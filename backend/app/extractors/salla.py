import asyncio, json, logging, re
from urllib.parse import urljoin
import httpx
from bs4 import BeautifulSoup
from backend.app.config import settings
from backend.app.utils import stable_id, html_to_text, number_or_none, text_or_none, validate_public_host, safe_redirect

log=logging.getLogger(__name__)
class ExtractionFailure(RuntimeError):
    def __init__(self,code,message,environmental=False): super().__init__(message); self.code=code; self.environmental=environmental

async def fetch(client,url):
    last=None
    for attempt in range(settings.max_retries+1):
        try:
            current=validate_public_host(url)
            for _ in range(4):
                response=await client.get(current,follow_redirects=False)
                if response.status_code in {301,302,303,307,308}:
                    current=safe_redirect(current,response.headers.get("location","")); continue
                if response.status_code==429: raise ExtractionFailure("RATE_LIMITED","The storefront rate-limited extraction")
                if response.status_code in {401,403}: raise ExtractionFailure("ACCESS_DENIED","The public storefront denied access")
                response.raise_for_status(); return response
            raise ExtractionFailure("ACCESS_DENIED","Too many redirects")
        except ExtractionFailure: raise
        except (httpx.TimeoutException,httpx.NetworkError,ValueError) as exc:
            last=exc
            if attempt<settings.max_retries: await asyncio.sleep(.35*(2**attempt))
    raise ExtractionFailure("PREVIEW_NETWORK_RESTRICTED",f"External store access failed: {type(last).__name__}",True)

def json_objects(soup):
    out=[]
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            value=json.loads(node.string or node.get_text())
            out.extend(value if isinstance(value,list) else [value])
        except Exception: continue
    return out

def product_from_json(obj,base,index):
    offers=obj.get("offers") or {}; offers=offers[0] if isinstance(offers,list) and offers else offers
    url=urljoin(base,obj.get("url") or ""); title=text_or_none(obj.get("name")); source_id=obj.get("productID") or obj.get("sku") or url or title
    if not title or not source_id:return None
    pid=str(source_id) if obj.get("productID") else stable_id("prd",source_id)
    desc=obj.get("description")
    p={"Product_ID":pid,"Title":title,"Slug":url.rstrip('/').split('/')[-1] or None,"SKU":text_or_none(obj.get("sku")),"Barcode":text_or_none(obj.get("gtin13") or obj.get("gtin")),"Product_Type":None,"Price":number_or_none(offers.get("price")),"Sale_Price":None,"Currency":text_or_none(offers.get("priceCurrency")),"Cost_Price":None,"Quantity":None,"Is_Available":"InStock" in str(offers.get("availability")) if offers.get("availability") else None,"Is_Active":True,"Brand":text_or_none((obj.get("brand") or {}).get("name") if isinstance(obj.get("brand"),dict) else obj.get("brand")),"Weight":None,"Weight_Unit":None,"Short_Description":None,"Description_HTML":desc,"Description_Text":html_to_text(desc),"Product_URL":url or None,"Created_At":None,"Updated_At":None}
    imgs=obj.get("image") or []; imgs=[imgs] if isinstance(imgs,str) else imgs
    return p,[{"Image_ID":stable_id("img",pid,x),"Product_ID":pid,"Image_URL":urljoin(base,x),"Alt_Text":title,"Display_Order":j,"Is_Main":j==1} for j,x in enumerate(imgs,1)]

async def extract_live(url):
    headers={"User-Agent":settings.user_agent,"Accept":"text/html,application/xhtml+xml"}
    async with httpx.AsyncClient(timeout=settings.request_timeout,headers=headers) as client:
        response=await fetch(client,url)
        html=response.text; soup=BeautifulSoup(html,"lxml"); marker=(html+" "+str(response.headers)).lower()
        salla_signals=["salla", "cdn.salla", "salla.sa", "salla-theme"]
        if not any(x in marker for x in salla_signals): raise ExtractionFailure("NOT_SALLA_STORE","The target does not appear to be a public Salla storefront")
        raw=json_objects(soup); products=[]; images=[]
        def walk(value):
            if isinstance(value,dict):
                if value.get("@type")=="Product":
                    got=product_from_json(value,url,len(products)+1)
                    if got: products.append(got[0]); images.extend(got[1])
                for v in value.values(): walk(v)
            elif isinstance(value,list):
                for v in value: walk(v)
        walk(raw)
        # Conservative discovery: parse only explicit product JSON-LD links; no invented catalog.
        if not products: raise ExtractionFailure("UNSUPPORTED_STRUCTURE","Salla storefront detected, but no public structured product records were exposed")
        name=text_or_none((soup.title.string if soup.title else None)) or "Salla Store"
        store=[{"Store_ID":stable_id("store",url),"Store_Name":name,"Store_URL":url,"Currency":next((p["Currency"] for p in products if p["Currency"]),None),"Language":soup.html.get("lang") if soup.html else None,"Extraction_Date":__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),"Data_Mode":"LIVE","Extractor_Version":"1.0.0"}]
        tables={"store":store,"categories":[],"products":products,"product_categories":[],"images":images,"product_options":[],"option_values":[],"variants":[],"variant_option_values":[],"tags":[],"product_tags":[],"seo":[]}
        return tables,{"json_ld":raw,"source_url":url,"strategies":["JSON_LD","HTML_DISCOVERY"],"pages_fetched":1}
