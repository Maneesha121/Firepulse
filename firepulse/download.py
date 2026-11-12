"""Download FIRMS hotspots in 10-day chunks (resumable cache). Needs FIRMS_MAP_KEY."""
import os, time, datetime as dt
import requests
from .config import RAW, SOURCES, EXTRA_SOURCES, BBOX, CHUNK_DAYS

BASE = "https://firms.modaps.eosdis.nasa.gov/api"


def _get(url, tries=4):
    for i in range(tries):
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 200:
                return r.text
            print("HTTP", r.status_code, r.text[:200])
        except requests.RequestException as e:
            print("request error:", e)
        time.sleep(5 * (i + 1))
    raise RuntimeError("giving up: " + url)


def availability(key):
    return _get(f"{BASE}/data_availability/csv/{key}/ALL")


def download(start, end, key=None, sources=None):
    key = key or os.environ.get("FIRMS_MAP_KEY", "")
    if not key:
        raise SystemExit("Set FIRMS_MAP_KEY (free key from the FIRMS website).")
    bbox = ",".join(map(str, BBOX))
    d0, d1 = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    failed = []
    for name in (sources or list(SOURCES.values()) + list(EXTRA_SOURCES)):
        folder = RAW / name
        folder.mkdir(parents=True, exist_ok=True)
        d = d0
        while d <= d1:
            n = min(CHUNK_DAYS, (d1 - d).days + 1)
            f = folder / f"{d}_{n}.csv"
            if not f.exists():
                txt = _get(f"{BASE}/area/csv/{key}/{name}/{bbox}/{n}/{d}")
                if not txt.startswith("latitude"):
                    # NOT cached: an error reply must never look like 'retrieved, zero detections' (retry on next run)
                    print("unexpected reply", name, d, txt[:150])
                    failed.append((name, str(d), txt[:80]))
                else:
                    f.write_text(txt)  # header-only reply = window retrieved with zero detections (coverage evidence)
                time.sleep(0.3)       # far below 5000 requests / 10 min
            d += dt.timedelta(days=n)
        print("downloaded", name)
    if failed:
        print(f"WARNING: {len(failed)} window(s) failed and were not cached; re-run to retry. First: {failed[0]}")
    return failed
