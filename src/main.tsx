import React, { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Database,
  Download,
  RefreshCw,
  Search,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import "./styles.css";

type Result = {
  id: string;
  stage: string;
  mode: "LIVE" | "MOCK";
  message: string;
  stats: Record<string, number | string>;
  progress_current?: number;
  progress_total?: number;
  progress_percentage?: number;
};
type Payload = {
  tables: Record<string, Record<string, unknown>[]>;
  raw_data: unknown;
  mode: string;
  stats: Record<string, number | string>;
};
const tabs = [
  ["overview", "Overview"],
  ["website_data", "Website Data"],
  ["categories", "Categories"],
  ["products", "Products"],
  ["product_categories", "Product Categories"],
  ["images", "Images"],
  ["product_options", "Options"],
  ["option_values", "Option Values"],
  ["variants", "Variants"],
  ["variant_option_values", "Variant Options"],
  ["tags", "Tags"],
  ["product_tags", "Product Tags"],
  ["seo", "SEO"],
  ["validation_issues", "Validation Issues"],
  ["raw", "Raw Data"],
];
function DataTable({ rows }: { rows: Record<string, unknown>[] }) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("");
  const [asc, setAsc] = useState(true);
  const cols = useMemo(
    () => Array.from(new Set(rows.flatMap(Object.keys))),
    [rows],
  );
  const filtered = useMemo(() => {
    let x = rows.filter((r) =>
      JSON.stringify(r).toLowerCase().includes(query.toLowerCase()),
    );
    if (sort)
      x = [...x].sort(
        (a, b) =>
          String(a[sort] ?? "").localeCompare(
            String(b[sort] ?? ""),
            undefined,
            { numeric: true },
          ) * (asc ? 1 : -1),
      );
    return x;
  }, [rows, query, sort, asc]);
  return (
    <>
      <div className="tablebar">
        <label>
          <Search size={16} />
          <input
            placeholder="Search this table"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <span>{filtered.length.toLocaleString()} rows</span>
      </div>
      <div className="scroll">
        <table>
          <thead>
            <tr>
              {cols.map((c) => (
                <th
                  key={c}
                  onClick={() => {
                    if (sort === c) setAsc(!asc);
                    else {
                      setSort(c);
                      setAsc(true);
                    }
                  }}
                >
                  {c}
                  {sort === c ? (asc ? " ↑" : " ↓") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((r, i) => (
              <tr key={i}>
                {cols.map((c) => (
                  <td key={c}>
                    {r[c] === null || r[c] === undefined ? (
                      <span className="null">null</span>
                    ) : typeof r[c] === "boolean" ? (
                      String(r[c])
                    ) : (
                      String(r[c])
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && (
          <div className="empty">
            No records were publicly available for this table.
          </div>
        )}
      </div>
    </>
  );
}
function App() {
  const [url, setUrl] = useState("https://example.salla.sa/");
  const [result, setResult] = useState<Result | null>(null);
  const [data, setData] = useState<Payload | null>(null);
  const [tab, setTab] = useState("overview");
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState("IDLE");
  const [error, setError] = useState("");
  const [dataType, setDataType] = useState<"PRODUCTS" | "WEBSITE">("PRODUCTS");
  const [extractionMode, setExtractionMode] = useState<"QUICK" | "FULL">(
    "QUICK",
  );
  async function run() {
    setBusy(true);
    setError("");
    setData(null);
    setResult(null);
    setStage("VALIDATING_URL");
    try {
      const r = await fetch("/api/extract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          store_url: url,
          data_type: dataType,
          extraction_mode: extractionMode,
        }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail?.message || "Extraction failed");
      setResult(body);
      let current = body;
      while (
        ![
          "READY",
          "COMPLETED",
          "COMPLETED_WITH_ERRORS",
          "PARTIAL_SUCCESS",
          "DEMO_MODE",
          "ERROR",
        ].includes(current.stage)
      ) {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        const statusResponse = await fetch(`/api/extraction/${body.id}`);
        if (!statusResponse.ok)
          throw new Error("Could not read extraction status");
        current = await statusResponse.json();
        setResult(current);
        setStage(current.stage);
      }
      if (current.stage === "ERROR")
        throw new Error(current.message || "Extraction failed");
      const t = await fetch(`/api/extraction/${body.id}/tables`);
      if (!t.ok) throw new Error("Could not load extracted tables");
      setData(await t.json());
    } catch (e) {
      setStage("ERROR");
      setError(e instanceof Error ? e.message : "Extraction failed");
    } finally {
      setBusy(false);
    }
  }
  function reset() {
    setResult(null);
    setData(null);
    setStage("IDLE");
    setError("");
    setTab("overview");
  }
  const ready =
    !!result &&
    ["READY", "COMPLETED", "PARTIAL_SUCCESS", "DEMO_MODE"].includes(
      result.stage,
    );
  const rows =
    tab === "raw"
      ? data
        ? [{ JSON: JSON.stringify(data.raw_data, null, 2) }]
        : []
      : data?.tables[tab] || [];
  return (
    <main>
      <header>
        <div className="brand">
          <Database size={22} />
          <div>
            <strong>Salla Data Extractor</strong>
            <small>Migration preparation · v1.7.0</small>
          </div>
        </div>
        <div className="health">
          <i /> FastAPI connected
        </div>
      </header>
      <section className="control">
        <div className="intro">
          <h1>Public store data extraction</h1>
          <p>
            Extract either public website identity/contact data or public
            product catalog records.
          </p>
        </div>
        <div className="form">
          <label>
            Store URL
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://store.example.com"
              disabled={busy}
            />
          </label>
          <label className="mode-field">
            Data type
            <select
              value={dataType}
              onChange={(e) =>
                setDataType(e.target.value as "PRODUCTS" | "WEBSITE")
              }
              disabled={busy}
            >
              <option value="PRODUCTS">Products only</option>
              <option value="WEBSITE">
                Website data · name, location, social media
              </option>
            </select>
          </label>
          <label className="mode-field">
            Extraction mode
            <select
              value={extractionMode}
              onChange={(e) =>
                setExtractionMode(e.target.value as "QUICK" | "FULL")
              }
              disabled={busy || dataType === "WEBSITE"}
            >
              <option value="QUICK">Quick Extract · first 30 products</option>
              <option value="FULL">
                Full Extract · complete public catalog
              </option>
            </select>
          </label>
          <button className="primary" onClick={run} disabled={busy || !url}>
            {busy ? (
              <RefreshCw className="spin" size={17} />
            ) : (
              <Database size={17} />
            )}{" "}
            Extract Data
          </button>
          <button className="secondary" onClick={reset} disabled={busy}>
            Reset
          </button>
        </div>
        <div className={`status ${stage.toLowerCase()}`}>
          <div>
            <span className="stage">{stage.replaceAll("_", " ")}</span>
            <b>
              {result?.mode === "LIVE"
                ? "LIVE DATA"
                : result?.mode === "MOCK"
                  ? "DEMO MODE"
                  : "Pipeline status"}
            </b>
            <p>
              {error ||
                result?.message ||
                "Waiting for a public Salla storefront URL."}
            </p>
          </div>
          {result?.mode === "LIVE" ? (
            <ShieldCheck />
          ) : result?.mode === "MOCK" || error ? (
            <TriangleAlert />
          ) : null}
        </div>
        {busy && (
          <div className="progress">
            <i
              style={{
                width: `${result?.progress_percentage || 2}%`,
                animation: result?.progress_total ? "none" : undefined,
              }}
            />
            <span>
              {result?.progress_total
                ? `${result.progress_current} / ${result.progress_total} · ${result.progress_percentage}%`
                : "Discovering catalog…"}
            </span>
          </div>
        )}
      </section>
      {data && (
        <>
          <section className="summary">
            <div>
              <small>Data mode</small>
              <b className={data.mode === "MOCK" ? "amber" : "green"}>
                {data.mode}
              </b>
            </div>
            {[
              "website_fields",
              "products",
              "categories",
              "variants",
              "images",
              "warnings",
              "errors",
            ].map((k) => (
              <div key={k}>
                <small>{k}</small>
                <b>{Number(data.stats[k] || 0).toLocaleString()}</b>
              </div>
            ))}
            <div>
              <small>Duration</small>
              <b>{data.stats.duration_seconds}s</b>
            </div>
          </section>
          <nav>
            {tabs.map(([k, l]) => (
              <button
                className={tab === k ? "active" : ""}
                onClick={() => setTab(k)}
                key={k}
              >
                {l}
                {k !== "overview" && k !== "raw" && (
                  <em>{data.tables[k]?.length || 0}</em>
                )}
              </button>
            ))}
          </nav>
          <section className="workspace">
            {tab === "overview" ? (
              <div className="overview">
                <h2>Extraction summary</h2>
                <dl>
                  {Object.entries(data.stats).map(([k, v]) => (
                    <div key={k}>
                      <dt>{k.replaceAll("_", " ")}</dt>
                      <dd>{String(v)}</dd>
                    </div>
                  ))}
                </dl>
                <div className="notice">
                  <ShieldCheck />
                  <p>
                    <b>Source traceability</b>
                    <br />
                    Mode: {data.mode}.{" "}
                    {data.mode === "MOCK"
                      ? "This catalog is bundled test data and was not extracted from the submitted URL."
                      : "Records came from the public storefront only."}
                  </p>
                </div>
              </div>
            ) : (
              <DataTable rows={rows} />
            )}
          </section>
          <footer>
            <span>
              {result?.stage === "PARTIAL_SUCCESS"
                ? "Some records could not be fully extracted. Review Validation Issues before importing."
                : "Exports include normalized relational tables and validation results."}
            </span>
            <a
              className={!ready ? "disabled" : ""}
              href={
                ready ? `/api/extraction/${result?.id}/export/xlsx` : undefined
              }
            >
              <Download size={16} /> Export Excel
            </a>
            <a
              className={!ready ? "disabled" : ""}
              href={
                ready ? `/api/extraction/${result?.id}/export/csv` : undefined
              }
            >
              <Download size={16} /> Export CSV ZIP
            </a>
          </footer>
        </>
      )}
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
