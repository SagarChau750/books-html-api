# Limitations and the long-term fix

## What was reverse-engineered

The public HTML structure, relative-link scheme, and pagination of Books to Scrape:

| Source representation | API interpretation |
|---|---|
| `article.product_pod h3 a[title]` | Full title; visible card text is truncated |
| Card link `href` | Canonical source URL and opaque book slug |
| `.price_color` containing a GBP price | Decimal price string and GBP currency |
| `.star-rating` class `One` through `Five` | Integer rating from 1 to 5 |
| `.pager .current`, `.pager .next a` | Page count and continuation |
| `.side_categories` nested navigation | Category IDs and labels |
| `.product_main`, product table, breadcrumb | Detail title, UPC, stock and category |

This is an HTML adapter, not discovery of a hidden authenticated service. It only
uses public GET requests. The source explicitly identifies itself as a scraping
sandbox. No public API was found in the inspected interface; proving that no API
exists anywhere is outside the scope of the assignment.

## Important limitations

1. **HTML is not a stable contract.** CSS, wording, URL or encoding changes can
   break the parser. Missing required fields produce a visible `source_changed`
   error rather than silently returning invented data. Some semantic changes with
   unchanged markup would still need manual review.
2. **Source data is fictional.** Prices and ratings are randomly assigned by the
   sandbox. This demonstrates engineering, not verified real-world book pricing.
3. **Search is bounded.** At most five pages per request; coverage and continuation
   are explicit. There is no semantic search, full catalogue index, sorting across
   unscanned pages, or guarantee of a snapshot across concurrent catalogue changes.
4. **Freshness is limited.** HTML is cached for five minutes. A product can change
   between listing and detail retrieval. No webhooks or change feed are available.
5. **Local demo scope.** No authentication, multi-tenant authorization, distributed
   cache, durable database, or inbound per-user rate limiting is provided. It binds
   to loopback by default. A public deployment needs those controls and monitoring.
6. **Source protection over throughput.** A single process serializes outbound
   fetches and bounds queued waiting. Multiple workers would multiply the budget.
   Retry delays are capped by stopping rather than retrying earlier than a long
   `Retry-After`. Network timeouts are per I/O operation, not a global request SLA.
7. **Narrow data surface.** The API exposes catalogue metadata, not full book
   descriptions, images, reviews, shopping carts, checkout or customer records.
   Robots.txt is checked; if policies or access requirements change, stop and
   review rather than bypassing them.

## Appropriate long-term fix

Work with the website owner to provide a supported, versioned API or authorised
catalogue feed backed by the source database. Agree on stable IDs, decimal/currency
types, pagination/search semantics, freshness guarantees, rate limits, and a
deprecation policy. Add ETags and a delta feed or webhooks for incremental updates.
This removes fragile HTML selectors and reduces duplicate crawling.

If an official API is not immediately feasible, seek explicit permission for a
scheduled ingestion job feeding a local index. Add persistent caching, a shared
request budget, source-change alerts, fixture-based contract tests and data-quality
checks. Serve user queries from that index, exposing last-sync time and coverage.
That is an interim arrangement, not a substitute for a supported data contract.
