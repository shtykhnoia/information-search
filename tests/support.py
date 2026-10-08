import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "tests/fixtures/article.html").read_text(encoding="utf-8")


class Site(BaseHTTPRequestHandler):
    calls = []
    revision = 1
    text = HTML
    forbidden = False
    fail_html = 0
    pause = None
    redirect_second = False

    def log_message(self, *args):
        pass

    def do_GET(self):
        cls = type(self)
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        cls.calls.append(
            {"path": parsed.path, "query": query, "headers": dict(self.headers)}
        )
        status = 200
        content_type = "text/html; charset=utf-8"
        if parsed.path == "/robots.txt":
            content_type = "text/plain"
            body = (
                "User-agent: *\nDisallow: /wiki/\n"
                if cls.forbidden
                else "User-agent: *\nDisallow:\n"
            )
        elif parsed.path == "/w/api.php":
            content_type = "application/json"
            if query.get("list") == ["categorymembers"]:
                if "cmcontinue" in query:
                    value = {
                        "query": {
                            "categorymembers": [
                                {"pageid": 2, "title": "Второй фильм", "ns": 0}
                            ]
                        }
                    }
                else:
                    value = {
                        "query": {
                            "categorymembers": [
                                {"pageid": 1, "title": "Тестовый фильм", "ns": 0}
                            ]
                        },
                        "continue": {"continue": "-||", "cmcontinue": "next"},
                    }
            else:
                title = query.get("titles", ["Тестовый фильм"])[0]
                if title == "Псевдоним" or (title == "Второй фильм" and cls.redirect_second):
                    title = "Тестовый фильм"
                value = {
                    "query": {
                        "pages": [
                            {
                                "pageid": 2 if title == "Второй фильм" else 1,
                                "title": title,
                                "ns": 0,
                                "lastrevid": cls.revision,
                            }
                        ]
                    }
                }
                if title == "Нет страницы":
                    value["query"]["pages"][0]["missing"] = True
                if title == "Неоднозначность":
                    value["query"]["pages"][0]["pageprops"] = {"disambiguation": ""}
            body = json.dumps(value, ensure_ascii=False)
        else:
            if cls.pause is not None:
                started, release = cls.pause
                started.set()
                release.wait(timeout=10)
            body = cls.text
            if cls.fail_html:
                cls.fail_html -= 1
                status = 503
            elif self.headers.get("If-None-Match") == f'"r{cls.revision}"':
                status = 304
                body = ""
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("ETag", f'"r{cls.revision}"')
        if status == 503:
            self.send_header("Retry-After", "0")
        try:
            self.end_headers()
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


class CliEnvironment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / ".work").mkdir(exist_ok=True)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / ".work")
        self.directory = Path(self.temporary.name)
        Site.calls = []
        Site.revision = 1
        Site.text = HTML
        Site.forbidden = False
        Site.fail_html = 0
        Site.pause = None
        Site.redirect_second = False

    def tearDown(self):
        if Site.pause:
            Site.pause[1].set()
        self.temporary.cleanup()

    def config(self, titles=None, categories=None, **logic):
        value = {
            "logic": {
                "delay_seconds": 0,
                "timeout_seconds": 3,
                "retries": 0,
                "recrawl_seconds": 1,
                "crawl_categories": bool(categories),
                **logic,
            },
            "sources": [
                {
                    "name": "wikipedia",
                    "base_url": self.base,
                    "titles": titles or ["Тестовый фильм"],
                    "categories": categories or [],
                },
                {
                    "name": "wikiquote",
                    "base_url": self.base,
                    "titles": titles or ["Тестовый фильм"],
                    "categories": categories or [],
                },
            ],
        }
        path = self.directory / "config.yaml"
        path.write_text(yaml.safe_dump(value, allow_unicode=True), encoding="utf-8")
        return path

    def cli(self, program, config):
        result = subprocess.run(
            [sys.executable, "-m", program, str(config)],
            cwd=ROOT,
            env=dict(os.environ, PYTHONUTF8="1", NO_PROXY="127.0.0.1,localhost"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        return result
