import io, time, zipfile
from tempfile import TemporaryDirectory
import pytest
from openpyxl import load_workbook
from backend.app.utils import normalize_url, validate_public_host, number_or_none, bool_or_none, html_to_text, URLSafetyError
from backend.app.mock.data import mock_catalog
from backend.app.models import Session
from backend.app.validators.catalog import validate_catalog
from backend.app.exporters.files import xlsx_bytes, zip_bytes
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.extractors.salla import ExtractionFailure, parse_sitemap, source_id_from_url, product_from_page, json_objects
from backend.app.services.session_store import SessionStore
from bs4 import BeautifulSoup

def session():
    tables=mock_catalog();issues=validate_catalog(tables);tables["validation_issues"]=[x.model_dump() for x in issues]
    return Session(id="test",stage="DEMO_MODE",mode="MOCK",message="test",tables=tables,issues=issues)
def test_url_validation(): assert normalize_url("https://shop.example.com")=="https://shop.example.com/"
def test_complex_salla_filter_url():
    value=normalize_url("https://shop.example.com/products?filters[category_id]=12&filters[available]=1")
    assert "filters%5Bcategory_id%5D=12" in value and "filters%5Bavailable%5D=1" in value
@pytest.mark.parametrize("url",["file:///etc/passwd","ftp://example.com","http://localhost:8000"])
def test_bad_urls(url):
    with pytest.raises(URLSafetyError): normalize_url(url)
def test_ssrf_ip():
    with pytest.raises(URLSafetyError): validate_public_host("http://127.0.0.1/")
def test_normalizers():
    assert number_or_none("SAR 12.50")==12.5 and number_or_none("") is None
    assert bool_or_none("متوفر") is True and bool_or_none("unknown") is None
    assert html_to_text("<p>مرحبا <b>بك</b></p>")=="مرحبا بك"
def test_sitemap_parsing_and_product_ids():
    xml='''<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://shop.example/sitemap-1.xml</loc></sitemap></sitemapindex>'''
    nested,rows=parse_sitemap(xml); assert nested==["https://shop.example/sitemap-1.xml"] and rows==[]
    xml='''<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"><url><loc>https://shop.example/item/p123</loc><lastmod>2026-01-01</lastmod><image:image><image:loc>https://cdn.example/a.jpg</image:loc></image:image></url></urlset>'''
    nested,rows=parse_sitemap(xml); assert not nested and rows[0]["images"]==["https://cdn.example/a.jpg"]
    assert source_id_from_url(rows[0]["url"])=="123"
def test_jsonld_product_prices_and_public_fields():
    html='''<html><head><script type="application/ld+json">{"@type":"Product","productID":"123","name":"عبوة اختبار","description":"<p>وصف</p>","weight":{"value":500,"unitText":"ml"},"notes":"يحفظ مبرداً","offers":{"price":80,"highPrice":100,"priceCurrency":"SAR","availability":"https://schema.org/InStock","shippingDetails":{"shippingLabel":"جاهز للشحن"}}}</script></head></html>'''
    soup=BeautifulSoup(html,"lxml")
    product,*_=product_from_page(json_objects(soup),soup,"https://shop.example/item/p123")
    assert product["Price"]==100 and product["Sale_Price"]==80
    assert product["Size_Volume"]=="500.0 ml" and product["Shipping_Status"]=="جاهز للشحن"
def test_relationships_and_demo_warnings():
    issues=validate_catalog(mock_catalog()); assert any(x.Field=="SKU" for x in issues) and any(x.Field=="Images" for x in issues)
def test_excel_generation():
    wb=load_workbook(io.BytesIO(xlsx_bytes(session()))); assert {"README","Products","Validation_Issues"}.issubset(wb.sheetnames); assert wb["Store"]["G2"].value=="MOCK"
def test_csv_generation():
    z=zipfile.ZipFile(io.BytesIO(zip_bytes(session()))); assert "products.csv" in z.namelist(); assert "MOCK DATA" in z.read("README.txt").decode("utf-8-sig")

def test_sqlite_session_and_export_persistence():
    with TemporaryDirectory() as directory:
        path=f"{directory}/sessions.sqlite3"
        first=SessionStore(path); current=session(); first.save(current); first.save_export(current.id,"csv",b"PK-test")
        restarted=SessionStore(path)
        assert restarted.get(current.id).stage=="DEMO_MODE"
        assert restarted.get_export(current.id,"csv")==b"PK-test"

def test_demo_mode_end_to_end(monkeypatch):
    import backend.app.main as main
    async def network_blocked(url): raise ExtractionFailure("PREVIEW_NETWORK_RESTRICTED","blocked",True)
    monkeypatch.setattr(main,"validate_public_host",lambda url:url)
    monkeypatch.setattr(main,"extract_live",network_blocked)
    client=TestClient(app)
    assert client.get("/api/health").status_code==200
    result=client.post("/api/extract",json={"store_url":"https://example.salla.sa/"})
    assert result.status_code==202
    sid=result.json()["id"]
    for _ in range(50):
        status=client.get(f"/api/extraction/{sid}").json()
        if status["stage"] in {"READY","COMPLETED","PARTIAL_SUCCESS","DEMO_MODE","ERROR"}: break
        time.sleep(.01)
    assert status["mode"]=="MOCK"
    tables=client.get(f"/api/extraction/{sid}/tables").json()["tables"]
    assert len(tables["products"])==20 and tables["store"][0]["Data_Mode"]=="MOCK"
    assert client.get(f"/api/extraction/{sid}/export/xlsx").content[:2]==b"PK"
    assert client.get(f"/api/extraction/{sid}/export/csv").content[:2]==b"PK"
