"""Synthetic HTML fixtures keep offline tests deterministic and copyright-light."""
import httpx
import pytest
from fastapi.testclient import TestClient

from book_api.app import create_app
from book_api.source import BASE, Source, SourceError, retry_after, safe_url

CARD = '''<article class="product_pod"><h3><a href="demo-book_1/index.html" title="Demo &amp; Book">Demo...</a></h3>
<p class="price_color">£12.30</p><p class="star-rating Three"></p><p class="availability">In stock</p></article>'''
NAV = '<div class="side_categories"><ul><li><ul><li><a href="category/books/fiction_10/index.html">Fiction</a></li></ul></li></ul></div>'
LIST = NAV + CARD + '<ul class="pager"><li class="current">Page 1 of 2</li><li class="next"><a href="page-2.html">next</a></li></ul>'
LAST = CARD + '<ul class="pager"><li class="current">Page 2 of 2</li></ul>'
DETAIL = '''<ul class="breadcrumb"><li><a>Home</a></li><li><a>Books</a></li><li><a>Fiction</a></li></ul>
<div class="product_main"><h1>Demo &amp; Book</h1><p class="price_color">£12.30</p><p class="star-rating Three"></p></div>
<table class="table-striped"><tr><th>UPC</th><td>fictional-upc</td></tr><tr><th>Availability</th><td>In stock (4 available)</td></tr><tr><th>Number of reviews</th><td>0</td></tr></table>'''


def html(value, status=200, headers=None):
    return httpx.Response(status, text=value, headers={"Content-Type": "text/html; charset=utf-8", **(headers or {})})


@pytest.fixture
def harness():
    calls = []
    def handle(request):
        calls.append(request.url.path)
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path.endswith("/demo-book_1/index.html"):
            return html(DETAIL)
        if path.endswith("page-1.html"):
            return html(LIST)
        if path.endswith("page-2.html"):
            return html(LAST)
        return html("missing", 404)
    source = Source(transport=httpx.MockTransport(handle), sleep=lambda _: None, interval=0)
    with TestClient(create_app(source)) as client:
        yield client, calls, source
    source.close()


def test_list_and_cache(harness):
    client, calls, _ = harness
    data = client.get("/api/v1/books").json()
    assert data["items"][0]["title"] == "Demo & Book"
    assert data["items"][0]["price"] == "12.30"
    assert data["items"][0]["rating"] == 3
    assert data["next_page"] == 2
    assert not data["cached"]
    assert client.get("/api/v1/books").json()["cached"]
    assert calls.count("/catalogue/page-1.html") == 1


def test_detail(harness):
    data = harness[0].get("/api/v1/books/demo-book_1").json()
    assert data["stock_quantity"] == 4
    assert data["upc"] == "fictional-upc"
    assert data["category"] == "Fiction"


def test_categories(harness):
    data = harness[0].get("/api/v1/categories").json()
    assert data["items"][0]["id"] == "fiction_10"


def test_bounded_search_and_filters(harness):
    client = harness[0]
    data = client.get("/api/v1/search", params={"q": "DEMO", "max_pages": 1}).json()
    assert data["match_count"] == 1 and not data["complete_catalogue"]
    assert data["next_start_page"] == 2
    data = client.get("/api/v1/search", params={"q": "demo", "min_rating": 4}).json()
    assert data["items"] == [] and data["complete_catalogue"]
    assert len(data["pages_scanned"]) == 2
    assert client.get("/api/v1/search", params={"q": "demo", "max_price": 1}).json()["items"] == []


@pytest.mark.parametrize("path", ["/api/v1/books?page=0", "/api/v1/books?page=1001", "/api/v1/books?category=https://evil.test", "/api/v1/books/not-an-id", "/api/v1/search?q=", "/api/v1/search?q=%20%20", "/api/v1/search?q=a&max_pages=6", "/api/v1/search?q=a&max_price=-1"])
def test_validation_without_upstream_calls(harness, path):
    assert harness[0].get(path).status_code == 422
    assert not harness[1]


def test_not_found(harness):
    response = harness[0].get("/api/v1/books/missing_999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_health_and_openapi(harness):
    client, calls, _ = harness
    assert client.get("/health").json()["upstream_checked"] is False
    assert "/api/v1/search" in client.get("/openapi.json").json()["paths"]
    assert not calls


@pytest.mark.parametrize("url", ["https://evil.test/catalogue/page-1.html", "http://books.toscrape.com/catalogue/page-1.html", BASE + "catalogue/../private", BASE + "catalogue/page-1.html?token=x", BASE + "catalogue/page-1.html#x"])
def test_fixed_origin(url):
    with pytest.raises(SourceError):
        safe_url(url)


@pytest.mark.parametrize("broken", [LIST.replace('class="price_color"', 'class="new-price"'), LIST.replace("£12.30", "$12.30"), LIST.replace("Three", "Unknown"), "<html>captcha</html>", LIST.replace('class="next"', 'class="gone"')])
def test_markup_drift_returns_502(broken):
    source = Source(transport=httpx.MockTransport(lambda r: httpx.Response(404) if r.url.path == "/robots.txt" else html(broken)), sleep=lambda _: None)
    with TestClient(create_app(source)) as client:
        response = client.get("/api/v1/books")
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "source_changed"
    source.close()


def test_robots_disallow():
    calls = []
    def handle(request):
        calls.append(request.url.path)
        return httpx.Response(200, text="User-agent: *\nDisallow: /catalogue/")
    source = Source(transport=httpx.MockTransport(handle), sleep=lambda _: None)
    with pytest.raises(SourceError, match="robots.txt"):
        source.get(BASE + "catalogue/page-1.html")
    assert calls == ["/robots.txt"]
    source.close()


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_retry_then_success(status):
    calls, waits = [], []
    def handle(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(1)
        return html("", status, {"Retry-After": "2"}) if len(calls) == 1 else html(LIST)
    source = Source(transport=httpx.MockTransport(handle), sleep=waits.append, interval=0)
    assert "product_pod" in source.get(BASE + "catalogue/page-1.html").html
    assert len(calls) == 2 and 2 in waits
    source.close()


def test_retry_exhaustion():
    calls = []
    def handle(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(1)
        return html("", 429)
    source = Source(transport=httpx.MockTransport(handle), sleep=lambda _: None)
    with pytest.raises(SourceError) as exc:
        source.get(BASE + "catalogue/page-1.html")
    assert exc.value.status == 503 and len(calls) == 3
    source.close()


def test_long_retry_after_does_not_retry_early():
    with pytest.raises(SourceError):
        retry_after("120", 0)


def test_timeouts_are_bounded():
    calls = []
    def handle(request):
        calls.append(1)
        raise httpx.ReadTimeout("synthetic timeout", request=request)
    source = Source(transport=httpx.MockTransport(handle), sleep=lambda _: None)
    with pytest.raises(SourceError) as exc:
        source.get(BASE + "catalogue/page-1.html")
    assert exc.value.status == 504 and len(calls) == 3
    source.close()


def test_expired_cache_refetches():
    now, calls = [0], []
    def handle(request):
        calls.append(request.url.path)
        return httpx.Response(404) if request.url.path == "/robots.txt" else html(LIST)
    source = Source(transport=httpx.MockTransport(handle), sleep=lambda _: None, clock=lambda: now[0], interval=0, ttl=5)
    source.get(BASE + "catalogue/page-1.html")
    now[0] = 6
    assert not source.get(BASE + "catalogue/page-1.html").cached
    assert calls.count("/catalogue/page-1.html") == 2
    source.close()


@pytest.mark.parametrize("status", [301, 302, 401, 403])
def test_no_redirect_or_access_bypass(status):
    calls = []
    def handle(request):
        calls.append(request.url.path)
        return httpx.Response(status, headers={"Location": "https://evil.test"})
    source = Source(transport=httpx.MockTransport(handle), sleep=lambda _: None)
    with pytest.raises(SourceError):
        source.get(BASE + "catalogue/page-1.html")
    assert len(calls) == 1
    source.close()


def test_robots_crawl_delay():
    waits = []
    source = Source(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="User-agent: *\nCrawl-delay: 3") if r.url.path == "/robots.txt" else html(LIST)), sleep=waits.append, clock=lambda: 0)
    source.get(BASE + "catalogue/page-1.html")
    assert 3 in waits
    source.close()


def test_oversized_html():
    source = Source(transport=httpx.MockTransport(lambda r: httpx.Response(404) if r.url.path == "/robots.txt" else html("x" * 2_000_001)), sleep=lambda _: None)
    with pytest.raises(SourceError) as exc:
        source.get(BASE + "catalogue/page-1.html")
    assert exc.value.code == "source_too_large"
    source.close()


def test_last_page_search_is_not_full_catalogue(harness):
    data = harness[0].get("/api/v1/search", params={"q": "demo", "start_page": 2}).json()
    assert data["next_start_page"] is None
    assert data["complete_catalogue"] is False
