import asyncio, logging, time, uuid
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from backend.app.config import settings
from backend.app.models import ExtractRequest, Session, TABLES
from backend.app.utils import normalize_url, validate_public_host, URLSafetyError
from backend.app.extractors.salla import extract_live, ExtractionFailure
from backend.app.mock.data import mock_catalog
from backend.app.validators.catalog import validate_catalog
from backend.app.exporters.files import xlsx_bytes, zip_bytes
from backend.app.services.session_store import SessionStore

logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(name)s %(message)s")
app=FastAPI(title="Salla Store Extractor",version="1.4.0")
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173","http://127.0.0.1:5173"],allow_methods=["*"],allow_headers=["*"])
session_store=SessionStore(settings.session_db_path)
recovered_sessions=session_store.recover_interrupted()
if recovered_sessions:
    logging.warning("Marked %s interrupted extraction session(s) as ERROR",recovered_sessions)

@app.exception_handler(HTTPException)
async def http_error_handler(_:Request,exc:HTTPException):
    detail=exc.detail if isinstance(exc.detail,dict) else {"code":"HTTP_ERROR","message":str(exc.detail)}
    return JSONResponse(status_code=exc.status_code,content={"detail":detail})

@app.exception_handler(Exception)
async def global_error_handler(_:Request,exc:Exception):
    logging.exception("Unhandled API error",exc_info=exc)
    return JSONResponse(status_code=500,content={"detail":{"code":"INTERNAL_ERROR","message":"The request could not be completed"}})

def persist_session(session:Session,generate_exports:bool=False):
    session_store.save(session)
    if generate_exports:
        try:
            session_store.save_export(session.id,"xlsx",xlsx_bytes(session))
            session_store.save_export(session.id,"csv",zip_bytes(session))
        except Exception:
            logging.exception("Could not pre-generate exports for session %s",session.id)

def finalize(s,tables,raw,mode,start):
    for key in TABLES: tables.setdefault(key,[])
    issues=validate_catalog(tables)
    for failure in raw.get("extraction_failures",[]):
        from backend.app.models import Issue
        issues.append(Issue(Severity="ERROR",Entity_Type="PRODUCT",Entity_ID=None,Field="Source",Issue=failure.get("message","Product extraction failed"),Original_Value=failure.get("url")))
    if raw.get("safety_truncated"):
        from backend.app.models import Issue
        issues.append(Issue(Severity="INFO",Entity_Type="CATALOG",Entity_ID=None,Field="Pagination",Issue="Quick Extract intentionally limits the preview; use Full Extract for the complete public catalog",Original_Value=settings.quick_products))
    if raw.get("timed_out"):
        from backend.app.models import Issue
        issues.append(Issue(Severity="WARNING",Entity_Type="CATALOG",Entity_ID=None,Field="Timeout",Issue="Extraction time limit reached; completed records were preserved",Original_Value=raw.get("timeout_seconds")))
    tables["validation_issues"]=[x.model_dump() for x in issues]
    s.tables=tables;s.raw_data=raw;s.issues=issues;s.mode=mode
    errors=sum(x.Severity=="ERROR" for x in issues); warnings=sum(x.Severity=="WARNING" for x in issues)
    s.stats={"categories":len(tables["categories"]),"products":len(tables["products"]),"variants":len(tables["variants"]),"images":len(tables["images"]),"valid_records":max(0,sum(len(v) for k,v in tables.items() if k!="validation_issues")-errors),"warnings":warnings,"errors":errors,"pages_fetched":raw.get("pages_fetched",1),"duration_seconds":round(time.monotonic()-start,3),"timestamp":datetime.now(timezone.utc).isoformat(),"extractor_version":"1.4.0","extraction_mode":s.extraction_mode}
    s.progress_current=raw.get("products_selected",len(tables["products"]));s.progress_total=raw.get("products_selected",len(tables["products"]));s.progress_percentage=100
    if mode=="MOCK":s.stage="DEMO_MODE";s.message="External store access is unavailable in this Preview environment. These records are MOCK DATA and were not extracted from the submitted store."
    elif raw.get("timed_out"):s.stage="COMPLETED";s.message="Time limit reached. Completed products were preserved and are ready for review/export."
    elif errors or raw.get("extraction_failures"):s.stage="PARTIAL_SUCCESS";s.message="Extraction completed with validation errors. Review Validation Issues before export."
    else:s.stage="READY";s.message="Live extraction and validation completed."
    persist_session(s,generate_exports=True)

@app.get("/api/health")
async def health():
    try:
        import scrapling  # noqa: F401
        scrapling_available=True
    except ImportError:
        scrapling_available=False
    return {"backend_status":"ok","extractor_version":"1.4.0","external_network_available":"unknown_until_extraction","browser_available":settings.enable_browser_fallback,"scrapling_available":scrapling_available,"quick_products":settings.quick_products,"quick_timeout_seconds":settings.extraction_timeout_seconds,"full_timeout_seconds":settings.full_extraction_timeout_seconds,"session_storage":"SQLITE"}

async def run_extraction(sid:str,store_url:str,extraction_mode:str):
    s=session_store.get(sid)
    if not s:
        logging.error("Extraction session %s disappeared before processing",sid);return
    start=time.monotonic()
    try:
        url=normalize_url(store_url);validate_public_host(url);s.stage="DISCOVERING";s.message="Discovering public Salla data";persist_session(s)
        s.stage="FETCHING";s.message="Fetching public storefront";persist_session(s)
        async def update_progress(current,total):
            s.progress_current=current;s.progress_total=total;s.progress_percentage=round((current/total)*100,1) if total else 0;s.message=f"Fetching products: {current} / {total}";persist_session(s)
        tables,raw=await extract_live(url,extraction_mode,update_progress);s.stage="STRUCTURING";s.message="Normalizing relational tables";persist_session(s)
        s.stage="VALIDATING_DATA";s.message="Validating relationships and records";persist_session(s);finalize(s,tables,raw,"LIVE",start)
    except URLSafetyError as exc:
        s.stage="ERROR";s.message=str(exc);persist_session(s)
    except ExtractionFailure as exc:
        if exc.environmental and settings.enable_demo_fallback:
            tables=mock_catalog();finalize(s,tables,{"source":"bundled_mock","live_failure_code":exc.code,"pages_fetched":0},"MOCK",start)
        else:
            s.stage="ERROR";s.message=f"{exc.code}: {exc}";persist_session(s)
    except Exception:
        logging.exception("Unhandled extraction failure");s.stage="ERROR";s.message="The storefront response could not be processed";persist_session(s)

@app.post("/api/extract",status_code=202)
async def extract(req:ExtractRequest):
    # Validate synchronously so malformed/unsafe URLs still receive an immediate 4xx.
    try:
        url=normalize_url(req.store_url);validate_public_host(url)
    except URLSafetyError as exc:
        raise HTTPException(400,{"code":"INVALID_URL","message":str(exc)})
    sid=str(uuid.uuid4());s=Session(id=sid,stage="VALIDATING_URL",extraction_mode=req.extraction_mode,message="Validating public URL");persist_session(s)
    asyncio.create_task(run_extraction(sid,url,req.extraction_mode))
    return {"id":sid,"stage":s.stage,"mode":s.mode,"message":s.message,"stats":s.stats}

def get_session(sid):
    s=session_store.get(sid)
    if not s:raise HTTPException(404,"Extraction session not found")
    return s
@app.get("/api/extraction/{sid}")
async def status(sid:str):
    s=get_session(sid);return s.model_dump(exclude={"tables","raw_data","issues"})
@app.get("/api/extraction/{sid}/tables")
async def tables(sid:str):
    s=get_session(sid);return {"tables":s.tables,"raw_data":s.raw_data,"mode":s.mode,"stats":s.stats}
@app.get("/api/extraction/{sid}/export/xlsx")
async def export_xlsx(sid:str):
    s=get_session(sid)
    if s.stage not in {"READY","COMPLETED","PARTIAL_SUCCESS","DEMO_MODE"}:raise HTTPException(409,"Export is unavailable until validation completes")
    payload=session_store.get_export(sid,"xlsx") or xlsx_bytes(s)
    session_store.save_export(sid,"xlsx",payload)
    stamp=datetime.now().strftime("%Y-%m-%d_%H-%M");return Response(payload,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":f'attachment; filename="salla_store_export_{stamp}.xlsx"'})
@app.get("/api/extraction/{sid}/export/csv")
async def export_csv(sid:str):
    s=get_session(sid)
    if s.stage not in {"READY","COMPLETED","PARTIAL_SUCCESS","DEMO_MODE"}:raise HTTPException(409,"Export is unavailable until validation completes")
    payload=session_store.get_export(sid,"csv") or zip_bytes(s)
    session_store.save_export(sid,"csv",payload)
    stamp=datetime.now().strftime("%Y-%m-%d_%H-%M");return Response(payload,media_type="application/zip",headers={"Content-Disposition":f'attachment; filename="salla_store_export_{stamp}.zip"'})

# In production FastAPI serves the compiled React app from the same origin.
dist_dir=Path(__file__).resolve().parents[2]/"dist"
if dist_dir.exists():
    app.mount("/",StaticFiles(directory=dist_dir,html=True),name="frontend")
