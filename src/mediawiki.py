import re
import time
from urllib.parse import quote, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup


class NotArticle(ValueError):
    pass


def wiki_url(source, title):
    return (
        source["base_url"] + "/wiki/" + quote(title.replace(" ", "_"), safe="()_:,-!~'")
    )


class MediaWiki:
    def __init__(self, logic):
        self.logic = logic
        self.session = requests.Session()
        self.session.headers["User-Agent"] = logic["user_agent"]
        self.last_request = 0
        self.robots = {}

    def close(self):
        self.session.close()

    def get(self, url, params=None, headers=None, api=False):
        for attempt in range(self.logic["retries"] + 1):
            time.sleep(
                max(
                    0,
                    self.logic["delay_seconds"]
                    - (time.monotonic() - self.last_request),
                )
            )
            self.last_request = time.monotonic()
            retry_after = None
            try:
                with self.session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self.logic["timeout_seconds"],
                    stream=True,
                ) as response:
                    retry_after = response.headers.get("Retry-After")
                    if response.status_code in (429, 500, 502, 503, 504):
                        raise requests.ConnectionError(
                            f"HTTP {response.status_code}: {url}"
                        )
                    response.raise_for_status()
                    body = bytearray()
                    for chunk in response.iter_content(65536):
                        body.extend(chunk)
                        if len(body) > self.logic["max_document_bytes"]:
                            raise ValueError("Ответ превышает max_document_bytes")
                    response._content = bytes(body)
                    response.encoding = "utf-8"
                    if api:
                        payload = response.json()
                        if not isinstance(payload, dict):
                            raise ValueError("API должен вернуть JSON-объект")
                        if "error" in payload:
                            error = payload["error"]
                            if error.get("code") in (
                                "maxlag",
                                "ratelimited",
                                "readonly",
                            ):
                                raise requests.ConnectionError(str(error))
                            raise ValueError(f"API: {error}")
                        return payload
                    return response
            except (requests.ConnectionError, requests.Timeout):
                if attempt == self.logic["retries"]:
                    raise
                delay = min(60, 2**attempt)
                if retry_after:
                    from datetime import datetime, timezone
                    from email.utils import parsedate_to_datetime

                    try:
                        delay = max(0, float(retry_after))
                    except ValueError:
                        try:
                            delay = max(
                                0,
                                (
                                    parsedate_to_datetime(retry_after)
                                    - datetime.now(timezone.utc)
                                ).total_seconds(),
                            )
                        except (ValueError, TypeError):
                            pass
                time.sleep(delay)

    def api(self, source, **params):
        return self.get(
            source["base_url"] + "/w/api.php",
            params={**params, "format": "json", "formatversion": 2, "maxlag": 5},
            api=True,
        )

    def page_info(self, source, title):
        payload = self.api(
            source,
            action="query",
            prop="info|pageprops",
            ppprop="disambiguation",
            titles=title,
            redirects=1,
        )
        pages = payload["query"]["pages"]
        if (
            len(pages) != 1
            or "missing" in pages[0]
            or "invalid" in pages[0]
            or pages[0].get("ns") != 0
        ):
            raise NotArticle(f"Не найдена обычная статья: {title}")
        page = pages[0]
        if "disambiguation" in page.get("pageprops", {}):
            raise NotArticle(f"Страница неоднозначности: {title}")
        return page

    def check_robots(self, source, url):
        base = source["base_url"]
        if base not in self.robots:
            parser = RobotFileParser()
            parser.parse(
                self.get(base + "/robots.txt").content.decode("utf-8-sig").splitlines()
            )
            self.robots[base] = parser
        if not self.robots[base].can_fetch(self.logic["user_agent"], url):
            raise ValueError("robots.txt запрещает скачивание страницы")

    def html(self, source, url, headers=None):
        self.check_robots(source, url)
        response = self.get(url, headers=headers)
        if urlsplit(response.url).netloc != urlsplit(source["base_url"]).netloc:
            raise ValueError("Страница перенаправлена на другой источник")
        if response.status_code != 304:
            if "text/html" not in response.headers.get("Content-Type", "").lower():
                raise ValueError("Ожидался text/html")
            response.content.decode("utf-8")
        return response


def article_revision(html):
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one("#mw-content-text .mw-parser-output")
    if root is None:
        root = soup.select_one(".mw-parser-output")
    if root is None:
        raise ValueError("Не найден блок статьи mw-parser-output")
    revision = re.search(r'"wgRevisionId"\s*:\s*(\d+)', html)
    return int(revision[1]) if revision else None
