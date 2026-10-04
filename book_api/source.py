"""Public HTML fetcher: fixed origin, robots policy, throttling, TTL cache."""
import math
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

BASE = "https://books.toscrape.com/"
AGENT = "BooksAssignmentBot"
SLUG = r"[a-z0-9][a-z0-9_-]*_[0-9]+"
PATH = re.compile(rf"(?:robots\.txt|catalogue/(?:page-[1-9][0-9]*\.html|{SLUG}/index\.html|category/books/{SLUG}/(?:index|page-[1-9][0-9]*)\.html))$")


class SourceError(Exception):
    def __init__(self, code, message, status=502):
        self.code, self.status = code, status
        super().__init__(message)


def safe_url(href, base=BASE):
    url = urljoin(base, href)
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "books.toscrape.com" or parts.query or parts.fragment:
        raise SourceError("source_changed", "Source contains an unsupported link")
    if not PATH.fullmatch(parts.path.lstrip("/")):
        raise SourceError("source_changed", "Source contains an unexpected catalogue path")
    return url


@dataclass(frozen=True)
class Page:
    html: str
    url: str
    fetched_at: str
    cached: bool = False


def retry_after(value, attempt):
    if value:
        try:
            delay = float(value)
        except ValueError:
            try:
                delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                delay = -1
        if math.isfinite(delay) and delay >= 0:
            if delay > 10:
                raise SourceError("upstream_busy", "Source requested a longer wait; try again later", 503)
            return delay
    return 2 ** attempt


class Source:
    def __init__(self, *, transport=None, sleep=time.sleep, clock=time.monotonic, interval=1.0, ttl=300):
        self.http = httpx.Client(transport=transport, timeout=httpx.Timeout(10, connect=5),
            follow_redirects=False, trust_env=False,
            headers={"User-Agent": f"{AGENT}/1.0 (educational read-only catalogue API)", "Accept": "text/html"})
        self.sleep, self.clock, self.interval, self.ttl = sleep, clock, interval, ttl
        self.policy_interval = interval
        self.cache = OrderedDict()
        self.lock = threading.Lock()
        self.last_request = float("-inf")
        self.robot = None
        self.robot_checked = float("-inf")

    def close(self):
        self.http.close()

    def _download(self, url, robots=False):
        for attempt in range(3):
            self.sleep(max(0, self.policy_interval - (self.clock() - self.last_request)))
            self.last_request = self.clock()
            try:
                with self.http.stream("GET", url) as response:
                    status = response.status_code
                    if robots and status == 404:
                        return ""
                    if status == 404:
                        raise SourceError("not_found", "Book, category or page does not exist", 404)
                    if status in (401, 403):
                        raise SourceError("source_denied", "Source denied access; no bypass attempted", 503)
                    if status == 429 or status in (502, 503, 504):
                        if attempt == 2:
                            raise SourceError("upstream_busy", "Source unavailable after three attempts", 503)
                        delay = retry_after(response.headers.get("Retry-After"), attempt)
                    elif status != 200:
                        raise SourceError("source_http_error", f"Unexpected source HTTP status: {status}")
                    else:
                        if not robots and "text/html" not in response.headers.get("content-type", ""):
                            raise SourceError("source_changed", "Expected an HTML page")
                        body = bytearray()
                        for chunk in response.iter_bytes():
                            body.extend(chunk)
                            if len(body) > 2_000_000:
                                raise SourceError("source_too_large", "Source response exceeds 2 MB")
                        return body.decode("utf-8", errors="strict")
            except httpx.TimeoutException:
                if attempt == 2:
                    raise SourceError("source_timeout", "Source timed out after three attempts", 504) from None
                delay = 2 ** attempt
            except httpx.TransportError:
                if attempt == 2:
                    raise SourceError("source_unreachable", "Could not reach the source", 503) from None
                delay = 2 ** attempt
            except UnicodeDecodeError:
                raise SourceError("source_changed", "Source encoding is no longer UTF-8") from None
            self.sleep(delay)

    def get(self, url):
        url = safe_url(url)
        # Bound waiting callers; serialize fetches to protect the upstream origin.
        if not self.lock.acquire(timeout=2):
            raise SourceError("connector_busy", "Another fetch is in progress; retry shortly", 503)
        try:
            if self.clock() - self.robot_checked >= self.ttl:
                rules = self._download(BASE + "robots.txt", robots=True)
                robot = RobotFileParser()
                robot.parse(rules.splitlines())
                self.robot = robot
                self.robot_checked = self.clock()
                delay = robot.crawl_delay(AGENT) or 0
                rate = robot.request_rate(AGENT)
                rate_interval = rate.seconds / rate.requests if rate and rate.requests > 0 else 0
                self.policy_interval = max(self.interval, delay, rate_interval)
            if self.policy_interval > 10:
                raise SourceError("robots_rate_limit", "Source crawl delay exceeds the interactive request budget", 503)
            if not self.robot.can_fetch(AGENT, url):
                raise SourceError("robots_denied", "robots.txt disallows this path", 503)
            cached = self.cache.get(url)
            if cached and self.clock() - cached[0] < self.ttl:
                self.cache.move_to_end(url)
                page = cached[1]
                return Page(page.html, page.url, page.fetched_at, True)
            html = self._download(url)
            page = Page(html, url, datetime.now(timezone.utc).isoformat())
            self.cache[url] = (self.clock(), page)
            self.cache.move_to_end(url)
            if len(self.cache) > 128:
                self.cache.popitem(last=False)
            return page
        finally:
            self.lock.release()
