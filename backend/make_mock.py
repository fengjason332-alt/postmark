"""Generate invented mock data for the frontend (data contract §6, schema 1.0).

Writes:
  frontend/public/mock/trips.json
  frontend/public/mock/stats.json
  frontend/public/mock/thumbs/<photo_id>_s.webp  (400px wide)
  frontend/public/mock/thumbs/<photo_id>_l.webp  (1600px long edge)

Everything here is made up. Nothing is read from data/.
Run from the repo root:  python backend/make_mock.py
"""

import hashlib
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
MOCK_DIR = REPO_ROOT / "frontend" / "public" / "mock"
THUMBS_DIR = MOCK_DIR / "thumbs"

SCHEMA_VERSION = "1.0"
# Fixed so that re-running the script gives byte-identical output.
GENERATED_AT = "2026-10-24T12:00:00-04:00"

HOME = {"city": "Boston", "country": "United States", "country_code": "US",
        "lat": 42.3601, "lng": -71.0589}

CITIES = {
    "city_newyork_us": {"name": "New York", "country": "United States", "country_code": "US",
                        "lat": 40.7128, "lng": -74.0060},
    "city_montreal_ca": {"name": "Montreal", "country": "Canada", "country_code": "CA",
                         "lat": 45.5019, "lng": -73.5674},
    "city_quebeccity_ca": {"name": "Quebec City", "country": "Canada", "country_code": "CA",
                           "lat": 46.8139, "lng": -71.2080},
}

PERSONAS = {"food": "Food Explorer", "city": "Urban Wanderer", "nature": "Nature Seeker",
            "architecture": "Architecture Buff"}

# Invented trips. Each photo: (taken_at, lat, lng, city_id, orientation, tags).
TRIPS = [
    {
        "slug": "newyork",
        "title": "New York",
        "color": (200, 85, 61),  # terracotta
        "photos": [
            ("2026-03-14T15:32:08-04:00", 40.7580, -73.9855, "city_newyork_us", "landscape", ["city"]),
            ("2026-03-14T19:05:41-04:00", 40.7306, -73.9866, "city_newyork_us", "portrait", ["food"]),
            ("2026-03-15T11:20:13-04:00", 40.7829, -73.9654, "city_newyork_us", "landscape", ["nature"]),
            ("2026-03-16T14:47:55-04:00", 40.7061, -73.9969, "city_newyork_us", "landscape", ["city", "architecture"]),
            ("2026-03-17T09:12:30-04:00", 40.7420, -74.0048, "city_newyork_us", "portrait", ["food"]),
        ],
    },
    {
        "slug": "montreal",
        "title": "Montreal",
        "color": (46, 111, 149),  # steel blue
        "photos": [
            ("2026-07-02T13:15:02-04:00", 45.5088, -73.5540, "city_montreal_ca", "landscape", ["architecture"]),
            ("2026-07-02T18:42:19-04:00", 45.5230, -73.5810, "city_montreal_ca", "portrait", ["food"]),
            ("2026-07-03T10:05:47-04:00", 45.5048, -73.5874, "city_montreal_ca", "landscape", ["nature"]),
            ("2026-07-04T12:30:11-04:00", 46.8123, -71.2046, "city_quebeccity_ca", "landscape", ["architecture", "city"]),
            ("2026-07-04T16:58:36-04:00", 46.8106, -71.2148, "city_quebeccity_ca", "portrait", ["food"]),
        ],
    },
]

SIZES = {"landscape": (1600, 1200), "portrait": (1200, 1600)}


def haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def photo_id(seed):
    # Real ids hash file content; mock ids hash a fixed string so they stay stable.
    return "p_" + hashlib.sha256(seed.encode()).hexdigest()[:10]


def tags_by_frequency(tag_lists):
    counts = Counter(t for tags in tag_lists for t in tags)
    return [t for t, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def write_thumbs(pid, size, color):
    w, h = size
    large = Image.new("RGB", (w, h), color)
    large.save(THUMBS_DIR / f"{pid}_l.webp", "WEBP", quality=80)
    small = Image.new("RGB", (400, round(400 * h / w)), color)
    small.save(THUMBS_DIR / f"{pid}_s.webp", "WEBP", quality=80)


def build_trip(index, spec):
    photos_in = sorted(spec["photos"], key=lambda p: p[0])
    photos = []
    for taken_at, lat, lng, city_id, orientation, tags in photos_in:
        pid = photo_id(f"mock/{spec['slug']}/{taken_at}")
        w, h = SIZES[orientation]
        write_thumbs(pid, (w, h), spec["color"])
        photos.append({
            "id": pid, "taken_at": taken_at, "date": taken_at[:10],
            "lat": round(lat, 4), "lng": round(lng, 4), "has_gps": True, "city_id": city_id,
            "thumb": f"thumbs/{pid}_s.webp", "full": f"thumbs/{pid}_l.webp",
            "width": w, "height": h, "tags": list(tags),
        })

    # Cities in order of first visit.
    cities = []
    for city_id in dict.fromkeys(p["city_id"] for p in photos if p["city_id"]):
        dates = [p["date"] for p in photos if p["city_id"] == city_id]
        c = CITIES[city_id]
        cities.append({
            "id": city_id, "name": c["name"], "country": c["country"], "country_code": c["country_code"],
            "lat": c["lat"], "lng": c["lng"], "arrive": min(dates), "leave": max(dates),
            "photo_count": len(dates),
        })

    # Distance = home -> each city in visit order (one way), as in the §6 example (Boston -> NYC = 306).
    distance = 0.0
    prev = (HOME["lat"], HOME["lng"])
    for c in cities:
        distance += haversine_km(*prev, c["lat"], c["lng"])
        prev = (c["lat"], c["lng"])

    start, end = photos[0]["date"], photos[-1]["date"]
    days = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days + 1
    return {
        "id": f"trip_{start.replace('-', '')}_{spec['slug']}",
        "index": index,
        "title": spec["title"],
        "start_date": start,
        "end_date": end,
        "days": days,
        "distance_km": round(distance),
        "photo_count": len(photos),
        "cover_photo_id": photos[0]["id"],
        "tags": tags_by_frequency(p["tags"] for p in photos),
        "cities": cities,
        "photos": photos,
    }


def summarize(trips):
    photos = [p for t in trips for p in t["photos"]]
    tag_counts = Counter(tag for p in photos for tag in p["tags"])
    top_tags = [[tag, round(n / len(photos), 2)]
                for tag, n in sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]] if photos else []
    return {
        "trips": len(trips),
        "cities": len({c["id"] for t in trips for c in t["cities"]}),
        "countries": len({c["country_code"] for t in trips for c in t["cities"]}),
        "days_away": sum(t["days"] for t in trips),
        "distance_km": sum(t["distance_km"] for t in trips),
        "photos_total": len(photos),
        "photos_with_gps": sum(p["has_gps"] for p in photos),
        "top_tags": top_tags,
        "persona": PERSONAS.get(top_tags[0][0]) if top_tags else None,
    }


def main():
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)

    specs = sorted(TRIPS, key=lambda s: min(p[0] for p in s["photos"]))
    trips = [build_trip(i, s) for i, s in enumerate(specs)]

    trips_json = {"schema_version": SCHEMA_VERSION, "generated_at": GENERATED_AT,
                  "home": HOME, "trips": trips}

    years = sorted({t["start_date"][:4] for t in trips})
    stats_json = {
        "schema_version": SCHEMA_VERSION,
        "all_time": summarize(trips),
        "by_year": {y: summarize([t for t in trips if t["start_date"][:4] == y]) for y in years},
    }

    for name, obj in (("trips.json", trips_json), ("stats.json", stats_json)):
        with open(MOCK_DIR / name, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
            f.write("\n")

    n_photos = sum(t["photo_count"] for t in trips)
    print(f"Wrote {len(trips)} trips, {n_photos} photos, {2 * n_photos} thumbnails to "
          f"{MOCK_DIR.relative_to(REPO_ROOT)}/")


if __name__ == "__main__":
    main()
