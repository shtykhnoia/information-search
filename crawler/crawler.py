import argparse
import logging
import time
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests
import yaml
from pymongo import MongoClient
from pymongo.errors import DocumentTooLarge

REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_RETRY_AFTER_SECONDS = 60

log = logging.getLogger("crawler")


def normalize_url(url):
    scheme, host, path, query, _ = urlsplit(url)
    return urlunsplit((scheme.lower(), host.lower(), quote(unquote(path)), query, ""))


class Crawler:
    def __init__(self, config, db):
        logic = config["logic"]
        self.delay_seconds = logic["delay_seconds"]
        self.recrawl_seconds = logic["recrawl_seconds"]
        self.user_agent = logic["user_agent"]
        self.sources = config["sources"]

        self.http = requests.Session()
        self.http.headers["User-Agent"] = self.user_agent

        self.documents = db.documents
        self.frontier = db.frontier
        self.categories = db.categories
        self.documents.create_index("url", unique=True)
        self.frontier.create_index("url", unique=True)
        self.frontier.create_index([("next_crawl", 1), ("_id", 1)])

    def run(self):
        while True:
            for source in self.sources:
                self.discover(source)
            pass_started = time.time()
            while page := self.frontier.find_one({"next_crawl": {"$lte": pass_started}}, sort=[("next_crawl", 1), ("_id", 1)]):
                self.crawl(page)
            next_page = self.frontier.find_one(sort=[("next_crawl", 1)])
            next_check = next_page["next_crawl"] if next_page else time.time() + self.recrawl_seconds
            log.info("проход завершён, следующая проверка: %s", time.ctime(next_check))
            time.sleep(max(0, next_check - time.time()))

    def discover(self, source):
        robots = RobotFileParser()
        robots.parse(self.get(source["url"] + "/robots.txt").text.splitlines())
        for category in source["categories"]:
            self.discover_category(source, category, robots)

    def discover_category(self, source, category, robots):
        state_id = f"{source['name']}:{category}"
        state = self.categories.find_one({"_id": state_id})
        if state is None or (state["done"] and state["listed_at"] + self.recrawl_seconds <= time.time()):
            state = {"_id": state_id, "continue": {}, "done": False}
        while not state["done"]:
            response = self.get(source["url"] + "/w/api.php", params={
                "action": "query",
                "format": "json",
                "formatversion": 2,
                "generator": "categorymembers",
                "gcmtitle": category,
                "gcmnamespace": 0,
                "gcmlimit": "max",
                "prop": "info",
                "inprop": "url",
                **state["continue"],
            }).json()
            pages = response.get("query", {}).get("pages", [])
            for page in pages:
                url = normalize_url(page["fullurl"])
                if robots.can_fetch(self.user_agent, url):
                    self.frontier.update_one(
                        {"url": url},
                        {"$setOnInsert": {"source": source["name"], "next_crawl": 0}},
                        upsert=True,
                    )
            state["continue"] = response.get("continue", {})
            state["done"] = "continue" not in response
            state["listed_at"] = int(time.time())
            self.categories.replace_one({"_id": state_id}, state, upsert=True)
            log.info("%s: найдено %d страниц", state_id, len(pages))

    def crawl(self, page):
        url = page["url"]
        headers = {"If-Modified-Since": page["last_modified"]} if page.get("last_modified") else {}
        update = {"next_crawl": int(time.time()) + self.recrawl_seconds}
        try:
            response = self.get(url, headers=headers)
            if response.status_code == 304:
                log.info("не изменилась %s", unquote(url))
            else:
                self.documents.replace_one({"url": url}, {
                    "url": url,
                    "html": response.text,
                    "source": page["source"],
                    "crawled_at": int(time.time()),
                }, upsert=True)
                update["last_modified"] = response.headers.get("Last-Modified")
                log.info("скачана %s", unquote(url))
        except (requests.HTTPError, DocumentTooLarge) as error:
            log.warning("ошибка %s: %s", unquote(url), error)
        self.frontier.update_one({"_id": page["_id"]}, {"$set": update})

    def get(self, url, **kwargs):
        while True:
            time.sleep(self.delay_seconds)
            response = self.http.get(url, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)
            if response.status_code != 429:
                break
            retry_after = response.headers.get("Retry-After", "")
            wait_seconds = int(retry_after) if retry_after.isdigit() else DEFAULT_RETRY_AFTER_SECONDS
            log.warning("сервер просит подождать %d с", wait_seconds)
            time.sleep(wait_seconds)
        response.raise_for_status()
        return response


def main():
    parser = argparse.ArgumentParser(description="Поисковый робот")
    parser.add_argument("config", help="путь до yaml-конфига")
    args = parser.parse_args()
    with open(args.config, encoding="utf-8") as file:
        config = yaml.safe_load(file)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    with MongoClient(config["db"]["uri"]) as mongo:
        try:
            Crawler(config, mongo[config["db"]["name"]]).run()
        except KeyboardInterrupt:
            log.info("остановлен")


if __name__ == "__main__":
    main()
