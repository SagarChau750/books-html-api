from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, RedirectResponse

from . import parser
from .source import BASE, SLUG, Source, SourceError


def create_app(source=None):
    owned = source is None
    source = source or Source()

    @asynccontextmanager
    async def lifespan(app):
        yield
        if owned:
            source.close()

    app = FastAPI(title="Books HTML API", version="1.0.0", lifespan=lifespan,
        description="Assignment 1: public HTML to JSON. Fictional prices/ratings from Books to Scrape. No official affiliation. Search is explicitly bounded; consult coverage fields.")

    @app.exception_handler(SourceError)
    async def source_error(request, exc):
        return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": str(exc)}},
                            headers={"Retry-After": "10"} if exc.status == 503 else None)

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/docs")

    @app.get("/health", tags=["Status"])
    def health():
        """Process health only; does not claim the upstream website is available."""
        return {"status": "ok", "source": BASE, "upstream_checked": False}

    def get_list(page, category=None):
        if category:
            filename = "index.html" if page == 1 else f"page-{page}.html"
            path = f"catalogue/category/books/{category}/{filename}"
        else:
            path = f"catalogue/page-{page}.html"
        result = parser.catalogue(source.get(BASE + path))
        if result["page"] != page:
            raise SourceError("source_changed", "Source returned an unexpected page")
        return result

    @app.get("/api/v1/books", tags=["Books"])
    def list_books(page: Annotated[int, Query(ge=1, le=1000)] = 1,
                   category: Annotated[str | None, Query(pattern=f"^{SLUG}$", max_length=150)] = None):
        """One upstream page (normally 20 books). Category IDs come from /categories."""
        return get_list(page, category)

    @app.get("/api/v1/categories", tags=["Categories"])
    def list_categories():
        """Read category names and IDs from public navigation."""
        return parser.categories(source.get(BASE + "catalogue/page-1.html"))

    @app.get("/api/v1/search", tags=["Search"])
    def search(q: Annotated[str, Query(min_length=1, max_length=100)],
               start_page: Annotated[int, Query(ge=1, le=1000)] = 1,
               max_pages: Annotated[int, Query(ge=1, le=5)] = 2,
               min_rating: Annotated[int, Query(ge=1, le=5)] = 1,
               max_price: Annotated[float | None, Query(ge=0, le=100000)] = None):
        """Case-insensitive title substring search over at most five pages. No match is NOT a claim about unscanned pages."""
        query = q.strip().casefold()
        if not query:
            return JSONResponse(status_code=422, content={"error": {"code": "invalid_query", "message": "Query cannot be whitespace"}})
        items, pages = [], []
        for number in range(start_page, start_page + max_pages):
            result = get_list(number)
            pages.append({key: result[key] for key in ("page", "source_url", "fetched_at", "cached")})
            items.extend(book for book in result["items"] if query in book["title"].casefold()
                         and book["rating"] >= min_rating
                         and (max_price is None or float(book["price"]) <= max_price))
            if result["next_page"] is None:
                break
        return {"query": q.strip(), "items": items, "match_count": len(items), "pages_scanned": pages,
            "total_source_pages": result["total_pages"], "next_start_page": result["next_page"],
            "complete_catalogue": start_page == 1 and result["next_page"] is None,
            "notice": "Matches cover scanned pages only. Continue with next_start_page for further results."}

    @app.get("/api/v1/books/{book_id}", tags=["Books"])
    def get_book(book_id: str):
        """Use an opaque slug ID from the list response. IDs can change if source URLs change."""
        import re
        if len(book_id) > 250 or not re.fullmatch(SLUG, book_id):
            return JSONResponse(status_code=422, content={"error": {"code": "invalid_id", "message": "Use a book ID returned by the list endpoint"}})
        return parser.detail(source.get(BASE + f"catalogue/{book_id}/index.html"))

    return app


app = create_app()
