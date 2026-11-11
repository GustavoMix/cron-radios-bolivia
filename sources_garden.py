"""Segunda fuente: radio.garden (radios organizadas por ciudad).

OJO: es la API interna que usa su propia web, no una API publica documentada. Puede cambiar o
dejar de funcionar; por eso el cron nunca falla si esta fuente cae (conserva lo ultimo bueno).
Se hacen ~2 peticiones por radio, una vez al dia, con User-Agent identificado.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://radio.garden/api/ara/content"
USER_AGENT = "Mozilla/5.0 (compatible; cron-radios-bolivia/1.0; +https://github.com/GustavoMix/cron-radios-bolivia)"
TIMEOUT = 25


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # devolvemos el 302 en vez de seguirlo
        return None


def _get_json(url: str, retries: int = 2):
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last = exc
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"radio.garden: {url} -> {last}")


def resolve_stream(channel_id: str) -> str:
    """La URL /listen/<id>/channel.mp3 responde con un 302 al stream real: lo guardamos directo."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(f"{BASE}/listen/{channel_id}/channel.mp3", headers={"User-Agent": USER_AGENT})
    try:
        opener.open(req, timeout=TIMEOUT)
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location", "")
        if e.code in (301, 302, 303, 307, 308) and loc.startswith("http"):
            return loc
    except (urllib.error.URLError, TimeoutError, OSError):
        pass
    return ""


def _channel(item: dict, place_title: str) -> dict | None:
    page = item.get("page") or {}
    cid = (page.get("url") or "").rstrip("/").split("/")[-1]
    if not cid or not page.get("title"):
        return None
    info: dict = {}
    try:
        info = _get_json(f"{BASE}/channel/{cid}").get("data", {})
    except RuntimeError:
        pass
    stream = resolve_stream(cid)
    if not stream:
        return None
    return {"id": "rg-" + cid, "name": page["title"], "place": place_title,
            "website": info.get("website", ""), "stream": stream}


def fetch_bolivia(workers: int = 8) -> list[dict]:
    """Devuelve las radios de Bolivia: [{id, name, place, website, stream}]. Lanza RuntimeError si falla."""
    places = _get_json(f"{BASE}/places")["data"]["list"]
    bolivia = [p for p in places if p.get("country") == "Bolivia"]
    if not bolivia:
        raise RuntimeError("radio.garden: no hay lugares de Bolivia (¿cambio la API?)")

    jobs: list[tuple[dict, str]] = []
    for p in bolivia:
        try:
            items = _get_json(f"{BASE}/page/{p['id']}/channels")["data"]["content"][0]["items"]
        except (RuntimeError, KeyError, IndexError):
            continue
        jobs += [(it, p["title"]) for it in items]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        channels = list(pool.map(lambda j: _channel(*j), jobs))
    out = [c for c in channels if c]
    print(f"radio.garden: {len(jobs)} canales, {len(out)} con stream valido")
    return out
