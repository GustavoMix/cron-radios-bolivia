"""Enriquece cada radio con datos de su sitio web: logo, portada, descripcion, color y redes.

Solo libreria estandar. Los resultados se guardan en data/enrichment.json para no repetir
las descargas todos los dias (exitos se renuevan cada 30 dias, fallos cada 7).
"""
from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

USER_AGENT = "Mozilla/5.0 (compatible; cron-radios-bolivia/1.0; +https://github.com/GustavoMix/cron-radios-bolivia)"
TIMEOUT = 8
MAX_HTML = 400_000
TTL_OK = 30 * 86400
TTL_FAIL = 7 * 86400
BAD_IMAGE_EXT = (".ico", ".svg", ".gif")

SOCIALS = {
    "facebook": ("facebook.com", "fb.com"),
    "instagram": ("instagram.com",),
    "tiktok": ("tiktok.com",),
    "youtube": ("youtube.com", "youtu.be"),
    "twitter": ("twitter.com", "x.com"),
    "whatsapp": ("wa.me", "api.whatsapp.com"),
}
SOCIAL_SKIP = ("sharer", "share?", "/share", "intent/", "dialog/", "plugins/", "/tr?", "login")


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.icons: list[tuple[str, str, int]] = []   # (rel, href, tamano)
        self.anchors: list[str] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content") and key not in self.meta:
                self.meta[key] = a["content"].strip()
        elif tag == "link" and a.get("href"):
            rel = a.get("rel", "").lower()
            if "icon" in rel:
                m = re.match(r"(\d+)x\d+", a.get("sizes", ""))
                self.icons.append((rel, a["href"], int(m.group(1)) if m else 0))
        elif tag == "a" and a.get("href"):
            self.anchors.append(a["href"])
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def _https(url: str, base: str) -> str:
    """URL absoluta; sube http -> https. Devuelve '' si no es utilizable."""
    if not url or url.startswith("data:"):
        return ""
    full = urljoin(base, url.strip())
    if full.startswith("http://"):
        full = "https://" + full[len("http://"):]
    return full if full.startswith("https://") else ""


def _good_image_url(url: str) -> bool:
    return bool(url) and not urlparse(url).path.lower().endswith(BAD_IMAGE_EXT)


def check_image(url: str) -> bool:
    """True si la URL responde con una imagen (lee solo el primer KB)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Range": "bytes=0-1023"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            r.read(1024)
            return r.status in (200, 206) and r.headers.get_content_type().startswith("image/")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def fetch_html(url: str) -> tuple[str, str]:
    """Devuelve (html, url_final)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        if "html" not in r.headers.get_content_type():
            raise ValueError("no es HTML")
        charset = r.headers.get_content_charset() or "utf-8"
        return r.read(MAX_HTML).decode(charset, errors="replace"), r.geturl()


def clean_description(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:.- ")
    return cut + "..."


def parse_color(value: str) -> str:
    """Valida un color hex y descarta blancos/negros puros (se ven mal como acento)."""
    m = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", (value or "").strip())
    if not m:
        return ""
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return f"#{h.lower()}" if 0.12 <= luminance <= 0.85 else ""


def extract_socials(anchors: list[str], base: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for href in anchors:
        url = _https(href, base)
        if not url:
            continue
        host = urlparse(url).netloc.lower().removeprefix("www.")
        low = url.lower()
        if any(s in low for s in SOCIAL_SKIP):
            continue
        for name, hosts in SOCIALS.items():
            if name not in found and any(host == h or host.endswith("." + h) for h in hosts):
                if urlparse(url).path.strip("/") or name == "whatsapp":  # evita la portada del sitio
                    found[name] = url
    return found


def parse_page(html: str, base: str) -> dict:
    """Extrae los datos utiles de un HTML (sin red; lo usan los tests)."""
    p = PageParser()
    p.feed(html)
    m = p.meta

    logo_candidates = sorted(
        (i for i in p.icons if "apple-touch" in i[0] or i[2] >= 64 or "icon" in i[0]),
        key=lambda i: ("apple-touch" not in i[0], -i[2]),
    )
    logos = [u for u in (_https(href, base) for _, href, _ in logo_candidates) if _good_image_url(u)]
    cover = _https(m.get("og:image") or m.get("twitter:image") or "", base)

    return {
        "logo_candidates": logos,
        "cover_url": cover if _good_image_url(cover) else "",
        "description": clean_description(m.get("og:description") or m.get("description") or ""),
        "color": parse_color(m.get("theme-color", "")) or parse_color(m.get("msapplication-tilecolor", "")),
        "links": extract_socials(p.anchors, base),
    }


def enrich_one(station: dict) -> dict:
    """Descarga la web de la radio y devuelve el resultado para guardar en cache."""
    result = {"checked": int(time.time()), "ok": False}
    site = _https(station.get("website", ""), "https://")
    if not site:
        return result
    try:
        html, final_url = fetch_html(site)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return result

    page = parse_page(html, final_url)
    current_logo = station.get("logo_url", "")
    if current_logo and check_image(current_logo):
        logo = current_logo
    else:
        logo = next((u for u in page["logo_candidates"] if check_image(u)), "")
    cover = page["cover_url"] if page["cover_url"] and check_image(page["cover_url"]) else ""
    if cover == logo:
        cover = ""

    result.update(ok=True, logo_url=logo, cover_url=cover, description=page["description"],
                  color=page["color"], links=page["links"], website=final_url)
    return result


def is_fresh(entry: dict | None, now: float) -> bool:
    if not entry:
        return False
    return now - entry.get("checked", 0) < (TTL_OK if entry.get("ok") else TTL_FAIL)


def enrich_all(stations: list[dict], cache: dict, workers: int = 8, now: float | None = None) -> dict:
    """Actualiza `cache` para las radios vencidas y aplica los datos a cada radio."""
    now = now or time.time()
    stale = [s for s in stations if not is_fresh(cache.get(s["id"]), now)]
    if stale:
        print(f"Enriqueciendo {len(stale)} radios (el resto viene de cache)...")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for s, res in zip(stale, pool.map(enrich_one, stale)):
                cache[s["id"]] = res
    ids = {s["id"] for s in stations}
    for old in [k for k in cache if k not in ids]:   # limpia radios que ya no existen
        del cache[old]

    for s in stations:
        e = cache.get(s["id"])
        if not e or not e.get("ok"):
            continue
        s["logo_url"] = e.get("logo_url") or s["logo_url"]
        s["cover_url"] = e.get("cover_url") or s.get("cover_url", "")
        s["description"] = s["description"] or e.get("description", "")
        s["color"] = e.get("color") or s["color"]
        s["links"] = {**e.get("links", {}), **s.get("links", {})}
        s["website"] = e.get("website") or s.get("website", "")
    return cache
