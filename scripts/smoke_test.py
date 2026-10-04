"""Working end-to-end test script. Start `python index.py` first."""
import argparse
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=120, trust_env=False) as client:
        def get(path, status=200, **params):
            response = client.get(path, params=params)
            assert response.status_code == status, f"{path}: {response.status_code} {response.text[:300]}"
            print(f"PASS {status} {path}")
            return response.json()
        get("/health")
        listing = get("/api/v1/books")
        assert listing["items"] and listing["page"] == 1
        book = listing["items"][0]
        detail = get("/api/v1/books/" + book["id"])
        assert detail["title"] == book["title"] and detail["price"] == book["price"]
        assert isinstance(detail["stock_quantity"], int)
        categories = get("/api/v1/categories")
        category = get("/api/v1/books", category=categories["items"][0]["id"])
        assert category["items"]
        get("/api/v1/books", page=2)
        matches = get("/api/v1/search", q=book["title"], max_pages=1)
        assert any(item["id"] == book["id"] for item in matches["items"])
        assert not matches["complete_catalogue"]
        assert get("/api/v1/search", q="zzzz-no-such-title-998877", max_pages=1)["items"] == []
        get("/api/v1/books", 422, page=0)
        get("/api/v1/books/nonexistent-book_999999", 404)
        get("/api/v1/books", 422, category="https://example.com")
        print("All live smoke checks passed. Source: https://books.toscrape.com/")


if __name__ == "__main__":
    main()
