import hashlib, html, ipaddress, re, socket
from urllib.parse import parse_qsl, urlencode, urlparse, urljoin
from bs4 import BeautifulSoup

class URLSafetyError(ValueError): pass

def normalize_url(value: str) -> str:
    value=value.strip()
    parsed=urlparse(value)
    if parsed.scheme not in {"http","https"}: raise URLSafetyError("Only HTTP and HTTPS URLs are allowed")
    if not parsed.hostname or parsed.username or parsed.password: raise URLSafetyError("Invalid public store URL")
    host=parsed.hostname.lower().rstrip('.')
    if host in {"localhost","localhost.localdomain"} or host.endswith(".local"): raise URLSafetyError("Local addresses are blocked")
    try:
        port=parsed.port
    except ValueError as exc:
        raise URLSafetyError("Invalid URL port") from exc
    # Re-encode complex Salla filters such as filters[category_id] safely.
    try:
        query=urlencode(parse_qsl(parsed.query,keep_blank_values=True),doseq=True)
    except ValueError as exc:
        raise URLSafetyError("Invalid URL query parameters") from exc
    return parsed._replace(netloc=host+(f":{port}" if port else ""), path=parsed.path or "/", query=query, fragment="").geturl()

def validate_public_host(url: str) -> str:
    url=normalize_url(url); host=urlparse(url).hostname
    try: addresses={x[4][0] for x in socket.getaddrinfo(host, None)}
    except socket.gaierror as exc: raise URLSafetyError("Hostname could not be resolved") from exc
    for value in addresses:
        ip=ipaddress.ip_address(value)
        if not ip.is_global or ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise URLSafetyError("Private or unsafe network targets are blocked")
    return url

def safe_redirect(base: str, location: str) -> str: return validate_public_host(urljoin(base,location))
def stable_id(prefix: str, *parts: object) -> str:
    raw="|".join(str(x or "").strip().lower() for x in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode()).hexdigest()[:18]}"
def text_or_none(v):
    if v is None:return None
    s=re.sub(r"\s+"," ",str(v)).strip(); return s or None
def html_to_text(value): return text_or_none(BeautifulSoup(value or "", "lxml").get_text(" "))
def number_or_none(v):
    if v in (None,""): return None
    try: return float(re.sub(r"[^0-9.\-]","",str(v)))
    except (ValueError,TypeError): return None
def bool_or_none(v):
    if v is None:return None
    if isinstance(v,bool):return v
    s=str(v).strip().lower()
    if s in {"true","1","yes","available","in stock","متوفر"}:return True
    if s in {"false","0","no","unavailable","out of stock","غير متوفر"}:return False
    return None
