#!/usr/bin/env python3
"""Genera data/stations.json con las radios de Bolivia.

Fuente: Radio Browser (https://www.radio-browser.info, API gratuita).
Solo usa la libreria estandar (Python 3.9+).

    python update_stations.py            # actualiza data/stations.json
    python update_stations.py --dry-run  # muestra el resultado sin escribir
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

import enrich
import sources_garden

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "stations.json"
OVERRIDES = ROOT / "data" / "overrides.json"
CACHE = ROOT / "data" / "enrichment.json"

SERVERS = [
    "https://de1.api.radio-browser.info",
    "https://de2.api.radio-browser.info",
    "https://fi1.api.radio-browser.info",
    "https://at1.api.radio-browser.info",
    "https://nl1.api.radio-browser.info",
]
USER_AGENT = "cron-radios-bolivia/1.0 (+https://github.com/GustavoMix/cron-radios-bolivia)"
HTTPS_ONLY = False       # la app de Tizen (config.xml access origin=*) reproduce tambien http; poner True para exigir https
ALLOWED_CODECS = {"", "MP3", "AAC", "AAC+", "UNKNOWN"}  # lo que reproduce Tizen (HLS aparte)
MIN_STATIONS = 10        # por debajo de esto se considera que la API fallo
MAX_DROP_RATIO = 0.5     # si la lista nueva es < 50% de la anterior, no se sobrescribe
COLORS = ["#e63946", "#f4a300", "#2a9d8f", "#d63384", "#3a86ff", "#06a77d",
          "#8338ec", "#e76f51", "#fb5607", "#118ab2", "#7b2cbf", "#ef476f"]

# departamento -> palabras que lo identifican (minusculas, sin tildes)
DEPARTMENTS = {
    "La Paz": ["la paz", "el alto", "copacabana", "achacachi", "viacha", "caranavi", "chulumani", "coroico", "desaguadero"],
    "Santa Cruz": ["santa cruz", "montero", "warnes", "camiri", "san ignacio", "vallegrande", "pampagrande", "guarayos", "yapacani", "cotoca", "la guardia", "san julian", "robore", "puerto suarez"],
    "Cochabamba": ["cochabamba", "quillacollo", "sacaba", "chapare", "cercado", "punata", "cliza", "villa tunari", "colcapirhua", "tiquipaya"],
    "Oruro": ["oruro", "huanuni", "challapata", "caracollo"],
    "Potosí": ["potosi", "uyuni", "llallagua", "tupiza", "villazon", "cotagaita", "betanzos"],
    "Chuquisaca": ["chuquisaca", "sucre", "monteagudo"],
    "Tarija": ["tarija", "traija", "yacuiba", "villamontes", "villa montes", "bermejo", "entre rios"],
    "Beni": ["beni", "trinidad", "riberalta", "guayaramerin", "rurrenabaque", "san borja", "santa ana del yacuma", "reyes"],
    "Pando": ["pando", "cobija"],
}
CAPITALS = {"La Paz": "La Paz", "Santa Cruz": "Santa Cruz", "Cochabamba": "Cochabamba",
            "Oruro": "Oruro", "Potosí": "Potosí", "Chuquisaca": "Sucre",
            "Tarija": "Tarija", "Beni": "Trinidad", "Pando": "Cobija"}


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(text or "").lower()).strip()


def fetch_json(path: str, retries: int = 2):
    """Prueba cada servidor de Radio Browser hasta que uno responda."""
    last_error: Exception | None = None
    for base in SERVERS:
        for attempt in range(retries):
            try:
                req = urllib.request.Request(base + path, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.load(resp)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                last_error = exc
                print(f"  aviso: {base} intento {attempt + 1} fallo: {exc}", file=sys.stderr)
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Ningun servidor de Radio Browser respondio: {last_error}")


def detect_department(*texts: str) -> str:
    haystack = " ".join(norm(t) for t in texts)
    for dept, words in DEPARTMENTS.items():
        if any(re.search(rf"\b{re.escape(w)}\b", haystack) for w in words):
            return dept
    return ""


def clean_city(state: str) -> str:
    city = re.sub(r"\s*[-,]\s*bolivia\s*$", "", state or "", flags=re.I).strip()
    return "" if norm(city) == "bolivia" else city


def detect_frequency(name: str) -> str:
    """Saca '93.3 FM' del nombre si lo trae (rango FM 87.5-108)."""
    m = re.search(r"(?<!\d)(\d{2,3})[.,](\d)(?!\d)", name)
    if m:
        mhz = float(f"{m.group(1)}.{m.group(2)}")
        if 87.5 <= mhz <= 108.0:
            return f"{mhz:.1f} FM"
    return ""


def clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", name or "").strip(" -_|")


def to_station(raw: dict) -> dict | None:
    url = (raw.get("url_resolved") or raw.get("url") or "").strip()
    codec = (raw.get("codec") or "").upper()
    name = clean_name(raw.get("name", ""))
    if not name or not raw.get("lastcheckok"):
        return None
    if not url.startswith(("https://", "http://")) or (HTTPS_ONLY and not url.startswith("https://")):
        return None
    if codec not in ALLOWED_CODECS and not raw.get("hls"):
        return None

    state = raw.get("state", "")
    dept = detect_department(state, name)
    city = clean_city(state) or CAPITALS.get(dept, "")
    tag = next((t.strip() for t in (raw.get("tags") or "").split(",") if t.strip()), "")
    uuid = raw.get("stationuuid") or hashlib.sha1(url.encode()).hexdigest()
    favicon = (raw.get("favicon") or "").strip()

    return {
        "id": uuid,
        "name": name,
        "city": city,
        "department": dept,
        "genre": (tag[:1].upper() + tag[1:]) if tag else "Variada",
        "frequency": detect_frequency(name),
        "stream_url": url,
        "secure": url.startswith("https://"),
        "logo_url": favicon if favicon.startswith("https://") else "",
        "cover_url": "",
        "color": COLORS[int(hashlib.md5(uuid.encode()).hexdigest(), 16) % len(COLORS)],
        "description": "",
        "is_featured": False,
        "website": (raw.get("homepage") or "").strip(),
        "links": {},
        "programs": [],
        "language": (raw.get("language") or "").strip(),
        "codec": codec,
        "bitrate": int(raw.get("bitrate") or 0),
        "votes": int(raw.get("votes") or 0),
    }


def name_key(name: str) -> str:
    """Nombre comparable: sin tildes, sin frecuencia ni palabras de relleno ('Radio X 93.3 FM' == 'X')."""
    n = re.sub(r"\d{2,3}[.,]\d\s*(fm|mhz)?", " ", norm(name))
    n = re.sub(r"\b(radio|fm|am|bolivia|online|en vivo|emisora|la|el|de|del)\b", " ", n)
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


FILL_FIELDS = ("city", "department", "frequency", "website", "logo_url")


def merge_dedupe(stations: list[dict]) -> list[dict]:
    """Une fuentes: si dos radios son la misma (mismo stream o mismo nombre y departamento
    compatible) se queda la de mas votos y se le rellenan los datos que le falten."""
    result: list[dict] = []
    by_stream: dict[str, dict] = {}
    by_name: dict[str, list[dict]] = {}
    for s in sorted(stations, key=lambda x: -x.get("votes", 0)):
        skey = s["stream_url"].lower().rstrip("/")
        nkey = name_key(s["name"])
        match = by_stream.get(skey)
        if not match and nkey:
            for cand in by_name.get(nkey, []):
                if not s.get("department") or not cand.get("department") or s["department"] == cand["department"]:
                    match = cand
                    break
        if match:
            for f in FILL_FIELDS:
                if not match.get(f) and s.get(f):
                    match[f] = s[f]
            continue
        result.append(s)
        by_stream[skey] = s
        if nkey:
            by_name.setdefault(nkey, []).append(s)
    return result


def from_garden(g: dict) -> dict:
    """Convierte una radio de radio.garden al mismo formato que las de Radio Browser."""
    name = clean_name(g["name"])
    place = g.get("place", "")
    dept = detect_department(place, name)
    url = g["stream"]
    return {
        "id": g["id"],
        "name": name,
        "city": place,
        "department": dept,
        "genre": "Variada",
        "frequency": detect_frequency(name),
        "stream_url": url,
        "secure": url.startswith("https://"),
        "logo_url": "",
        "cover_url": "",
        "color": COLORS[int(hashlib.md5(g["id"].encode()).hexdigest(), 16) % len(COLORS)],
        "description": "",
        "is_featured": False,
        "website": (g.get("website") or "").strip(),
        "links": {},
        "programs": [],
        "language": "",
        "codec": "",
        "bitrate": 0,
        "votes": 0,
    }


def apply_overrides(stations: list[dict], overrides: dict) -> list[dict]:
    exclude = {norm(str(x)) for x in overrides.get("exclude", [])}
    patch = {norm(k): v for k, v in overrides.get("patch", {}).items()}
    result = []
    for s in stations:
        if norm(s["id"]) in exclude or norm(s["name"]) in exclude:
            continue
        s.update(patch.get(norm(s["id"])) or patch.get(norm(s["name"])) or {})
        result.append(s)
    for extra in overrides.get("add", []):
        extra.setdefault("id", "manual-" + hashlib.sha1(extra["name"].encode()).hexdigest()[:10])
        for key, default in (("city", ""), ("department", ""), ("genre", "Variada"), ("frequency", ""),
                             ("logo_url", ""), ("cover_url", ""), ("color", COLORS[0]),
                             ("description", ""), ("is_featured", False), ("website", ""),
                             ("links", {}), ("programs", [])):
            extra.setdefault(key, default)
        result.append(extra)
    return result


def build(raw_list: list[dict], overrides: dict, cache: dict | None = None,
          extra: list[dict] | None = None) -> list[dict]:
    """raw_list: radios de Radio Browser. extra: radios ya normalizadas de otras fuentes."""
    stations = merge_dedupe([s for s in map(to_station, raw_list) if s] + list(extra or []))
    if cache is not None:                       # logo, portada, descripcion, color, redes
        enrich.enrich_all(stations, cache)
    stations = apply_overrides(stations, overrides)   # lo manual siempre gana
    for s in stations:
        s.setdefault("votes", 0)
    # ranking: mas votadas primero (desempata por nombre). `rank` 1 = la mas votada.
    stations.sort(key=lambda s: (-s["votes"], norm(s["name"])))
    for i, s in enumerate(stations, 1):
        s["rank"] = i
    # las marcadas a mano como destacadas (en overrides) van antes, sin cambiar su rank
    stations.sort(key=lambda s: not s.get("is_featured", False))
    return stations


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="no escribe el archivo")
    parser.add_argument("--no-enrich", action="store_true", help="no visita las webs de las radios")
    parser.add_argument("--no-garden", action="store_true", help="no usa radio.garden (solo Radio Browser)")
    args = parser.parse_args()

    print("Descargando radios de Bolivia...")
    raw = fetch_json("/json/stations/bycountrycodeexact/BO?hidebroken=true&order=votes&reverse=true")
    previous = load_json(OUT, [])
    extra: list[dict] = []
    if not args.no_garden:
        try:
            extra = [from_garden(g) for g in sources_garden.fetch_bolivia()]
        except Exception as exc:  # esta fuente no es oficial: si falla, se conserva lo ultimo bueno
            print(f"AVISO: radio.garden fallo ({exc}); se conservan sus radios anteriores.", file=sys.stderr)
            extra = [dict(s, votes=s.get("votes", 0)) for s in previous if str(s.get("id", "")).startswith("rg-")]
    cache = None if args.no_enrich else load_json(CACHE, {})
    stations = build(raw, load_json(OVERRIDES, {}), cache, extra)
    print(f"{len(raw)} radios en Radio Browser + {len(extra)} en radio.garden -> {len(stations)} validas")

    if len(stations) < MIN_STATIONS:
        print(f"ERROR: solo {len(stations)} radios (minimo {MIN_STATIONS}). No se sobrescribe.", file=sys.stderr)
        return 1
    if previous and len(stations) < len(previous) * MAX_DROP_RATIO:
        print(f"ERROR: la lista cae de {len(previous)} a {len(stations)}. No se sobrescribe.", file=sys.stderr)
        return 1

    if args.dry_run:
        print(json.dumps(stations[:3], ensure_ascii=False, indent=1))
        return 0
    OUT.parent.mkdir(exist_ok=True)
    if cache is not None:
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    OUT.write_text(json.dumps(stations, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Escrito {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
