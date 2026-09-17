import asyncio
import gc
import json
import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qsl, unquote, urljoin, urlparse
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from backend.app.config import settings
from backend.app.utils import html_to_text, number_or_none, safe_redirect, stable_id, text_or_none, validate_public_host

log = logging.getLogger(__name__)
PRODUCT_PATH = re.compile(r"(?:^|/)p(\d+)(?:/)?$")
CATEGORY_PATH = re.compile(r"(?:^|/)c(\d+)(?:/)?$")
SIZE_VOLUME = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(مل|مليلتر|مللي|ml|ltr|liter|l|لتر|جم|غرام|g|kg|كجم)\b", re.IGNORECASE)
SOCIAL_HOSTS = {
    "instagram.com": "Social_Instagram",
    "facebook.com": "Social_Facebook",
    "twitter.com": "Social_X_Twitter",
    "x.com": "Social_X_Twitter",
    "tiktok.com": "Social_TikTok",
    "snapchat.com": "Social_Snapchat",
    "youtube.com": "Social_YouTube",
    "youtu.be": "Social_YouTube",
    "linkedin.com": "Social_LinkedIn",
    "wa.me": "Social_WhatsApp",
    "whatsapp.com": "Social_WhatsApp",
}


@dataclass
class FetchedPage:
    text: str
    headers: dict
    status_code: int
    strategy: str
    url: str


class ExtractionFailure(RuntimeError):
    def __init__(self, code, message, environmental=False):
        super().__init__(message)
        self.code = code
        self.environmental = environmental


def request_headers() -> dict[str, str]:
    """Stable, transparent headers; rate compliance is handled by pacing."""
    return {"User-Agent": settings.user_agent, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8", "Accept-Language": "ar,en;q=0.8", "Cache-Control": "no-cache"}


def rate_limit_delay(headers: dict, attempt: int) -> float:
    exponential = settings.rate_limit_backoff_min_seconds * (1.5**attempt)
    bounded = min(settings.rate_limit_backoff_max_seconds, max(settings.rate_limit_backoff_min_seconds, exponential))
    retry_after = number_or_none(headers.get("retry-after"))
    # Honor a server-provided delay, with a safety ceiling for malformed values.
    return min(60.0, max(bounded, retry_after or 0))


async def _scrapling_fetch(url: str) -> FetchedPage:
    """Fetch public content with bounded retries and validated redirects."""
    from scrapling.fetchers import AsyncFetcher

    for attempt in range(settings.max_retries + 1):
        current = validate_public_host(url)
        for _ in range(4):
            page = await AsyncFetcher.get(current, follow_redirects=False, timeout=settings.request_timeout, retries=0, headers=request_headers())
            status = int(page.status)
            headers = {str(k).lower(): str(v) for k, v in dict(page.headers or {}).items()}
            if status in {301, 302, 303, 307, 308}:
                current = safe_redirect(current, headers.get("location", ""))
                continue
            if status == 429:
                if attempt < settings.max_retries:
                    delay = rate_limit_delay(headers, attempt)
                    log.warning("HTTP 429 for %s; retry %s/%s in %.1fs", current, attempt + 1, settings.max_retries, delay)
                    await asyncio.sleep(delay)
                    break
                raise ExtractionFailure("RATE_LIMITED", "The storefront rate-limited extraction")
            if status in {401, 403}:
                raise ExtractionFailure("ACCESS_DENIED", "The public storefront denied access")
            if status >= 400:
                raise ExtractionFailure("NETWORK_ERROR", f"Storefront returned HTTP {status}")
            encoding = getattr(page, "encoding", None) or "utf-8"
            return FetchedPage(page.body.decode(encoding, errors="replace"), headers, status, "SCRAPLING_HTTP", current)
        else:
            raise ExtractionFailure("ACCESS_DENIED", "Too many redirects")
    raise ExtractionFailure("RATE_LIMITED", "The storefront rate-limited extraction")


async def fetch(client: httpx.AsyncClient, url: str) -> FetchedPage:
    last = None
    if settings.enable_scrapling:
        try:
            return await _scrapling_fetch(url)
        except ExtractionFailure:
            raise
        except Exception as exc:
            last = exc
            log.warning("Scrapling failed for %s; falling back to httpx: %s", url, type(exc).__name__)
    for attempt in range(settings.max_retries + 1):
        try:
            current = validate_public_host(url)
            for _ in range(4):
                response = await client.get(current, follow_redirects=False)
                if response.status_code in {301, 302, 303, 307, 308}:
                    current = safe_redirect(current, response.headers.get("location", ""))
                    continue
                if response.status_code == 429:
                    if attempt < settings.max_retries:
                        delay = rate_limit_delay({str(k).lower(): str(v) for k, v in response.headers.items()}, attempt)
                        log.warning("HTTP 429 for %s; httpx retry %s/%s in %.1fs", current, attempt + 1, settings.max_retries, delay)
                        await asyncio.sleep(delay)
                        break
                    raise ExtractionFailure("RATE_LIMITED", "The storefront rate-limited extraction after bounded retries")
                if response.status_code in {401, 403}:
                    raise ExtractionFailure("ACCESS_DENIED", "The public storefront denied access")
                response.raise_for_status()
                return FetchedPage(response.text, dict(response.headers), response.status_code, "HTTPX", current)
            else:
                raise ExtractionFailure("ACCESS_DENIED", "Too many redirects")
        except ExtractionFailure:
            raise
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError, ValueError) as exc:
            last = exc
            if attempt < settings.max_retries:
                await asyncio.sleep(0.35 * (2**attempt))
    raise ExtractionFailure("PREVIEW_NETWORK_RESTRICTED", f"External store access failed: {type(last).__name__}", True)


def json_objects(soup: BeautifulSoup) -> list[dict]:
    out = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(node.string or node.get_text())
            out.extend(value if isinstance(value, list) else [value])
        except (TypeError, json.JSONDecodeError):
            continue
    return [x for x in out if isinstance(x, dict)]


def embedded_json_objects(soup: BeautifulSoup) -> list[dict]:
    """Read public serialized storefront state without calling private endpoints."""
    out = json_objects(soup)
    for node in soup.select('script[type="application/json"],script[id="__NEXT_DATA__"]'):
        try:
            value = json.loads(node.string or node.get_text())
            out.extend(value if isinstance(value, list) else [value])
        except (TypeError, json.JSONDecodeError):
            continue
    # Salla exposes product/category analytics as a public JSON object.
    for node in soup.find_all("script"):
        script = node.string or node.get_text()
        if "dataLayer.push(" not in script:
            continue
        for match in re.finditer(r"dataLayer\.push\((\{.*?\})\);", script, re.DOTALL):
            try:
                value = json.loads(match.group(1))
                if isinstance(value, dict): out.append(value)
            except json.JSONDecodeError:
                continue
    return [x for x in out if isinstance(x, dict)]


def walk_json(values):
    for value in values:
        if isinstance(value, dict):
            yield value
            yield from walk_json(value.values())
        elif isinstance(value, list):
            yield from walk_json(value)


def _meta_content(soup: BeautifulSoup, *selectors: str) -> str | None:
    for selector in selectors:
        node = soup.select_one(selector)
        if node and text_or_none(node.get("content")):
            return text_or_none(node.get("content"))
    return None


def website_data_from_page(raw: list[dict], soup: BeautifulSoup, url: str, strategy: str = "PUBLIC_HTML"):
    """Normalize only public website identity/contact metadata from one page."""
    entity_types = {"organization", "localbusiness", "store", "onlinestore", "website"}
    entities = [obj for obj in walk_json(raw) if str(obj.get("@type", "")).lower() in entity_types]
    primary = next((obj for obj in entities if str(obj.get("@type", "")).lower() != "website"), entities[0] if entities else {})
    canonical_node = soup.select_one('link[rel="canonical"][href]')
    canonical = urljoin(url, canonical_node.get("href")) if canonical_node else url
    title = _meta_content(soup, 'meta[property="og:site_name"]', 'meta[property="og:title"]')
    name = text_or_none(primary.get("name") or primary.get("legalName") or title or (soup.title.string if soup.title else None))
    description = text_or_none(primary.get("description") or _meta_content(soup, 'meta[name="description"]', 'meta[property="og:description"]'))
    logo_values = image_urls(primary.get("logo")) or image_urls(_meta_content(soup, 'meta[property="og:image"]'))
    telephone = text_or_none(primary.get("telephone"))
    email = text_or_none(primary.get("email"))
    address = primary.get("address") if isinstance(primary.get("address"), dict) else {}
    geo = primary.get("geo") if isinstance(primary.get("geo"), dict) else {}
    contact_points = primary.get("contactPoint") or []
    contact_points = contact_points if isinstance(contact_points, list) else [contact_points]
    if not telephone:
        telephone = next((text_or_none(point.get("telephone")) for point in contact_points if isinstance(point, dict) and point.get("telephone")), None)
    if not email:
        email = next((text_or_none(point.get("email")) for point in contact_points if isinstance(point, dict) and point.get("email")), None)
    if not telephone:
        tel_node = soup.select_one('a[href^="tel:"]')
        telephone = text_or_none(tel_node.get("href", "")[4:]) if tel_node else None
    if not email:
        email_node = soup.select_one('a[href^="mailto:"]')
        email = text_or_none(email_node.get("href", "")[7:].split("?", 1)[0]) if email_node else None

    rows = []
    seen = set()

    def add(field, value, source="JSON_LD_OR_HTML"):
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        value = text_or_none(value)
        key = (field, value)
        if value and key not in seen:
            seen.add(key)
            rows.append({"Field": field, "Value": value, "Source_URL": canonical, "Source_Strategy": source})

    add("Store_Name", name)
    add("Legal_Name", primary.get("legalName"))
    add("Description", description)
    for logo in logo_values:
        add("Logo_URL", urljoin(url, logo))
    add("Phone", telephone)
    add("Email", email)
    add("Address_Street", address.get("streetAddress"))
    add("Location_City", address.get("addressLocality"))
    add("Location_Region", address.get("addressRegion"))
    add("Postal_Code", address.get("postalCode"))
    country = address.get("addressCountry")
    add("Country", country.get("name") if isinstance(country, dict) else country)
    add("Latitude", geo.get("latitude"))
    add("Longitude", geo.get("longitude"))
    add("Opening_Hours", primary.get("openingHours") or primary.get("openingHoursSpecification"))
    add("VAT_ID", primary.get("vatID") or primary.get("taxID"))
    add("Public_URL", primary.get("url") or canonical)
    add("Language", soup.html.get("lang") if soup.html else None, "HTML")

    social_urls = primary.get("sameAs") or []
    social_urls = [social_urls] if isinstance(social_urls, str) else social_urls
    social_urls = [*social_urls, *(node.get("href") for node in soup.select("a[href]") if node.get("href"))]
    for social_url in social_urls:
        absolute = urljoin(url, str(social_url))
        host = urlparse(absolute).hostname or ""
        field = next((label for domain, label in SOCIAL_HOSTS.items() if host == domain or host.endswith(f".{domain}")), None)
        if field:
            add(field, absolute, "JSON_LD_OR_LINK")

    store = [{"Store_ID": stable_id("store", canonical), "Store_Name": name or "Salla Store", "Store_URL": canonical, "Currency": None, "Language": soup.html.get("lang") if soup.html else None, "Extraction_Date": datetime.now(timezone.utc).isoformat(), "Data_Mode": "LIVE", "Extractor_Version": "1.7.0"}]
    return store, rows


async def extract_website_data(url: str):
    headers = request_headers()
    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.request_timeout), headers=headers) as client:
        page = await fetch(client, url)
    marker = (page.text + " " + str(page.headers)).lower()
    if not any(value in marker for value in ["salla", "cdn.salla", "salla.sa", "salla-theme"]):
        raise ExtractionFailure("NOT_SALLA_STORE", "The target does not appear to be a public Salla storefront")
    soup = BeautifulSoup(page.text, "lxml")
    store, website_rows = website_data_from_page(embedded_json_objects(soup), soup, page.url, page.strategy)
    tables = {"store": store, "website_data": website_rows}
    raw = {"source_url": url, "resolved_url": page.url, "target_scope": "WEBSITE", "data_type": "WEBSITE", "exact_url_preserved": True, "strategies": [page.strategy], "pages_fetched": 1, "products_discovered": 0, "products_selected": 0, "products_extracted": 0, "public_fields_extracted": len(website_rows)}
    return tables, raw


def parse_sitemap(xml: str) -> tuple[list[str], list[dict]]:
    """Return nested sitemap URLs and URL entries without relying on namespaces."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return [], []
    nested, entries = [], []
    for node in root.iter():
        node_type = node.tag.rsplit("}", 1)[-1]
        if node_type not in {"sitemap", "url"}:
            continue
        loc = next((text_or_none(c.text) for c in node if c.tag.rsplit("}", 1)[-1] == "loc"), None)
        if not loc:
            continue
        if node_type == "sitemap":
            nested.append(loc)
            continue
        lastmod = next((text_or_none(c.text) for c in node if c.tag.rsplit("}", 1)[-1] == "lastmod"), None)
        images = [text_or_none(c.text) for c in node.iter() if c.tag.rsplit("}", 1)[-1] == "loc"][1:]
        entries.append({"url": loc, "lastmod": lastmod, "images": [x for x in images if x]})
    return nested, entries


def source_id_from_url(url: str, pattern=PRODUCT_PATH):
    match = pattern.search(urlparse(url).path.rstrip("/"))
    return match.group(1) if match else None


def extraction_scope(url: str) -> str:
    parsed = urlparse(url)
    if source_id_from_url(url):
        return "PRODUCT"
    if parsed.path.rstrip("/") or parse_qsl(parsed.query, keep_blank_values=True):
        return "CATEGORY"
    return "STORE"


def product_entries_from_dom(soup: BeautifulSoup, page_url: str) -> list[dict]:
    entries = {}
    selectors = 'salla-products-list a[href], salla-product-card a[href], .s-product-card a[href], [data-product-id] a[href], [data-product-id][data-url], [product-url]'
    for node in soup.select(selectors):
        candidate = node.get("href") or node.get("data-url") or node.get("product-url")
        if not candidate:
            continue
        product_url = urljoin(page_url, candidate)
        if source_id_from_url(product_url):
            entries[product_url] = {"url": product_url, "lastmod": None, "images": []}
    for obj in walk_json(embedded_json_objects(soup)):
        candidate = obj.get("url") if isinstance(obj, dict) else None
        if candidate:
            product_url = urljoin(page_url, candidate)
            if source_id_from_url(product_url):
                entries[product_url] = {"url": product_url, "lastmod": None, "images": image_urls(obj.get("image") or obj.get("images"))}
    return list(entries.values())


async def discover_category_products(client, exact_url: str, first_page: FetchedPage, max_pages: int):
    queue, seen, products, strategies = [(exact_url, first_page)], set(), {}, set()
    while queue and len(seen) < max_pages:
        page_url, prefetched = queue.pop(0)
        if page_url in seen:
            continue
        seen.add(page_url)
        page = prefetched or await fetch(client, page_url)
        strategies.add(page.strategy)
        soup = BeautifulSoup(page.text, "lxml")
        for entry in product_entries_from_dom(soup, page.url):
            products[entry["url"]] = entry
        for node in soup.select('link[rel="next"][href], a[rel="next"][href], .pagination a[href]'):
            next_url = urljoin(page.url, node.get("href"))
            if urlparse(next_url).netloc == urlparse(exact_url).netloc and next_url not in seen:
                queue.append((next_url, None))
    return list(products.values()), len(seen), sorted(strategies)


def slug_name(url: str) -> tuple[str | None, str | None]:
    parts = [unquote(x) for x in urlparse(url).path.split("/") if x]
    if not parts:
        return None, None
    slug = parts[-2] if re.fullmatch(r"[pc]\d+", parts[-1]) and len(parts) > 1 else parts[-1]
    return slug, text_or_none(re.sub(r"[-+_]", " ", slug))


def extract_size_volume(*values) -> str | None:
    match = SIZE_VOLUME.search(" ".join(str(x or "") for x in values))
    return f"{match.group(1).replace(',', '.')} {match.group(2)}" if match else None


def image_urls(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        direct = value.get("url") or value.get("contentUrl") or value.get("src") or value.get("original")
        nested = image_urls(direct) if direct else []
        for key in ("images", "gallery", "items"):
            nested.extend(image_urls(value.get(key)))
        return nested
    if isinstance(value, list):
        return [url for item in value for url in image_urls(item)]
    return []


def offer_prices(product: dict, offer: dict) -> tuple[float | None, float | None]:
    current = number_or_none(offer.get("price") or offer.get("lowPrice"))
    specifications = offer.get("priceSpecification") or product.get("priceSpecification") or []
    specifications = specifications if isinstance(specifications, list) else [specifications]
    values = [current]
    for specification in specifications:
        if isinstance(specification, dict):
            values.extend(number_or_none(specification.get(key)) for key in ("price", "value", "minPrice", "maxPrice"))
    values.append(number_or_none(offer.get("highPrice") or product.get("original_price") or product.get("regular_price")))
    values = [value for value in values if value is not None]
    if not values:
        return None, None
    original, discounted = max(values), min(values)
    return original, discounted if discounted < original else None


def product_from_page(raw: list[dict], soup: BeautifulSoup, url: str, sitemap_entry: dict | None = None):
    product_obj = next((x for x in walk_json(raw) if str(x.get("@type", "")).lower() == "product"), None)
    source_id = (product_obj or {}).get("productID") or source_id_from_url(url)
    title = text_or_none((product_obj or {}).get("name"))
    if not title:
        meta = soup.select_one('meta[property="og:title"]')
        title = text_or_none(meta.get("content") if meta else None)
    if not title or not source_id:
        return None
    pid = str(source_id)
    public_record = next((x for x in walk_json(raw) if str(x.get("id", "")) == pid and any(k in x for k in ("categories", "category", "images", "image"))), {})
    offers = (product_obj or {}).get("offers") or {}
    offer_list = offers if isinstance(offers, list) else [offers]
    offer = next((x for x in offer_list if isinstance(x, dict)), {})
    desc = (product_obj or {}).get("description")
    if desc is None:
        meta = soup.select_one('meta[name="description"]')
        desc = meta.get("content") if meta else None
    canonical_node = soup.select_one('link[rel="canonical"]')
    canonical = urljoin(url, canonical_node.get("href")) if canonical_node and canonical_node.get("href") else url
    slug, _ = slug_name(canonical)
    images = image_urls((product_obj or {}).get("image"))
    for key in ("image", "images", "gallery", "photos"):
        images.extend(image_urls(public_record.get(key)))
    for candidate in walk_json(raw):
        if candidate is product_obj or str(candidate.get("@type", "")).lower() == "product":
            for key in ("images", "gallery", "photos"):
                images.extend(image_urls(candidate.get(key)))
    images.extend(node.get("content") for node in soup.select('meta[property="og:image"]') if node.get("content"))
    for node in soup.select('salla-slider img, .breadcrumb-product img, [data-product-image] img, img[data-src]'):
        candidate = node.get("data-src") or node.get("src")
        if candidate and not candidate.lower().endswith(".svg"):
            images.append(candidate)
    if not images and sitemap_entry:
        images = sitemap_entry.get("images", [])
    price, sale_price = offer_prices(product_obj or {}, offer)
    if price is None:
        price_meta = soup.select_one('meta[property="product:price:amount"]')
        price = number_or_none(price_meta.get("content") if price_meta else None)
    currency = text_or_none(offer.get("priceCurrency"))
    if currency is None:
        currency_meta = soup.select_one('meta[property="product:price:currency"]')
        currency = text_or_none(currency_meta.get("content") if currency_meta else None)
    availability = offer.get("availability")
    weight_obj = (product_obj or {}).get("weight") or (product_obj or {}).get("size")
    if isinstance(weight_obj, dict):
        weight, weight_unit = number_or_none(weight_obj.get("value")), text_or_none(weight_obj.get("unitCode") or weight_obj.get("unitText"))
        size_volume = " ".join(str(x) for x in [weight, weight_unit] if x is not None) or None
    else:
        weight, weight_unit, size_volume = number_or_none(weight_obj), None, text_or_none(weight_obj)
    size_volume = size_volume or extract_size_volume(title, desc)
    notes = text_or_none((product_obj or {}).get("notes") or public_record.get("notes") or (product_obj or {}).get("disambiguatingDescription"))
    shipping = (product_obj or {}).get("shippingDetails") or offer.get("shippingDetails")
    shipping_status = text_or_none(shipping.get("shippingLabel") if isinstance(shipping, dict) else shipping)
    product = {"Product_ID": pid, "Title": title, "Slug": slug, "SKU": text_or_none((product_obj or {}).get("sku")), "Barcode": text_or_none((product_obj or {}).get("gtin13") or (product_obj or {}).get("gtin")), "Product_Type": None, "Price": price, "Sale_Price": sale_price, "Currency": currency, "Cost_Price": None, "Quantity": None, "Is_Available": ("InStock" in str(availability)) if availability else None, "Is_Active": True, "Brand": text_or_none(((product_obj or {}).get("brand") or {}).get("name") if isinstance((product_obj or {}).get("brand"), dict) else (product_obj or {}).get("brand")), "Weight": weight, "Weight_Unit": weight_unit, "Size_Volume": size_volume, "Notes": notes, "Shipping_Status": shipping_status, "Short_Description": notes, "Description_HTML": desc, "Description_Text": html_to_text(desc), "Product_URL": canonical, "Created_At": None, "Updated_At": (sitemap_entry or {}).get("lastmod")}
    image_rows = [{"Image_ID": stable_id("img", pid, image), "Product_ID": pid, "Image_URL": image, "Alt_Text": title, "Display_Order": order, "Is_Main": order == 1} for order, image in enumerate(dict.fromkeys(urljoin(url, str(x)) for x in images if x), 1)]
    variants = []
    if len(offer_list) > 1:
        for item in offer_list:
            if not isinstance(item, dict):
                continue
            identifier = item.get("sku") or item.get("url")
            if identifier:
                variants.append({"Variant_ID": stable_id("var", pid, identifier), "Product_ID": pid, "SKU": text_or_none(item.get("sku")), "Barcode": text_or_none(item.get("gtin13") or item.get("gtin")), "Price": number_or_none(item.get("price")), "Sale_Price": None, "Quantity": None, "Is_Available": "InStock" in str(item.get("availability")) if item.get("availability") else None, "Weight": None, "Weight_Unit": None})
    meta_desc = soup.select_one('meta[name="description"]')
    seo = {"Entity_Type": "PRODUCT", "Entity_ID": pid, "Meta_Title": text_or_none(soup.title.string if soup.title else title), "Meta_Description": text_or_none(meta_desc.get("content") if meta_desc else None), "Canonical_URL": canonical}
    breadcrumbs = []
    for obj in walk_json(raw):
        if str(obj.get("@type", "")).lower() != "breadcrumblist":
            continue
        for item in obj.get("itemListElement", []):
            value = item.get("item", {}) if isinstance(item, dict) else {}
            name = text_or_none(item.get("name") or (value.get("name") if isinstance(value, dict) else None))
            item_url = item.get("item") if isinstance(item.get("item"), str) else value.get("@id") if isinstance(value, dict) else None
            if name and item_url and CATEGORY_PATH.search(urlparse(item_url).path.rstrip("/")):
                breadcrumbs.append((name, item_url))
    for node in soup.select('nav[aria-label*="breadcrumb" i] a, .breadcrumb a, [class*="breadcrumb"] a'):
        item_url = urljoin(url, node.get("href", ""))
        name = text_or_none(node.get_text(" "))
        if name and CATEGORY_PATH.search(urlparse(item_url).path.rstrip("/")):
            breadcrumbs.append((name, item_url))
    category_value = (product_obj or {}).get("category")
    if not breadcrumbs and category_value:
        category_name = text_or_none(category_value.get("name") if isinstance(category_value, dict) else category_value)
        category_url = category_value.get("url") if isinstance(category_value, dict) else None
        if category_name:
            breadcrumbs.append((category_name, urljoin(url, category_url) if category_url else ""))
    for category in public_record.get("categories", []) if isinstance(public_record.get("categories"), list) else []:
        if not isinstance(category, dict): continue
        category_name, category_id = text_or_none(category.get("name")), category.get("id")
        if category_name and category_id:
            breadcrumbs.append((category_name, urljoin(url, f"/c{category_id}")))
    return product, image_rows, variants, seo, breadcrumbs


async def discover_sitemaps(client, base_url: str, max_pages: int, max_depth: int):
    queue, seen, entries, strategies = [(urljoin(base_url, "/sitemap.xml"), 0)], set(), [], set()
    while queue and len(seen) < max_pages:
        sitemap_url, depth = queue.pop(0)
        if sitemap_url in seen:
            continue
        seen.add(sitemap_url)
        try:
            page = await fetch(client, sitemap_url)
        except ExtractionFailure as exc:
            log.warning("Sitemap request failed %s: %s", sitemap_url, exc.code)
            continue
        strategies.add(page.strategy)
        nested, found = parse_sitemap(page.text)
        entries.extend(found)
        for child in nested:
            child = urljoin(sitemap_url, child)
            if depth < max_depth and child not in seen and len(seen) + len(queue) < max_pages:
                queue.append((child, depth + 1))
    return list({x["url"]: x for x in entries}.values()), len(seen), sorted(strategies)


async def extract_live(url: str, extraction_mode: str = "QUICK", progress_callback=None, checkpoint_callback=None, checkpoint_loader=None):
    is_full = extraction_mode == "FULL"
    timeout_seconds = settings.full_extraction_timeout_seconds if is_full else settings.extraction_timeout_seconds
    deadline = time.monotonic() + timeout_seconds
    max_pages = settings.max_pages if is_full else settings.quick_max_pages
    max_depth = settings.max_sitemap_depth if is_full else settings.quick_sitemap_depth
    max_products = None if is_full else settings.quick_products
    headers = request_headers()
    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.request_timeout), headers=headers) as client:
        home = await fetch(client, url)
        marker = (home.text + " " + str(home.headers)).lower()
        if not any(x in marker for x in ["salla", "cdn.salla", "salla.sa", "salla-theme"]):
            raise ExtractionFailure("NOT_SALLA_STORE", "The target does not appear to be a public Salla storefront")
        home_soup = BeautifulSoup(home.text, "lxml")
        scope = extraction_scope(url)
        timed_out = False
        if scope == "STORE":
            try:
                sitemap_entries, sitemap_pages, sitemap_strategies = await asyncio.wait_for(discover_sitemaps(client, url, max_pages, max_depth), timeout=min(settings.sitemap_timeout_seconds if not is_full else 120, max(0.1, deadline - time.monotonic())))
            except asyncio.TimeoutError:
                sitemap_entries, sitemap_pages, sitemap_strategies, timed_out = [], 0, [], True
            product_entries = [x for x in sitemap_entries if source_id_from_url(x["url"])]
            category_entries = [x for x in sitemap_entries if source_id_from_url(x["url"], CATEGORY_PATH)]
        elif scope == "PRODUCT":
            sitemap_entries, sitemap_pages, sitemap_strategies = [], 0, [home.strategy]
            product_entries = [{"url": url, "lastmod": None, "images": []}]
            category_entries = []
        else:
            product_entries, sitemap_pages, sitemap_strategies = await discover_category_products(client, url, home, max_pages)
            sitemap_entries = product_entries
            category_entries = [{"url": url, "lastmod": None, "images": []}] if source_id_from_url(url, CATEGORY_PATH) else []
            if not product_entries:
                raise ExtractionFailure("UNSUPPORTED_STRUCTURE", "The exact category page is client-rendered and exposes no public product cards in its HTML. No store-wide sitemap fallback was used.")
        if not product_entries:
            raise ExtractionFailure("UNSUPPORTED_STRUCTURE", "No public product links were found for the submitted URL")
        categories, category_by_url = [], {}
        for order, entry in enumerate(category_entries, 1):
            cid = source_id_from_url(entry["url"], CATEGORY_PATH)
            slug, name = slug_name(entry["url"])
            row = {"Category_ID": cid, "Parent_Category_ID": None, "Name": name or cid, "Slug": slug, "URL": entry["url"], "Description": None, "Display_Order": order, "Is_Active": True}
            categories.append(row)
            category_by_url[entry["url"].rstrip("/")] = row
        semaphore, failures, results, processed_urls = asyncio.Semaphore(settings.max_concurrent_requests), {}, {}, set()

        async def extract_one(entry):
            async with semaphore:
                try:
                    page = home if entry["url"].rstrip("/") == url.rstrip("/") else await fetch(client, entry["url"])
                    soup = BeautifulSoup(page.text, "lxml")
                    parsed = product_from_page(embedded_json_objects(soup), soup, page.url, entry)
                    if parsed:
                        results[entry["url"]] = (parsed, page.strategy)
                        failures.pop(entry["url"], None)
                    else:
                        failures[entry["url"]] = {"url": entry["url"], "code": "PARSING_ERROR", "message": "No reliable public product record found"}
                except Exception as exc:
                    failures[entry["url"]] = {"url": entry["url"], "code": getattr(exc, "code", "PARSING_ERROR"), "message": str(exc)[:240]}
                finally:
                    processed_urls.add(entry["url"])
                    await asyncio.sleep(random.uniform(settings.request_pacing_min_seconds, settings.request_pacing_max_seconds))

        selected_entries = product_entries if max_products is None else product_entries[:max_products]
        total = len(selected_entries)
        if progress_callback:
            await progress_callback(0, total)

        batch_number = 0
        async def run_batches(entries):
            nonlocal timed_out, batch_number
            for offset in range(0, len(entries), settings.extraction_batch_size):
                if time.monotonic() >= deadline:
                    timed_out = True; break
                batch = entries[offset:offset + settings.extraction_batch_size]
                tasks = [asyncio.create_task(extract_one(entry)) for entry in batch]
                _, pending = await asyncio.wait(tasks, timeout=max(0.1, deadline - time.monotonic()))
                if pending:
                    timed_out = True
                    for task in pending: task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                batch_number += 1
                if checkpoint_callback:
                    completed = {entry["url"]: results.pop(entry["url"]) for entry in batch if entry["url"] in results}
                    await checkpoint_callback(batch_number, completed)
                    completed.clear()
                    gc.collect()
                if progress_callback:
                    await progress_callback(min(len(processed_urls), total), total)
                if timed_out: break

        await run_batches(selected_entries)
        # One bounded second pass recovers transient failures without duplicating successful rows.
        if failures and not timed_out:
            retry_entries = [entry for entry in selected_entries if entry["url"] in failures]
            await run_batches(retry_entries)
        if checkpoint_loader:
            for checkpoint in await checkpoint_loader():
                results.update(checkpoint)
        products, images, variants, seo, product_categories = [], [], [], [], []
        strategies = {home.strategy, *sitemap_strategies}
        for parsed, strategy in results.values():
            product, image_rows, variant_rows, seo_row, breadcrumbs = parsed
            strategies.add(strategy); products.append(product); images.extend(image_rows); variants.extend(variant_rows); seo.append(seo_row)
            for name, category_url in breadcrumbs:
                key = category_url.rstrip("/") or f"name:{name.casefold()}"
                category = category_by_url.get(key)
                if not category:
                    cid = source_id_from_url(category_url, CATEGORY_PATH) or stable_id("cat", category_url or name)
                    slug, _ = slug_name(category_url)
                    category = {"Category_ID": cid, "Parent_Category_ID": None, "Name": name, "Slug": slug, "URL": category_url, "Description": None, "Display_Order": len(categories) + 1, "Is_Active": True}
                    categories.append(category); category_by_url[key] = category
                product_categories.append({"Product_ID": product["Product_ID"], "Category_ID": category["Category_ID"], "Is_Primary": not any(x["Product_ID"] == product["Product_ID"] for x in product_categories)})
        products = list({x["Product_ID"]: x for x in products}.values())
        images = list({x["Image_ID"]: x for x in images}.values())
        variants = list({x["Variant_ID"]: x for x in variants}.values())
        product_categories = list({(x["Product_ID"], x["Category_ID"]): x for x in product_categories}.values())
        if not products:
            raise ExtractionFailure("UNSUPPORTED_STRUCTURE", "Salla storefront detected, but no public product records could be structured")
        name = text_or_none(home_soup.title.string if home_soup.title else None) or "Salla Store"
        store = [{"Store_ID": stable_id("store", url), "Store_Name": name, "Store_URL": url, "Currency": next((p["Currency"] for p in products if p["Currency"]), None), "Language": home_soup.html.get("lang") if home_soup.html else None, "Extraction_Date": datetime.now(timezone.utc).isoformat(), "Data_Mode": "LIVE", "Extractor_Version": "1.6.0"}]
        tables = {"store": store, "categories": categories, "products": products, "product_categories": product_categories, "images": images, "product_options": [], "option_values": [], "variants": variants, "variant_option_values": [], "tags": [], "product_tags": [], "seo": seo}
        raw = {"source_url": url, "target_scope": scope, "exact_url_preserved": True, "extraction_mode": extraction_mode, "strategies": sorted(strategies), "pages_fetched": 1 + sitemap_pages + len(results) + len(failures), "sitemap_pages": sitemap_pages, "sitemap_entries": len(sitemap_entries), "products_discovered": len(product_entries), "products_selected": len(selected_entries), "products_extracted": len(products), "extraction_failures": list(failures.values()), "safety_truncated": max_products is not None and len(product_entries) > max_products, "timed_out": timed_out, "timeout_seconds": timeout_seconds}
        return tables, raw
