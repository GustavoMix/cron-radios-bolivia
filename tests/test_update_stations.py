import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import update_stations as u  # noqa: E402


def raw(**kw):
    base = {"stationuuid": "id1", "name": "Radio Prueba", "url_resolved": "https://x.com/s",
            "codec": "MP3", "lastcheckok": 1, "state": "", "tags": "", "favicon": "", "votes": 1}
    base.update(kw)
    return base


class Tests(unittest.TestCase):
    def test_descarta_http_caidas_y_codec(self):
        self.assertIsNone(u.to_station(raw(url_resolved="http://x.com/s")))
        self.assertIsNone(u.to_station(raw(lastcheckok=0)))
        self.assertIsNone(u.to_station(raw(codec="OGG")))
        self.assertIsNotNone(u.to_station(raw(codec="OGG", hls=1)))

    def test_departamento_y_ciudad(self):
        s = u.to_station(raw(state="Cochabamba - Bolivia"))
        self.assertEqual((s["city"], s["department"]), ("Cochabamba", "Cochabamba"))
        s = u.to_station(raw(name="Radio Potosí FM"))
        self.assertEqual((s["city"], s["department"]), ("Potosí", "Potosí"))
        s = u.to_station(raw(state="Bolivia"))
        self.assertEqual(s["city"], "")

    def test_frecuencia(self):
        self.assertEqual(u.detect_frequency("Radio Fides 93.3 FM"), "93.3 FM")
        self.assertEqual(u.detect_frequency("Radio 2000"), "")
        self.assertEqual(u.detect_frequency("Radio 12.5"), "")

    def test_dedupe_y_overrides(self):
        a = raw(stationuuid="a", name="Radio A", url_resolved="https://x.com/1", votes=1)
        b = raw(stationuuid="b", name="Otra", url_resolved="https://x.com/1/", votes=9)
        c = raw(stationuuid="c", name="Radio C", url_resolved="https://x.com/3")
        out = u.build([a, b, c], {"exclude": ["Radio C"],
                                  "add": [{"name": "Manual", "stream_url": "https://m.com/s"}]})
        self.assertEqual(sorted(s["name"] for s in out), ["Manual", "Otra"])
        self.assertTrue(all("votes" not in s for s in out))


class EnrichTests(unittest.TestCase):
    HTML = """<html><head>
    <meta property="og:image" content="/img/portada.jpg">
    <meta property="og:description" content="  La radio   de la gente. """ + "x" * 300 + """ ">
    <meta name="theme-color" content="#C0392B">
    <link rel="icon" href="/favicon.ico">
    <link rel="apple-touch-icon" sizes="180x180" href="http://radio.bo/logo.png">
    </head><body>
    <a href="https://www.facebook.com/radiox">fb</a>
    <a href="https://www.facebook.com/sharer/sharer.php?u=1">compartir</a>
    <a href="https://instagram.com/">home</a>
    <a href="https://wa.me/59170000000">wsp</a>
    </body></html>"""

    def test_parse_page(self):
        import enrich
        r = enrich.parse_page(self.HTML, "https://radio.bo/")
        self.assertEqual(r["logo_candidates"][0], "https://radio.bo/logo.png")   # apple-touch primero, http->https
        self.assertNotIn("https://radio.bo/favicon.ico", r["logo_candidates"])   # .ico descartado
        self.assertEqual(r["cover_url"], "https://radio.bo/img/portada.jpg")
        self.assertEqual(r["color"], "#c0392b")
        self.assertTrue(r["description"].startswith("La radio de la gente."))
        self.assertLessEqual(len(r["description"]), 224)
        self.assertEqual(r["links"], {"facebook": "https://www.facebook.com/radiox",
                                      "whatsapp": "https://wa.me/59170000000"})

    def test_color_y_cache(self):
        import enrich
        self.assertEqual(enrich.parse_color("#fff"), "")        # blanco: se descarta
        self.assertEqual(enrich.parse_color("#000000"), "")     # negro: se descarta
        self.assertEqual(enrich.parse_color("#e63"), "#ee6633")
        now = 1_000_000
        self.assertTrue(enrich.is_fresh({"checked": now - 86400, "ok": True}, now))
        self.assertFalse(enrich.is_fresh({"checked": now - 8 * 86400, "ok": False}, now))
        self.assertFalse(enrich.is_fresh(None, now))


if __name__ == "__main__":
    unittest.main()
