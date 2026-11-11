# cron-radios-bolivia

Cron en GitHub Actions que cada día arma la lista de radios de Bolivia y la publica en
[`data/stations.json`](data/stations.json). Las apps (por ejemplo la de Tizen TV) solo leen ese archivo.

```
https://raw.githubusercontent.com/GustavoMix/cron-radios-bolivia/main/data/stations.json
```

## Qué hace
1. Baja las radios de Bolivia de [Radio Browser](https://www.radio-browser.info) (con varios servidores de respaldo).
2. Filtra: solo streams `https`, que estén en línea, con códec MP3/AAC/HLS, sin duplicados.
3. Normaliza: departamento, ciudad, frecuencia (si viene en el nombre), color y género.
4. Aplica tus ajustes de [`data/overrides.json`](data/overrides.json).
5. Hace commit solo si la lista cambió.

**Protecciones:** si la API devuelve menos de 10 radios o la lista cae a menos de la mitad de la anterior,
no se sobrescribe nada y el workflow falla (GitHub te avisa por correo).

## Enriquecimiento automático (`enrich.py`)
Para cada radio visita su sitio web y saca: **logo** (verificado que sea una imagen real), **portada**
(`og:image`), **descripción**, **color de marca** (`theme-color`) y **redes sociales** (Facebook, Instagram,
TikTok, YouTube, X, WhatsApp). Los resultados se guardan en `data/enrichment.json`: lo bueno se renueva cada
30 días y lo fallido cada 7, así el cron diario es rápido. Lo que no se encuentre queda vacío.

## Formato de cada radio
```json
{ "id": "...", "name": "Radio X", "city": "La Paz", "department": "La Paz", "genre": "Noticias",
  "frequency": "93.3 FM", "stream_url": "https://...", "logo_url": "https://...",
  "cover_url": "https://...", "color": "#e63946", "description": "...", "is_featured": false,
  "website": "https://...", "links": { "facebook": "...", "instagram": "...", "whatsapp": "..." },
  "programs": [ { "days": "Lun-Vie", "start": "06:00", "end": "09:00", "name": "Buenos días Bolivia" } ],
  "language": "español", "codec": "MP3", "bitrate": 128 }
```
`programs` (la programación) **no existe en ninguna API pública**: se llena a mano en `overrides.json`.

## Ajustes manuales (`data/overrides.json`)
```json
{
  "exclude": ["Radio que no quiero", "id-de-radio-browser"],
  "patch": {
    "Radio Fides": {
      "frequency": "93.3 FM", "is_featured": true, "city": "La Paz",
      "description": "Noticias y análisis las 24 horas.",
      "programs": [ { "days": "Lun-Vie", "start": "06:00", "end": "09:00", "name": "Buenos días Bolivia" } ]
    }
  },
  "add": [ { "name": "Radio Mia", "stream_url": "https://...", "city": "Sucre", "department": "Chuquisaca" } ]
}
```
`exclude` y `patch` aceptan el nombre o el id. Al guardar este archivo el workflow corre solo.

## Uso local
```bash
python update_stations.py --dry-run   # ver sin escribir
python update_stations.py             # actualizar data/stations.json
python -m unittest discover -s tests  # tests
```
Requiere Python 3.9+, sin dependencias.

## Puesta en marcha en GitHub
1. Repo **público** (para que `raw.githubusercontent.com` funcione).
2. Settings → Actions → General → Workflow permissions → **Read and write permissions**.
3. Actions → "Actualizar radios de Bolivia" → **Run workflow** para probar.
