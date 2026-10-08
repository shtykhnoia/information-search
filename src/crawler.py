import argparse
import hashlib
import sys
import time

import requests
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from .config import configure_utf8, emit, load_config
from .mediawiki import MediaWiki, NotArticle, article_revision, wiki_url


class Crawler:
    def __init__(self, config):
        self.config = config
        self.http = MediaWiki(config["logic"])
        settings = config.get("db", {})
        if (
            not isinstance(settings, dict)
            or not settings.get("uri")
            or not settings.get("database")
        ):
            raise ValueError("В db нужны uri и database для MongoDB")
        self.mongo = MongoClient(settings["uri"], serverSelectionTimeoutMS=5000)
        self.mongo.admin.command("ping")
        database = self.mongo[settings["database"]]
        self.documents = database.documents
        self.progress = database.progress
        self.documents.create_index("checked_at")

    def close(self):
        self.http.close()
        self.mongo.close()

    def download(self, source, title):
        page = self.http.page_info(source, title)
        url = wiki_url(source, page["title"])
        identity = f"{source['name']}:{page['pageid']}"
        old = self.documents.find_one({"_id": identity}, {"html": 0})
        now = int(time.time())
        if old and now - old["checked_at"] < self.config["logic"]["recrawl_seconds"]:
            emit("recent", source=source["name"], title=page["title"])
            return identity
        revision = page.get("lastrevid")
        if old and revision is not None and revision == old.get("revision_id"):
            self.documents.update_one(
                {"_id": identity},
                {"$set": {"checked_at": now, "url": url, "title": page["title"]}},
            )
            emit("unchanged", source=source["name"], title=page["title"])
            return identity
        headers = {}
        if old:
            for field, header in (
                ("etag", "If-None-Match"),
                ("last_modified", "If-Modified-Since"),
            ):
                if old.get(field):
                    headers[header] = old[field]
        response = self.http.html(source, url, headers)
        if response.status_code == 304:
            self.documents.update_one(
                {"_id": identity},
                {"$set": {"checked_at": now, "url": url, "title": page["title"]}},
            )
            emit("unchanged", source=source["name"], title=page["title"])
            return identity
        html = response.content.decode("utf-8")
        html_revision = article_revision(html)
        digest = hashlib.sha256(response.content).hexdigest()
        fields = {
            "checked_at": now,
            "url": url,
            "title": page["title"],
            "revision_id": html_revision or revision,
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
        }
        if old and old["sha256"] == digest:
            event = "unchanged"
        else:
            fields.update(
                url=url,
                html=html,
                source=source["name"],
                title=page["title"],
                timestamp=now,
                sha256=digest,
            )
            event = "updated" if old else "downloaded"
        self.documents.update_one({"_id": identity}, {"$set": fields}, upsert=True)
        emit(event, source=source["name"], title=page["title"])
        return identity

    def crawl_task(self, source, category=None):
        if category:
            task_id = source["base_url"] + ":" + category
            initial = {
                "_id": task_id,
                "batch": [],
                "index": 0,
                "continuation": {},
                "done": False,
            }
        else:
            titles = source["titles"]
            signature = hashlib.sha256("\n".join(titles).encode("utf-8")).hexdigest()[
                :16
            ]
            task_id = source["base_url"] + ":titles:" + signature
            initial = {
                "_id": task_id,
                "batch": titles,
                "index": 0,
                "continuation": None,
                "done": False,
            }
        self.progress.update_one(
            {"_id": task_id}, {"$setOnInsert": initial}, upsert=True
        )
        state = self.progress.find_one({"_id": task_id})
        while not state["done"]:
            if state["index"] < len(state["batch"]):
                title = state["batch"][state["index"]]
                try:
                    self.download(source, title)
                except NotArticle as error:
                    emit(
                        "skipped", source=source["name"], title=title, reason=str(error)
                    )
                state["index"] += 1
            elif state["continuation"] is None:
                state["done"] = True
            else:
                payload = self.http.api(
                    source,
                    action="query",
                    list="categorymembers",
                    cmtitle=category,
                    cmnamespace=0,
                    cmtype="page",
                    cmlimit=500,
                    **state["continuation"],
                )
                state["batch"] = [
                    page["title"] for page in payload["query"]["categorymembers"]
                ]
                state["index"] = 0
                state["continuation"] = payload.get("continue")
            self.progress.replace_one({"_id": task_id}, state)

    def refresh(self):
        sources = {source["name"]: source for source in self.config["sources"]}
        cutoff = int(time.time()) - self.config["logic"]["recrawl_seconds"]
        while True:
            document = self.documents.find_one(
                {"source": {"$in": list(sources)}, "checked_at": {"$lte": cutoff}},
                {"source": 1, "title": 1},
                sort=[("checked_at", 1), ("_id", 1)],
            )
            if document is None:
                return
            try:
                current_id = self.download(sources[document["source"]], document["title"])
                if current_id != document["_id"]:
                    self.documents.delete_one({"_id": document["_id"]})
            except NotArticle as error:
                self.documents.update_one(
                    {"_id": document["_id"]}, {"$set": {"checked_at": int(time.time())}}
                )
                emit("skipped", title=document["title"], reason=str(error))

    def run(self):
        for source in self.config["sources"]:
            if source["titles"]:
                self.crawl_task(source)
            if self.config["logic"]["crawl_categories"]:
                for category in source["categories"]:
                    self.crawl_task(source, category)
        while True:
            self.refresh()
            emit("complete", documents=self.documents.count_documents({}))
            if not self.config["logic"]["continuous"]:
                return
            time.sleep(min(60, self.config["logic"]["recrawl_seconds"]))


def main():
    configure_utf8()
    parser = argparse.ArgumentParser(description="Лабораторная 2: поисковый робот")
    parser.add_argument("config", help="Путь к YAML-конфигурации")
    args = parser.parse_args()
    crawler = None
    try:
        crawler = Crawler(load_config(args.config))
        crawler.run()
        return 0
    except KeyboardInterrupt:
        return 130
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        requests.RequestException,
        PyMongoError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        if crawler:
            crawler.close()


if __name__ == "__main__":
    raise SystemExit(main())
