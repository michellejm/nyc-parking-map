"""
Build a color-coded GeoJSON of NYC alternate-side-parking (ASP) rules for a
bounding box, by:
  1. fetching DOT's ASP sign inventory (points, NY State Plane ft)
  2. converting to lon/lat and parsing each sign's rule text
  3. grouping signs into block faces (on_street + cross streets + side)
  4. snapping each block face to the nearest matching NYC Street Centerline
     (CSCL) segment
  5. offsetting a line to the correct side of the street and colored by
     schedule
"""
import json
import math
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict

from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points

sys.path.insert(0, "pipeline")
from rules import parse_sign_description, schedule_label  # noqa: E402

SOCRATA_BASE = "https://data.cityofnewyork.us/resource"
ASP_SIGNS_RESOURCE = "2x64-6f34"
CSCL_RESOURCE = "inkn-q76z"

XY_TO_LONLAT = Transformer.from_crs("EPSG:2263", "EPSG:4326", always_xy=True)

SUFFIX_MAP = {
    "STREET": "ST", "AVENUE": "AVE", "BOULEVARD": "BLVD", "PARKWAY": "PKWY",
    "PLACE": "PL", "ROAD": "RD", "DRIVE": "DR", "LANE": "LN", "COURT": "CT",
    "TERRACE": "TER", "EXPRESSWAY": "EXPY", "CIRCLE": "CIR", "HIGHWAY": "HWY",
    "SQUARE": "SQ", "BRIDGE": "BR", "PROMENADE": "PROM",
}


def normalize_street(name):
    name = name.upper().strip()
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"\b(\d+)(ST|ND|RD|TH)\b", r"\1", name)  # strip ordinals
    words = name.split(" ")
    words = [SUFFIX_MAP.get(w, w) for w in words]
    return " ".join(words)


def socrata_get(resource, params):
    url = f"{SOCRATA_BASE}/{resource}.json?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url) as r:
        return json.load(r)


def fetch_cscl_segments(bbox):
    lat_min, lat_max, lon_min, lon_max = bbox
    where = f"within_box(the_geom, {lat_max}, {lon_min}, {lat_min}, {lon_max})"
    rows = socrata_get(CSCL_RESOURCE, {
        "$where": where,
        "$select": "physicalid,full_street_name,the_geom",
        "$limit": 10000,
    })
    segments = []
    for row in rows:
        geom = row.get("the_geom")
        if not geom:
            continue
        name = normalize_street(row["full_street_name"])
        coord_lists = (
            geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]
        )
        for coords in coord_lists:
            if len(coords) < 2:
                continue
            segments.append({
                "physicalid": row["physicalid"],
                "name": name,
                "line": LineString(coords),
            })
    return segments


def fetch_asp_signs(borough):
    page_size = 50000
    offset = 0
    all_rows = []
    while True:
        rows = socrata_get(ASP_SIGNS_RESOURCE, {
            "borough": borough,
            "$select": "on_street,from_street,to_street,side_of_street,sign_description,"
                       "sign_x_coord,sign_y_coord",
            "$limit": page_size,
            "$offset": offset,
            "$order": ":id",
        })
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return all_rows


def in_bbox(lon, lat, bbox):
    lat_min, lat_max, lon_min, lon_max = bbox
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def build_block_faces(signs, bbox):
    groups = defaultdict(lambda: {"points": [], "schedules": set(), "meta": None})
    for s in signs:
        x, y = s.get("sign_x_coord"), s.get("sign_y_coord")
        if not x or not y:
            continue
        lon, lat = XY_TO_LONLAT.transform(float(x), float(y))
        if not in_bbox(lon, lat, bbox):
            continue
        schedule = parse_sign_description(s["sign_description"])
        if not schedule:
            continue
        on = normalize_street(s["on_street"])
        cross = frozenset([
            normalize_street(s.get("from_street") or ""),
            normalize_street(s.get("to_street") or ""),
        ])
        side = s["side_of_street"]
        key = (on, cross, side)
        g = groups[key]
        g["points"].append((lon, lat))
        g["schedules"].add((tuple(schedule["days"]), schedule["start_min"], schedule["end_min"]))
        g["meta"] = {"on_street": s["on_street"], "from_street": s.get("from_street"),
                      "to_street": s.get("to_street"), "side": side}
    return groups


def nearest_segment(point_lon, point_lat, street_name, segments_by_name, max_dist_deg=0.0025):
    pt = Point(point_lon, point_lat)
    candidates = segments_by_name.get(street_name, [])
    pool = candidates if candidates else [seg for segs in segments_by_name.values() for seg in segs]
    best, best_dist = None, None
    for seg in pool:
        d = pt.distance(seg["line"])
        if best_dist is None or d < best_dist:
            best, best_dist = seg, d
    if best is None or best_dist > max_dist_deg:
        return None
    return best


def local_meters_per_degree(lat):
    lat_rad = math.radians(lat)
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(lat_rad)
    return m_per_deg_lon, m_per_deg_lat


def compass_of_vector(dx_m, dy_m):
    bearing = (math.degrees(math.atan2(dx_m, dy_m)) + 360) % 360
    if bearing >= 315 or bearing < 45:
        return "N"
    if bearing < 135:
        return "E"
    if bearing < 225:
        return "S"
    return "W"


# Zones are the DSNY pickup-day *pairs* a block belongs to: one side is swept on
# the first day, the opposite side on the second. Coloring by zone (not by the
# single day a given side happens to carry) means both sides of one block read
# as the same color, matching how residents actually think about "their street."
CANONICAL_PAIRS = {
    "MON_TUE": frozenset({"MON", "TUE"}),
    "WED_THU": frozenset({"WED", "THU"}),
    "WED_FRI": frozenset({"WED", "FRI"}),
    "THU_FRI": frozenset({"THU", "FRI"}),
    "MON_THU": frozenset({"MON", "THU"}),
}
DAILY_SET = frozenset({"MON", "TUE", "WED", "THU", "FRI", "SAT"})

ZONE_COLORS = {
    "MON_TUE": "#2a78d6",
    "WED_THU": "#e34948",
    "WED_FRI": "#eb6834",
    "THU_FRI": "#4a3aa7",
    "DAILY": "#e87ba4",
    "MON_THU": "#eda100",
    "OTHER": "#898781",
}
ZONE_LABELS = {
    "MON_TUE": "Mon/Tue", "WED_THU": "Wed/Thu", "WED_FRI": "Wed/Fri",
    "THU_FRI": "Thu/Fri", "DAILY": "Daily (except Sun)", "MON_THU": "Mon/Thu",
    "OTHER": "Other",
}


def classify_zone(days):
    days = frozenset(days)
    if days == DAILY_SET:
        return "DAILY"
    for name, pair in CANONICAL_PAIRS.items():
        if days == pair:
            return name
    if len(days) == 1:
        day = next(iter(days))
        matches = [name for name, pair in CANONICAL_PAIRS.items() if day in pair]
        if len(matches) == 1:
            return matches[0]
    return "OTHER"


def offset_line_for_side(line, side, offset_m=3.5):
    coords = list(line.coords)
    lat0 = coords[len(coords) // 2][1]
    m_per_deg_lon, m_per_deg_lat = local_meters_per_degree(lat0)

    offset_coords = []
    n = len(coords)
    for i, (lon, lat) in enumerate(coords):
        if i == 0:
            (lon2, lat2) = coords[1]
            (lon1, lat1) = (lon, lat)
        elif i == n - 1:
            (lon2, lat2) = (lon, lat)
            (lon1, lat1) = coords[i - 1]
        else:
            (lon1, lat1) = coords[i - 1]
            (lon2, lat2) = coords[i + 1]
        dx_m = (lon2 - lon1) * m_per_deg_lon
        dy_m = (lat2 - lat1) * m_per_deg_lat
        length = math.hypot(dx_m, dy_m) or 1.0
        perp_dx, perp_dy = -dy_m / length, dx_m / length  # rotate +90
        if compass_of_vector(perp_dx, perp_dy) != side:
            perp_dx, perp_dy = -perp_dx, -perp_dy
        offset_coords.append((
            lon + (perp_dx * offset_m) / m_per_deg_lon,
            lat + (perp_dy * offset_m) / m_per_deg_lat,
        ))
    return offset_coords


def build_geojson(bbox, borough, area_name):
    segments = fetch_cscl_segments(bbox)
    segments_by_name = defaultdict(list)
    for seg in segments:
        segments_by_name[seg["name"]].append(seg)

    signs = fetch_asp_signs(borough)
    groups = build_block_faces(signs, bbox)

    block_days = defaultdict(set)
    for (on_street, cross, side), g in groups.items():
        for days, s, e in g["schedules"]:
            block_days[(on_street, cross)].update(days)
    block_zone = {k: classify_zone(v) for k, v in block_days.items()}

    features = []
    unmatched = 0
    for (on_street, cross, side), g in groups.items():
        lon = sum(p[0] for p in g["points"]) / len(g["points"])
        lat = sum(p[1] for p in g["points"]) / len(g["points"])
        seg = nearest_segment(lon, lat, on_street, segments_by_name)
        if seg is None:
            unmatched += 1
            continue

        zone = block_zone[(on_street, cross)]
        color = ZONE_COLORS[zone]
        labels = [schedule_label({"days": list(d), "start_min": s, "end_min": e})
                  for d, s, e in sorted(g["schedules"])]
        all_days = sorted({d for sched in g["schedules"] for d in sched[0]},
                           key=lambda d: ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"].index(d))

        offset_coords = offset_line_for_side(seg["line"], side)
        meta = g["meta"]
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": offset_coords},
            "properties": {
                "street": meta["on_street"],
                "from": meta["from_street"],
                "to": meta["to_street"],
                "side": side,
                "zone": zone,
                "zone_label": ZONE_LABELS[zone],
                "schedules": labels,
                "all_days": all_days,
                "color": color,
            },
        })

    print(f"{area_name}: {len(features)} block-face segments, {unmatched} unmatched", file=sys.stderr)
    return {"type": "FeatureCollection", "features": features}


if __name__ == "__main__":
    # Bay Ridge + Fort Hamilton, south to the Verrazzano-Narrows Bridge / Army base.
    BAY_RIDGE_BBOX = (40.596, 40.643, -74.045, -74.000)  # lat_min, lat_max, lon_min, lon_max
    fc = build_geojson(BAY_RIDGE_BBOX, "Brooklyn", "Bay Ridge / Fort Hamilton")
    with open("data/bayridge.geojson", "w") as f:
        json.dump(fc, f)
    print("Wrote data/bayridge.geojson", file=sys.stderr)
