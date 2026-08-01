"""
Download all external JS/CSS dependencies for offline use.
Run once, then app works fully offline.
"""
import urllib.request
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"

FILES = {
    # Leaflet
    "leaflet.js": "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js",
    "leaflet.css": "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.css",
    # jQuery
    "jquery.min.js": "https://code.jquery.com/jquery-3.7.1.min.js",
    # Bootstrap 5
    "bootstrap.min.css": "https://cdn.jsdelivr.net/npm/bootstrap@5.2.2/dist/css/bootstrap.min.css",
    "bootstrap.bundle.min.js": "https://cdn.jsdelivr.net/npm/bootstrap@5.2.2/dist/js/bootstrap.bundle.min.js",
    # Font Awesome
    "fontawesome.min.css": "https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.2.0/css/all.min.css",
    # Leaflet Awesome Markers
    "leaflet.awesome-markers.css": "https://cdnjs.cloudflare.com/ajax/libs/Leaflet.awesome-markers/2.0.2/leaflet.awesome-markers.css",
    "leaflet.awesome-markers.js": "https://cdnjs.cloudflare.com/ajax/libs/Leaflet.awesome-markers/2.0.2/leaflet.awesome-markers.js",
    # Bootstrap Glyphicons (v3 fallback)
    "bootstrap-glyphicons.css": "https://netdna.bootstrapcdn.com/bootstrap/3.0.0/css/bootstrap-glyphicons.css",
    # Folium rotate plugin
    "leaflet.awesome.rotate.min.css": "https://cdn.jsdelivr.net/gh/python-visualization/folium/folium/templates/leaflet.awesome.rotate.min.css",
}

STATIC.mkdir(parents=True, exist_ok=True)

for name, url in FILES.items():
    path = STATIC / name
    if path.exists():
        print(f"  [SKIP] {name} (exists)")
        continue
    print(f"  [DOWNLOAD] {name} <- {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            path.write_bytes(resp.read())
        print(f"    -> OK ({path.stat().st_size:,} bytes)")
    except Exception as e:
        print(f"    -> FAILED: {e}")

print(f"\nDone. Files in: {STATIC}")
