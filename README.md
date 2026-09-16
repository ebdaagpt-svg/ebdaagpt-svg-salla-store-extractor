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

The backend validates and resolves the supplied HTTP(S) URL, blocks non-public address ranges, validates every redirect, requests the storefront with bounded retries and timeouts, detects Salla signals, prefers JSON-LD structured product data, normalizes records, then validates all relationships. The implementation is deliberately conservative: it does not guess fields or claim inaccessible records.

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

- Public storefront structure varies by Salla theme and can change. The current live extractor handles public JSON-LD product records conservatively; stores that expose catalogs only through theme-specific client endpoints may return `UNSUPPORTED_STRUCTURE` rather than fabricated or incomplete data.
- Private admin data, costs, inventory details, and records requiring authentication cannot be extracted without an officially authorized API integration.
- In-memory extraction sessions are lost on backend restart.
- Playwright fallback is intentionally not installed; it can be added as an optional strategy without making startup depend on it.
