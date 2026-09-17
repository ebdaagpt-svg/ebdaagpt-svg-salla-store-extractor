# Salla Store Data Extractor

A runnable React + TypeScript and FastAPI application that attempts conservative extraction of publicly accessible Salla storefront data. The user can choose `Products only` or `Website data` (public identity, contact, location, logo, and social links), then inspect and export normalized Excel or zipped CSV files.

## Architecture

- `src/`: Vite/React inspection UI with status, sortable/searchable tables, and export controls.
- `backend/app/extractors/`: layered public storefront request and JSON-LD parsing.
- `backend/app/validators/`: completeness, price, duplicate, and relationship checks.
- `backend/app/exporters/`: multi-sheet XLSX and UTF-8-BOM CSV ZIP generation.
- `backend/app/mock/`: fixed realistic Arabic demo catalog, never represented as live data.
- `tests/`: SSRF, normalization, validation, and export tests.

## Run in Codex Preview / development

```bash
python -m pip install -r requirements.txt
npm install
python -m backend.app
npm run dev
```

Open `http://localhost:5173`. The Vite server proxies `/api` to FastAPI on port 8000. Health check: `http://localhost:8000/api/health`.

## Extraction pipeline

The backend validates and resolves the supplied HTTP(S) URL, blocks non-public address ranges, validates every redirect, and requests the storefront through Scrapling's static browser-impersonating fetcher with an `httpx` fallback. It recursively discovers bounded public Sitemaps, identifies stable Salla `/p<ID>` and `/c<ID>` URLs, fetches products with bounded concurrency and pacing, prefers JSON-LD, falls back to public OpenGraph metadata, then normalizes and validates relational records. The implementation does not guess unavailable fields or claim inaccessible records.

`LIVE` means records were read from the submitted public storefront. `MOCK` is activated only when external access fails for an environmental/network reason and `ENABLE_DEMO_FALLBACK=true`. Detection or unsupported-structure errors remain errors rather than silently loading demo records.

## Export structure

Excel contains README plus Store, Website Data, Categories, Products, Product Categories, Images, Options, Option Values, Variants, Variant Option Values, Tags, Product Tags, SEO, and Validation Issues sheets. CSV export is a ZIP with one UTF-8-BOM CSV per table and `README.txt`. Mock exports carry explicit MOCK metadata and warnings.

## Configuration

Copy `.env.example` to `.env` to override safe defaults. No secrets are required. Browser automation is disabled and is not needed to start the application.

Quick Extract is the default and processes the first 30 public product pages within 45 seconds. Full Extract has no product-count cap, walks up to 100 sitemap documents/five nested levels, processes URLs in batches of 40, and runs as a persisted background session with live percentage progress. Each completed batch is checkpointed to SQLite and released from working memory. A 30-minute safety deadline prevents abandoned full jobs from running indefinitely; completed records remain exportable in terminal `COMPLETED` state. Unexpected failures after a checkpoint end as `COMPLETED_WITH_ERRORS` instead of breaking status polling.

The independent `Website data` type fetches one submitted public page and extracts only public store metadata from JSON-LD, Salla's public page state, links, and footer HTML: store/legal name, public store ID and username, description, logo, every exposed phone/email, WhatsApp, postal address, city/region/country, coordinates, map link, opening hours, public VAT/commercial registration/certificate identifiers, currency, mobile-app links, and recognized social-media links. Missing values remain absent and are never invented.

`Products only` supports selectable limits of 30, 50, 100, 250, or all public products. In addition to the normalized relational sheets, `Products_Flat`/`products_flat.csv` provides one row per product with joined category IDs/names/URLs, main image, all image URLs, variant counts/SKUs, option names, and tag names for simpler imports.

Extraction sessions and pre-generated XLSX/CSV ZIP artifacts are stored in SQLite (`SESSION_DB_PATH`). Use a persistent Railway volume mounted at `/data` with `SESSION_DB_PATH=/data/extractions.sqlite3` to preserve sessions across deployments as well as process restarts.

## Tests

```bash
pytest -q
npm run build
```

## Known limitations

- Public storefront structure varies by Salla theme and can change. Products absent from public Sitemaps/JSON-LD/OpenGraph may be reported as partial or unsupported rather than fabricated.
- Private admin data, costs, inventory details, and records requiring authentication cannot be extracted without an officially authorized API integration.
- SQLite sessions persist across process restarts. Persistence across Railway deployments requires the configured `/data` volume.

## Scrapling integration

The API uses Scrapling's static HTTP fetcher first with bounded retries, then falls back to `httpx`. It reads public JSON-LD and serialized page state, but does not bypass authentication, CAPTCHAs, Cloudflare challenges, or access controls. Redirects are handled manually and every redirect target passes the existing SSRF checks. Browser rendering remains disabled by default.

HTTP 429 responses are retried up to three times with bounded exponential backoff (3, 4.5, then 5 seconds) while honoring a larger numeric `Retry-After` value. Requests use randomized 0.3–0.8 second pacing and a stable, transparent extractor User-Agent; identity/header rotation is intentionally not used.

Request starts are globally paced within each extraction session, including concurrent product workers. Scrapling's automatic stealth headers are disabled so the configured transparent extractor identity is preserved. A persistent 429 is respected and ends with a clear retry-later message; the pipeline never changes identity or client to evade a storefront rate limit.

Submitted product and category URLs are scope-isolated. A product URL extracts only that product. A category/filter URL is fetched exactly (path and query included) and only links inside the listing's product-card DOM are eligible. Generic embedded JSON is deliberately ignored for category discovery because it may contain recommendations or store-wide analytics. Pagination must keep the exact host/path and every original non-pagination query filter. Category jobs never fall back to the store-wide sitemap; client-rendered listings that expose no public product cards return `UNSUPPORTED_STRUCTURE` instead of unrelated catalog rows. Every click creates a new UUID session with fresh request clients, result dictionaries, checkpoints and exports; no catalog result cache is shared between extraction sessions.

To deploy the official Scrapling MCP server, create a second Railway service from this repository, select `Dockerfile.mcp` (or use `railway-mcp.json`), and set a long random `SCRAPLING_MCP_AUTH_TOKEN`. Give that service its own public domain. The Streamable HTTP endpoint is:

`https://<mcp-service-domain>/mcp`

Connect it to an MCP-compatible client with `Authorization: Bearer <SCRAPLING_MCP_AUTH_TOKEN>`. Never deploy this service without authentication. The MCP service is deliberately separate from the catalog API so browser/session workloads cannot block the user-facing extractor.
- Playwright fallback is intentionally not installed; it can be added as an optional strategy without making startup depend on it.
