# Salla Store Data Extractor

A runnable React + TypeScript and FastAPI application that attempts conservative extraction of publicly accessible Salla storefront catalog data, normalizes records into relational migration tables, validates integrity, and exports Excel or zipped CSV files.

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

Excel contains README plus Store, Categories, Products, Product Categories, Images, Options, Option Values, Variants, Variant Option Values, Tags, Product Tags, SEO, and Validation Issues sheets. CSV export is a ZIP with one UTF-8-BOM CSV per table and `README.txt`. Mock exports carry explicit MOCK metadata and warnings.

## Configuration

Copy `.env.example` to `.env` to override safe defaults. No secrets are required. Browser automation is disabled and is not needed to start the application.

## Tests

```bash
pytest -q
npm run build
```

## Known limitations

- Public storefront structure varies by Salla theme and can change. Products absent from public Sitemaps/JSON-LD/OpenGraph may be reported as partial or unsupported rather than fabricated.
- Private admin data, costs, inventory details, and records requiring authentication cannot be extracted without an officially authorized API integration.
- In-memory extraction sessions are lost on backend restart.

## Scrapling integration

The API uses Scrapling's static HTTP fetcher first (browser fingerprinting, bounded retries), then falls back to `httpx`. Redirects are handled manually and every redirect target passes the existing SSRF checks. Browser rendering remains disabled by default.

To deploy the official Scrapling MCP server, create a second Railway service from this repository, select `Dockerfile.mcp` (or use `railway-mcp.json`), and set a long random `SCRAPLING_MCP_AUTH_TOKEN`. Give that service its own public domain. The Streamable HTTP endpoint is:

`https://<mcp-service-domain>/mcp`

Connect it to an MCP-compatible client with `Authorization: Bearer <SCRAPLING_MCP_AUTH_TOKEN>`. Never deploy this service without authentication. The MCP service is deliberately separate from the catalog API so browser/session workloads cannot block the user-facing extractor.
- Playwright fallback is intentionally not installed; it can be added as an optional strategy without making startup depend on it.
