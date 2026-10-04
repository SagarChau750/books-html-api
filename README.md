# Books HTML API

**Razorpay Forward-Deployed Engineer assignment — Option 1: reverse-engineer an API.**

A Python REST API that turns the public HTML catalogue at
[Books to Scrape](https://books.toscrape.com/) into structured JSON. It provides book
listing, detail lookup, categories, and bounded title search without login, cookies,
API keys, private data, or access-control bypasses.

The source is a scraping sandbox, not a real merchant: prices and ratings are
fictional. No documented public API was identified in its public interface; this
implementation reads HTML rather than wrapping an existing JSON API. This is an
independent educational project, not an official Books to Scrape API.

## Quick start

Requires Python 3.11+ and internet access for live requests.

```powershell
# Windows PowerShell, from the repository directory
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe index.py
```

macOS/Linux equivalent:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python index.py
```

Open **http://127.0.0.1:8000/docs** for interactive Swagger documentation. Click an
endpoint, select **Try it out**, and then **Execute**. The root URL redirects there.
The server binds to loopback only. No credentials or environment configuration are needed.

## API

| Method and path | Purpose | Example |
|---|---|---|
| `GET /health` | Process health, no upstream request | `/health` |
| `GET /api/v1/books` | One catalogue page | `?page=2` |
| `GET /api/v1/books` | Books in a category | `?category=travel_2` |
| `GET /api/v1/books/{book_id}` | Product metadata and stock | `a-light-in-the-attic_1000` |
| `GET /api/v1/categories` | Names, IDs, source URLs | No parameters |
| `GET /api/v1/search` | Case-insensitive title substring, rating/price filters | `?q=light&max_pages=2&min_rating=3` |
| `GET /openapi.json` | Machine-readable endpoint/input specification | No parameters |

IDs are source URL slugs, not database IDs. Always take them from list responses.
Prices are decimal **strings** in GBP, avoiding JSON floating-point rounding.
Lists expose `page`, `total_pages`, and `next_page`. Responses include source URLs,
UTC `fetched_at`, and `cached` so consumers can assess provenance and freshness.

Example request in PowerShell:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/books?page=1'
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/search?q=light&max_pages=1'
```

### Search coverage is explicit

The website has no search interface used by this adapter. We implement substring
matching over a bounded sequence of catalogue pages. `max_pages` defaults to 2 and
cannot exceed 5; each upstream page normally has 20 books. Continue using
`next_start_page`. `complete_catalogue` is true only when a request scanned from
page 1 through the last page. An empty partial result does **not** mean the entire
catalogue has no match. Filters apply only to the scanned pages. There is no hidden
full-site crawl during startup or each search request.

## Test and demonstrate

Offline tests use synthetic HTML and mocked HTTP, requiring no upstream access:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

With the API running, open a second terminal and run the required working test script:

```powershell
.\.venv\Scripts\python.exe scripts/smoke_test.py
```

The script validates real list/detail consistency, categories, category filtering,
pagination, positive/negative search, invalid inputs, and a nonexistent book. It exits
nonzero if an assertion or HTTP call fails. Unit tests separately exercise retries,
timeouts, robots restrictions, cache expiration, redirects, and markup drift.

**Recorded local verification (4 October 2026):** 40 offline tests and 11 live HTTP
checks passed on Python 3.11 / Windows. These are observations, not a guarantee of
future source availability. GitHub Actions runs offline tests only. The installed
Starlette version emits a deprecation warning for its HTTPX test adapter; tests pass.

For a two-minute walkthrough, show `/docs`, execute a listing, copy a book ID into
the detail endpoint, perform a search and explain its coverage, then run the test
script and show an invalid-input response.

## Design

```text
HTTP client / Swagger UI
          |
FastAPI routes + input validation
          |
Explicit HTML parsers
          |
Fixed-origin fetcher + robots policy + cache + request pacing
          |
Public Books to Scrape HTML pages
```

- `book_api/app.py`: API contract, search orchestration, error mapping.
- `book_api/source.py`: fixed HTTPS origin, no redirects, 1 request/second minimum
  spacing, three attempts maximum, 5-second connect / 10-second I/O timeouts,
  `Retry-After` handling, 2 MB decoded response limit, 128-page / 5-minute cache.
- `book_api/parser.py`: validated selectors for cards, categories, details and pagination.
- `tests/test_api.py`: deterministic parser, API, transport and policy regression tests.
- `scripts/smoke_test.py`: end-to-end test through the running HTTP service.

Robots rules are refreshed every five minutes. A missing robots.txt (404) is treated
as no declared restrictions; fetch errors or denial stop scraping. Authentication
errors are never bypassed, and redirects are rejected. Requests are serialized;
callers waiting over two seconds receive a retryable busy error. Cache state is
process-local: run one worker for the documented upstream request budget.

## Errors

| Status | Meaning |
|---|---|
| 404 | Source book, category or page was not found |
| 422 | Invalid query, page, category or book ID |
| 502 | Unexpected HTML, content type, source status or response size |
| 503 | Robots denial, access denial, busy connector or unavailable source |
| 504 | Upstream timed out after bounded retries |

Source failures return `{"error":{"code":"...","message":"..."}}`. FastAPI's
parameter-validation errors use its standard `detail` array. No upstream HTML body
or stack trace is returned to API consumers. See [LIMITATIONS.md](LIMITATIONS.md)
for scope, tradeoffs and the appropriate long-term fix.

## Publish to GitHub

Create an empty repository named `books-html-api`, then run:

```powershell
git remote add origin https://github.com/YOUR_USERNAME/books-html-api.git
git push -u origin main
```

If this is a fresh copy without Git metadata, run `git init -b main`, `git add .`,
and `git commit -m "Build public books HTML API"` first. Use your own Git identity.
Only this project belongs in the repository; do not upload `.venv`, credentials, or
the previous WooCommerce backup. No hosted deployment is required by the assignment.

## References

- [Source catalogue and scraping-sandbox notice](https://books.toscrape.com/)
- [Representative detail page](https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html)
- [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/)
- [HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/)
