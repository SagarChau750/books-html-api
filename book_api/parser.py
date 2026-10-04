"""Explicit selectors: missing required fields fail visibly, never silently guess."""
import re
from decimal import Decimal

from bs4 import BeautifulSoup

from .source import BASE, SourceError, safe_url

RATINGS = {name: i for i, name in enumerate(("One", "Two", "Three", "Four", "Five"), 1)}


def required(node, selector):
    value = node.select_one(selector)
    if value is None:
        raise SourceError("source_changed", f"Required HTML selector missing: {selector}")
    return value


def money(text):
    match = re.fullmatch(r"£([0-9]+\.[0-9]{2})", text.strip())
    if not match:
        raise SourceError("source_changed", "Unexpected price format or currency")
    return str(Decimal(match.group(1)))


def rating(node):
    classes = required(node, ".star-rating").get("class", [])
    values = [RATINGS[x] for x in classes if x in RATINGS]
    if len(values) != 1:
        raise SourceError("source_changed", "Unexpected rating encoding")
    return values[0]


def provenance(page):
    return {"source_url": page.url, "fetched_at": page.fetched_at, "cached": page.cached}


def catalogue(page):
    soup = BeautifulSoup(page.html, "html.parser")
    articles = soup.select("article.product_pod")
    if not articles:
        raise SourceError("source_changed", "No product cards found in catalogue HTML")
    items = []
    for card in articles:
        link = required(card, "h3 a")
        title, href = link.get("title"), link.get("href")
        if not title or not href:
            raise SourceError("source_changed", "Product title or link is missing")
        url = safe_url(href, page.url)
        items.append({"id": url.split("/")[-2], "title": title,
            "price": money(required(card, ".price_color").get_text(strip=True)),
            "currency": "GBP", "rating": rating(card),
            "availability": required(card, ".availability").get_text(" ", strip=True),
            "source_url": url})
    pager = soup.select_one(".pager .current")
    if pager:
        match = re.fullmatch(r"Page\s+(\d+)\s+of\s+(\d+)", pager.get_text(" ", strip=True))
        if not match:
            raise SourceError("source_changed", "Unexpected pagination markup")
        current, total = map(int, match.groups())
    else:
        current = total = 1
    if not 1 <= current <= total:
        raise SourceError("source_changed", "Inconsistent pagination")
    next_link = soup.select_one(".pager .next a")
    if bool(next_link) != (current < total):
        raise SourceError("source_changed", "Missing or inconsistent next-page link")
    if next_link:
        safe_url(next_link.get("href", ""), page.url)
    return {"items": items, "page": current, "total_pages": total,
            "next_page": current + 1 if current < total else None, **provenance(page)}


def categories(page):
    soup = BeautifulSoup(page.html, "html.parser")
    links = soup.select(".side_categories ul li ul li a")
    if not links:
        raise SourceError("source_changed", "Category navigation missing")
    result = []
    for link in links:
        url = safe_url(link.get("href", ""), page.url)
        if "/category/books/" not in url:
            raise SourceError("source_changed", "Unexpected category URL")
        result.append({"id": url.split("/")[-2], "name": link.get_text(strip=True), "source_url": url})
    return {"items": result, **provenance(page)}


def detail(page):
    soup = BeautifulSoup(page.html, "html.parser")
    main = required(soup, ".product_main")
    fields = {}
    for row in soup.select("table.table-striped tr"):
        fields[required(row, "th").get_text(strip=True)] = required(row, "td").get_text(strip=True)
    if not all(key in fields for key in ("UPC", "Availability", "Number of reviews")):
        raise SourceError("source_changed", "Product metadata missing")
    available = re.fullmatch(r"In stock \((\d+) available\)", fields["Availability"])
    if available:
        stock = int(available.group(1))
    elif fields["Availability"] == "Out of stock":
        stock = 0
    else:
        raise SourceError("source_changed", "Unexpected stock format")
    if not fields["Number of reviews"].isdigit():
        raise SourceError("source_changed", "Invalid review count")
    crumbs = soup.select(".breadcrumb li a")
    if len(crumbs) < 3:
        raise SourceError("source_changed", "Category breadcrumb missing")
    return {"id": page.url.split("/")[-2],
        "title": required(main, "h1").get_text(strip=True),
        "price": money(required(main, ".price_color").get_text(strip=True)),
        "currency": "GBP", "rating": rating(main), "upc": fields["UPC"],
        "category": crumbs[-1].get_text(strip=True), "stock_quantity": stock,
        "availability": fields["Availability"], "review_count": int(fields["Number of reviews"]),
        **provenance(page)}
