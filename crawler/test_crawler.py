import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

import requests
import yaml
from pymongo import MongoClient

from crawler import Crawler, normalize_url

MONGO_URI = os.environ.get("TEST_MONGO_URI", "mongodb://127.0.0.1:27017")
CRAWLER = Path(__file__).with_name("crawler.py")
CATEGORY_BATCHES = [["Матрица (фильм)", "Интерстеллар"], ["Во все тяжкие", "Скрытая страница"]]


class FakeWiki(BaseHTTPRequestHandler):
    visited = []
    last_modified = "Wed, 07 Oct 2026 10:00:00 GMT"
    broken_batch = None
    rate_limited_requests = 0

    def do_GET(self):
        url = urlsplit(self.path)
        FakeWiki.visited.append(unquote(self.path))
        if FakeWiki.rate_limited_requests:
            FakeWiki.rate_limited_requests -= 1
            self.reply(429, "")
        elif url.path == "/robots.txt":
            self.reply(200, "User-agent: *\nDisallow: /wiki/Скрытая")
        elif url.path == "/w/api.php":
            batch = int(parse_qs(url.query).get("gcmcontinue", ["0"])[0])
            self.reply(500 if batch == FakeWiki.broken_batch else 200, json.dumps(self.category_batch(batch)))
        elif self.headers.get("If-Modified-Since") == FakeWiki.last_modified:
            self.reply(304, "")
        else:
            self.reply(200, f"<html>{unquote(url.path)} {FakeWiki.last_modified}</html>")

    def category_batch(self, batch):
        host = f"http://{self.headers['Host']}"
        pages = [{"fullurl": f"{host}/wiki/{quote(title.replace(' ', '_'), safe='()')}"} for title in FakeWiki.category_batches[batch]]
        response = {"query": {"pages": pages}}
        if batch + 1 < len(FakeWiki.category_batches):
            response["continue"] = {"gcmcontinue": str(batch + 1), "continue": "gcmcontinue||"}
        return response

    def reply(self, status, body):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Last-Modified", FakeWiki.last_modified)
        if status == 429:
            self.send_header("Retry-After", "0")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class CrawlerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeWiki)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.mongo = MongoClient(MONGO_URI)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.mongo.close()

    def setUp(self):
        FakeWiki.visited = []
        FakeWiki.last_modified = "Wed, 07 Oct 2026 10:00:00 GMT"
        FakeWiki.broken_batch = None
        FakeWiki.rate_limited_requests = 0
        FakeWiki.category_batches = [list(batch) for batch in CATEGORY_BATCHES]
        self.db_name = "test_" + uuid.uuid4().hex
        self.db = self.mongo[self.db_name]
        self.config = {
            "db": {"uri": MONGO_URI, "name": self.db_name},
            "logic": {"delay_seconds": 0, "recrawl_seconds": 3600, "user_agent": "test"},
            "sources": [{"name": "wikipedia", "url": self.base_url, "categories": ["Категория:Фильмы"]}],
        }

    def tearDown(self):
        self.mongo.drop_database(self.db_name)

    def crawl_all(self):
        crawler = Crawler(self.config, self.db)
        crawler.discover(self.config["sources"][0])
        for page in crawler.frontier.find():
            crawler.crawl(page)

    def start_crawler_process(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config_path = Path(directory.name) / "config.yaml"
        config_path.write_text(yaml.safe_dump(self.config, allow_unicode=True), encoding="utf-8")
        process = subprocess.Popen([sys.executable, CRAWLER, config_path], stderr=subprocess.DEVNULL)
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        return process

    def wait_until(self, condition):
        deadline = time.time() + 10
        while not condition():
            self.assertLess(time.time(), deadline, "не дождались условия")
            time.sleep(0.05)

    def test_normalize_url(self):
        self.assertEqual(normalize_url("HTTPS://Ru.Wikipedia.org/wiki/A_(b)#c"), "https://ru.wikipedia.org/wiki/A_%28b%29")
        self.assertEqual(
            normalize_url("https://ru.wikipedia.org/wiki/%D0%A4%D0%B8%D0%BB%D1%8C%D0%BC"),
            normalize_url("https://ru.wikipedia.org/wiki/Фильм"),
        )

    def test_saves_documents_with_required_fields(self):
        self.crawl_all()
        document = self.db.documents.find_one({"url": normalize_url(f"{self.base_url}/wiki/Матрица_(фильм)")})
        self.assertIn("/wiki/Матрица_(фильм)", document["html"])
        self.assertEqual(document["source"], "wikipedia")
        self.assertAlmostEqual(document["crawled_at"], time.time(), delta=10)
        self.assertEqual(self.db.documents.count_documents({}), 3)

    def test_skips_pages_forbidden_by_robots(self):
        self.crawl_all()
        self.assertNotIn("/wiki/Скрытая_страница", FakeWiki.visited)

    def test_resumes_category_listing_after_failure(self):
        FakeWiki.broken_batch = 1
        with self.assertRaises(requests.HTTPError):
            Crawler(self.config, self.db).discover(self.config["sources"][0])

        FakeWiki.broken_batch = None
        FakeWiki.visited = []
        Crawler(self.config, self.db).discover(self.config["sources"][0])
        api_calls = [path for path in FakeWiki.visited if path.startswith("/w/api.php")]
        self.assertEqual(len(api_calls), 1)
        self.assertIn("gcmcontinue=1", api_calls[0])
        self.assertEqual(self.db.frontier.count_documents({}), 3)

    def test_finds_new_pages_in_category_after_recrawl_interval(self):
        self.config["logic"]["recrawl_seconds"] = 1
        self.start_crawler_process()
        self.wait_until(lambda: self.db.documents.count_documents({}) == 3)
        FakeWiki.category_batches[1].append("Новый фильм")
        self.wait_until(lambda: self.db.documents.count_documents({}) == 4)

    def test_waits_and_retries_when_rate_limited(self):
        FakeWiki.rate_limited_requests = 2
        self.crawl_all()
        self.assertEqual(self.db.documents.count_documents({}), 3)

    def test_resumes_crawl_after_kill(self):
        self.config["logic"]["delay_seconds"] = 0.2
        process = self.start_crawler_process()
        self.wait_until(lambda: self.db.documents.count_documents({}) >= 2)
        process.kill()
        process.wait()

        FakeWiki.visited = []
        self.start_crawler_process()
        self.wait_until(lambda: self.db.documents.count_documents({}) == 3)
        self.assertNotIn("/wiki/Матрица_(фильм)", FakeWiki.visited)
        self.assertFalse(any(path.startswith("/w/api.php") for path in FakeWiki.visited))

    def test_recrawl_keeps_unchanged_page(self):
        self.crawl_all()
        self.db.documents.update_many({}, {"$set": {"crawled_at": 0}})
        self.crawl_all()
        self.assertEqual(self.db.documents.count_documents({"crawled_at": 0}), 3)

    def test_recrawl_updates_changed_page(self):
        self.crawl_all()
        self.db.documents.update_many({}, {"$set": {"crawled_at": 0}})
        FakeWiki.last_modified = "Thu, 08 Oct 2026 10:00:00 GMT"
        self.crawl_all()
        self.assertEqual(self.db.documents.count_documents({"crawled_at": {"$gt": 0}}), 3)
        self.assertEqual(self.db.documents.count_documents({"html": {"$regex": "08 Oct"}}), 3)

    def test_periodically_recrawls_changed_pages(self):
        self.config["logic"]["recrawl_seconds"] = 1
        self.start_crawler_process()
        self.wait_until(lambda: self.db.documents.count_documents({}) == 3)
        FakeWiki.last_modified = "Thu, 08 Oct 2026 10:00:00 GMT"
        self.wait_until(lambda: self.db.documents.count_documents({"html": {"$regex": "08 Oct"}}) == 3)


if __name__ == "__main__":
    unittest.main()
