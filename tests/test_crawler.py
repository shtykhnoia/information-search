import os
import queue
import subprocess
import sys
import threading
import uuid

import yaml
from pymongo import MongoClient

from support import CliEnvironment, HTML, ROOT, Site


class CrawlerTests(CliEnvironment):
    def setUp(self):
        super().setUp()
        self.mongo = MongoClient(
            os.environ.get("TEST_MONGO_URI", "mongodb://127.0.0.1:27017"),
            serverSelectionTimeoutMS=3000,
        )
        self.mongo.admin.command("ping")
        self.database_name = "ir_test_" + uuid.uuid4().hex
        self.database = self.mongo[self.database_name]

    def tearDown(self):
        self.mongo.drop_database(self.database_name)
        self.mongo.close()
        super().tearDown()

    def config(self, titles=None, categories=None, **logic):
        path = super().config(titles=titles, categories=categories, **logic)
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        value["sources"] = value["sources"][:1]
        value["db"] = {
            "uri": os.environ.get("TEST_MONGO_URI", "mongodb://127.0.0.1:27017"),
            "database": self.database_name,
        }
        if categories:
            value["sources"][0]["titles"] = []
        path.write_text(yaml.safe_dump(value, allow_unicode=True), encoding="utf-8")
        return path

    def run_crawler(self, config):
        result = self.cli("src.crawler", config)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def make_due(self):
        self.database.documents.update_many({}, {"$set": {"checked_at": 0}})
        Site.calls.clear()

    def test_01_required_fields_and_alias_deduplication(self):
        self.run_crawler(self.config(titles=["Тестовый фильм", "Псевдоним"]))
        self.assertEqual(self.database.documents.count_documents({}), 1)
        document = self.database.documents.find_one({})
        self.assertEqual(document["html"], HTML)
        self.assertEqual(document["source"], "wikipedia")
        self.assertEqual(
            document["url"],
            self.base
            + "/wiki/%D0%A2%D0%B5%D1%81%D1%82%D0%BE%D0%B2%D1%8B%D0%B9_%D1%84%D0%B8%D0%BB%D1%8C%D0%BC",
        )
        self.assertIsInstance(document["timestamp"], int)

    def test_02_category_pagination(self):
        self.run_crawler(self.config(categories=["Категория:Фильмы"]))
        self.assertEqual(self.database.documents.count_documents({}), 2)
        requests = [
            call
            for call in Site.calls
            if call["query"].get("list") == ["categorymembers"]
        ]
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[1]["query"]["cmcontinue"], ["next"])
        self.assertTrue(self.database.progress.find_one({})["done"])

    def test_03_same_revision_does_not_download_html(self):
        config = self.config()
        self.run_crawler(config)
        old = self.database.documents.find_one({})
        self.make_due()
        result = self.run_crawler(config)
        self.assertIn('"unchanged"', result.stdout)
        self.assertFalse(any(call["path"].startswith("/wiki/") for call in Site.calls))
        new = self.database.documents.find_one({})
        self.assertEqual(new["timestamp"], old["timestamp"])
        self.assertEqual(new["html"], old["html"])
        self.assertGreater(new["checked_at"], 0)

    def test_04_changed_revision_updates_html(self):
        config = self.config()
        self.run_crawler(config)
        self.make_due()
        Site.revision = 2
        Site.text = HTML.replace("Анна Иванова", "Новая реплика").replace(
            '"wgRevisionId":1', '"wgRevisionId":2'
        )
        result = self.run_crawler(config)
        self.assertIn('"updated"', result.stdout)
        self.assertIn("Новая реплика", self.database.documents.find_one({})["html"])
        self.assertEqual(self.database.documents.count_documents({}), 1)

    def test_05_revision_changed_but_identical_html_keeps_timestamp(self):
        config = self.config()
        self.run_crawler(config)
        old = self.database.documents.find_one({})
        self.make_due()
        Site.revision = 2
        result = self.run_crawler(config)
        self.assertIn('"unchanged"', result.stdout)
        self.assertEqual(
            self.database.documents.find_one({})["timestamp"], old["timestamp"]
        )

    def test_06_http_304_keeps_html_and_timestamp(self):
        config = self.config()
        self.run_crawler(config)
        old = self.database.documents.find_one({})
        self.make_due()
        self.database.documents.update_one({}, {"$set": {"revision_id": None}})
        self.run_crawler(config)
        html_calls = [call for call in Site.calls if call["path"].startswith("/wiki/")]
        self.assertEqual(html_calls[0]["headers"]["If-None-Match"], '"r1"')
        self.assertEqual(
            self.database.documents.find_one({})["timestamp"], old["timestamp"]
        )

    def test_07_failed_page_is_retried_on_restart(self):
        config = self.config()
        Site.fail_html = 1
        result = self.cli("src.crawler", config)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.database.progress.find_one({})["index"], 0)
        self.assertEqual(self.database.documents.count_documents({}), 0)
        self.run_crawler(config)
        self.assertEqual(self.database.documents.count_documents({}), 1)

    def test_08_force_kill_during_download_resumes_current_page(self):
        config = self.config(categories=["Категория:Фильмы"])
        started, release = threading.Event(), threading.Event()
        Site.pause = (started, release)
        process = subprocess.Popen(
            [sys.executable, "-m", "src.crawler", str(config)],
            cwd=ROOT,
            env=dict(os.environ, PYTHONUTF8="1", NO_PROXY="127.0.0.1,localhost"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            self.assertTrue(started.wait(10), "Робот не начал скачивание")
            process.kill()
            process.communicate(timeout=10)
            state = self.database.progress.find_one({})
            self.assertEqual(state["batch"], ["Тестовый фильм"])
            self.assertEqual(state["index"], 0)
            self.assertEqual(self.database.documents.count_documents({}), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
            release.set()
            Site.pause = None
        Site.calls.clear()
        self.run_crawler(config)
        titles = [
            call["query"]["titles"][0]
            for call in Site.calls
            if "titles" in call["query"]
        ]
        self.assertEqual(titles, ["Тестовый фильм", "Второй фильм"])
        self.assertEqual(self.database.documents.count_documents({}), 2)

    def test_09_stop_after_save_before_checkpoint_does_not_duplicate(self):
        config = self.config()
        self.run_crawler(config)
        self.database.progress.update_one({}, {"$set": {"index": 0, "done": False}})
        Site.calls.clear()
        self.run_crawler(config)
        self.assertEqual(self.database.documents.count_documents({}), 1)
        self.assertFalse(any(call["path"].startswith("/wiki/") for call in Site.calls))

    def test_10_disambiguation_does_not_stop_category(self):
        self.run_crawler(self.config(titles=["Неоднозначность", "Тестовый фильм"]))
        self.assertEqual(self.database.documents.count_documents({}), 1)

    def test_11_missing_database_configuration_fails_clearly(self):
        config = self.config()
        value = yaml.safe_load(config.read_text(encoding="utf-8"))
        value.pop("db")
        config.write_text(yaml.safe_dump(value, allow_unicode=True), encoding="utf-8")
        result = self.cli("src.crawler", config)
        self.assertEqual(result.returncode, 1)
        self.assertIn("db", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_12_continuous_mode_checks_changes_without_restart(self):
        config = self.config()
        value = yaml.safe_load(config.read_text(encoding="utf-8"))
        value["logic"]["continuous"] = True
        config.write_text(yaml.safe_dump(value, allow_unicode=True), encoding="utf-8")
        process = subprocess.Popen(
            [sys.executable, "-m", "src.crawler", str(config)],
            cwd=ROOT,
            env=dict(os.environ, PYTHONUTF8="1", NO_PROXY="127.0.0.1,localhost"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        output = queue.Queue()

        def read_output():
            for line in process.stdout:
                output.put(line)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        try:
            for _ in range(10):
                if '"complete"' in output.get(timeout=10):
                    break
            else:
                self.fail("Первый проход не завершён")
            Site.revision = 2
            Site.text = HTML.replace("Анна Иванова", "Периодическое обновление")
            for _ in range(10):
                if '"updated"' in output.get(timeout=10):
                    break
            else:
                self.fail("Изменение не проверено")
            self.assertIn(
                "Периодическое обновление", self.database.documents.find_one({})["html"]
            )
        finally:
            process.kill()
            process.wait(timeout=10)
            reader.join(timeout=10)
            process.stdout.close()
            process.stderr.close()

    def test_13_article_becomes_redirect_after_download(self):
        config = self.config(titles=["Тестовый фильм", "Второй фильм"])
        self.run_crawler(config)
        self.assertEqual(self.database.documents.count_documents({}), 2)
        self.make_due()
        Site.redirect_second = True
        self.run_crawler(config)
        self.assertEqual(self.database.documents.count_documents({}), 1)
        self.assertEqual(self.database.documents.find_one({})["title"], "Тестовый фильм")

    def test_14_missing_article_block_is_not_saved(self):
        Site.text = "<p>Captcha</p>"
        result = self.cli("src.crawler", self.config())
        self.assertEqual(result.returncode, 1)
        self.assertIn("mw-parser-output", result.stderr)
        self.assertEqual(self.database.documents.count_documents({}), 0)

    def test_15_robots_forbid_html(self):
        Site.forbidden = True
        result = self.cli("src.crawler", self.config())
        self.assertEqual(result.returncode, 1)
        self.assertIn("robots.txt", result.stderr)
        self.assertFalse(any(call["path"].startswith("/wiki/") for call in Site.calls))

    def test_16_retry_temporary_http_error(self):
        Site.fail_html = 1
        self.run_crawler(self.config(retries=1))
        self.assertEqual(self.database.documents.count_documents({}), 1)

    def test_17_invalid_yaml_and_delay(self):
        for value in (-1, True, "bad", float("nan")):
            with self.subTest(value=value):
                result = self.cli("src.crawler", self.config(delay_seconds=value))
                self.assertEqual(result.returncode, 1)
                self.assertNotIn("Traceback", result.stderr)
        path = self.directory / "broken.yaml"
        path.write_text("logic: [", encoding="utf-8")
        result = self.cli("src.crawler", path)
        self.assertEqual(result.returncode, 1)
        self.assertIn("YAML", result.stderr)

    def test_18_limit_response_size(self):
        result = self.cli("src.crawler", self.config(max_document_bytes=200))
        self.assertEqual(result.returncode, 1)
        self.assertIn("max_document_bytes", result.stderr)
        self.assertEqual(self.database.documents.count_documents({}), 0)
