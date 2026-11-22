"""Place candidates on an India map from the free-text `city` field Crustdata returns.

The field is messy (post-office names, localities, several branches in one string), so this is a keyword lookup against
well-known city centroids. A candidate whose text matches no known place is NOT placed (we never guess); the UI reports
how many could not be placed. Coordinates are approximate city centres, and markers are jittered slightly so several
companies in one city stay visible: the map shows which city a company is in, not its street address.
"""
from __future__ import annotations

import hashlib
import json
import math

CITIES = {
    "Mumbai": (19.076, 72.878), "Navi Mumbai": (19.033, 73.030), "Thane": (19.218, 72.978), "Pune": (18.520, 73.857),
    "Bengaluru": (12.972, 77.594), "Hyderabad": (17.385, 78.487), "Chennai": (13.083, 80.270), "Kolkata": (22.573, 88.364),
    "Delhi": (28.614, 77.209), "Noida": (28.535, 77.391), "Greater Noida": (28.474, 77.504), "Gurugram": (28.459, 77.027),
    "Ghaziabad": (28.667, 77.449), "Ahmedabad": (23.023, 72.572), "Vadodara": (22.307, 73.181), "Surat": (21.170, 72.831),
    "Jaipur": (26.912, 75.787), "Lucknow": (26.847, 80.947), "Kanpur": (26.449, 80.331), "Chandigarh": (30.733, 76.779),
    "Indore": (22.720, 75.858), "Bhopal": (23.259, 77.413), "Nagpur": (21.146, 79.088), "Raipur": (21.251, 81.630),
    "Thiruvananthapuram": (8.524, 76.936), "Kochi": (9.931, 76.267), "Coimbatore": (11.017, 76.956), "Madurai": (9.925, 78.120),
    "Pudukkottai": (10.380, 78.820), "Rewari": (28.199, 76.619), "Jalandhar": (31.326, 75.576), "Solapur": (17.660, 75.906),
    "Bharatpur": (27.217, 77.489), "Gonda": (27.134, 81.962), "Jind": (29.316, 76.315), "Yamunanagar": (30.130, 77.289),
    "Visakhapatnam": (17.687, 83.219), "Bhubaneswar": (20.296, 85.824), "Patna": (25.594, 85.137), "Mysuru": (12.296, 76.639),
    "Kolhapur": (16.705, 74.243), "Nashik": (19.998, 73.790), "Mohali": (30.704, 76.717), "Panaji": (15.490, 73.828),
}

# (lower-case text to look for, city). Order matters: specific names first.
KEYWORDS = [
    ("navi mumbai", "Navi Mumbai"), ("belapur", "Navi Mumbai"), ("millenium business park", "Navi Mumbai"), ("vashi", "Navi Mumbai"),
    ("greater noida", "Greater Noida"), ("noida", "Noida"), ("gurugram", "Gurugram"), ("gurgaon", "Gurugram"),
    ("ghaziabad", "Ghaziabad"), ("mumbai", "Mumbai"), ("powai", "Mumbai"), ("sakinaka", "Mumbai"), ("kandivali", "Mumbai"),
    ("charkop", "Mumbai"), ("ghatkopar", "Mumbai"), ("andheri", "Mumbai"), ("thane", "Thane"),
    ("pimpri", "Pune"), ("chinchwad", "Pune"), ("deccan gymkhana", "Pune"), ("baner", "Pune"), ("lohogaon", "Pune"), ("pune", "Pune"),
    ("bengaluru", "Bengaluru"), ("bangalore", "Bengaluru"), ("koramangala", "Bengaluru"), ("bannerghatta", "Bengaluru"),
    ("rajarajeshwarinagar", "Bengaluru"), ("r t nagar", "Bengaluru"), ("carmelram", "Bengaluru"),
    ("hyderabad", "Hyderabad"), ("gachibowli", "Hyderabad"), ("kondapur", "Hyderabad"), ("secunderabad", "Hyderabad"),
    ("chennai", "Chennai"), ("guindy", "Chennai"), ("urapakkam", "Chennai"), ("adambakkam", "Chennai"),
    ("kolkata", "Kolkata"), ("park street", "Kolkata"), ("elliot road", "Kolkata"), ("new delhi", "Delhi"), ("delhi", "Delhi"),
    ("ahmedabad", "Ahmedabad"), ("ellisbridge", "Ahmedabad"), ("thaltej", "Ahmedabad"), ("bodakdev", "Ahmedabad"),
    ("vadodara", "Vadodara"), ("surat", "Surat"), ("jaipur", "Jaipur"), ("lucknow", "Lucknow"), ("kanpur", "Kanpur"),
    ("chandigarh", "Chandigarh"), ("mohali", "Mohali"), ("indore", "Indore"), ("bhopal", "Bhopal"), ("nagpur", "Nagpur"),
    ("raipur", "Raipur"), ("thiruvananthapuram", "Thiruvananthapuram"), ("trivandrum", "Thiruvananthapuram"),
    ("ernakulam", "Kochi"), ("kochi", "Kochi"), ("cochin", "Kochi"), ("maradu", "Kochi"), ("brahmapuram", "Kochi"),
    ("coimbatore", "Coimbatore"), ("madurai", "Madurai"), ("pudukkottai", "Pudukkottai"), ("pudukottai", "Pudukkottai"),
    ("rewari", "Rewari"), ("jalandhar", "Jalandhar"), ("solapur", "Solapur"), ("bharatpur", "Bharatpur"), ("gonda", "Gonda"),
    ("jind", "Jind"), ("yamunanagar", "Yamunanagar"), ("visakhapatnam", "Visakhapatnam"), ("bhubaneswar", "Bhubaneswar"),
    ("patna", "Patna"), ("mysuru", "Mysuru"), ("mysore", "Mysuru"), ("kolhapur", "Kolhapur"), ("nashik", "Nashik"),
    ("panaji", "Panaji"),
]


def locate(text: str | None):
    """Return (city, lat, lon) or None. Never guesses: no keyword match means not placed."""
    if not text:
        return None
    low = text.lower()
    for kw, city in KEYWORDS:
        if kw in low:
            lat, lon = CITIES[city]
            return city, lat, lon
    return None


def _jitter(key: str, radius: float) -> tuple[float, float]:
    h = int(hashlib.md5(key.encode()).hexdigest()[:8], 16)
    ang = (h % 3600) / 3600 * 2 * math.pi
    r = radius * (0.35 + 0.65 * (((h >> 12) % 1000) / 1000))
    return r * math.sin(ang), r * math.cos(ang)


def build_points(ranked: list[dict], candidates: list[dict], colors: dict, rec_key) -> tuple[list[dict], int, int]:
    """Points for the map. Returns (points, placed_count, unplaced_count). Ranked partners are drawn over candidates."""
    pts, placed, unplaced = [], 0, 0
    ranked_ids = {str(p["company"]["id"]) for p in ranked}
    for c in candidates:
        if str(c.get("id")) in ranked_ids:
            continue
        loc = locate(c.get("city"))
        if not loc:
            unplaced += 1
            continue
        d_lat, d_lon = _jitter(str(c.get("id")), 0.22)
        pts.append({"kind": "candidate", "name": c.get("name"), "city": loc[0], "lat": loc[1] + d_lat, "lon": loc[2] + d_lon})
        placed += 1
    for i, p in enumerate(ranked, 1):
        co = p["company"]
        loc = locate(co.get("city"))
        if not loc:
            unplaced += 1
            continue
        d_lat, d_lon = _jitter("r" + str(co.get("id")), 0.12)
        key = rec_key(p.get("recommendation"))
        pts.append({"kind": "ranked", "name": co.get("name"), "city": loc[0], "lat": loc[1] + d_lat, "lon": loc[2] + d_lon,
                    "rank": i, "fit": (p.get("fit") or {}).get("score"), "rec": p.get("recommendation"), "color": colors.get(key, "#64748B")})
        placed += 1
    return pts, placed, unplaced


def map_html(points: list[dict], height: int = 430) -> str:
    """Self-contained Leaflet map (OpenStreetMap tiles, darkened with a CSS filter). Needs internet for the tiles and the Leaflet CDN."""
    data = json.dumps(points)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#m{{margin:0;height:100%;background:#0b1020}}
.leaflet-container{{font-family:Inter,system-ui,sans-serif;background:#0b1020}}
.dark-tiles{{filter:invert(1) hue-rotate(195deg) saturate(.55) brightness(.92) contrast(.92)}}
.leaflet-control-attribution{{background:#0b1020aa!important;color:#6b7fae!important}} .leaflet-control-attribution a{{color:#8fa3c8!important}}
.tip b{{color:#e5edff}} .tip{{font-size:12px;line-height:1.35}}
.leaflet-tooltip{{background:#121a30;color:#c9d6f2;border:1px solid #2a3a60;border-radius:8px;box-shadow:none}}
.leaflet-tooltip-top:before{{border-top-color:#2a3a60}}
.legend{{position:absolute;z-index:999;right:10px;bottom:10px;background:#121a30e6;border:1px solid #2a3a60;border-radius:10px;
padding:8px 10px;color:#c9d6f2;font:11px Inter,system-ui,sans-serif}}
.legend i{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;vertical-align:middle}}</style></head>
<body><div id="m"></div><div class="legend" id="lg"></div>
<script>
var pts={data};
var map=L.map('m',{{zoomControl:true,attributionControl:true,minZoom:3,maxZoom:10,scrollWheelZoom:false}});
map.fitBounds([[6.5,67.5],[36.0,98.0]]);
L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
  {{attribution:'&copy; OpenStreetMap contributors',maxZoom:19,className:'dark-tiles'}}).addTo(map);
var legend={{}};
pts.filter(function(p){{return p.kind==='candidate'}}).forEach(function(p){{
  L.circleMarker([p.lat,p.lon],{{radius:4,color:'#6b7fae',weight:0,fillColor:'#6b7fae',fillOpacity:.55}})
   .bindTooltip('<div class="tip"><b>'+p.name+'</b><br>'+p.city+' &middot; discovered, not investigated</div>').addTo(map);}});
pts.filter(function(p){{return p.kind==='ranked'}}).forEach(function(p){{
  legend[p.rec]=p.color;
  L.circleMarker([p.lat,p.lon],{{radius:15,color:p.color,weight:0,fillColor:p.color,fillOpacity:.18}}).addTo(map);
  L.circleMarker([p.lat,p.lon],{{radius:9,color:'#0b1020',weight:2,fillColor:p.color,fillOpacity:1}})
   .bindTooltip('<div class="tip"><b>#'+p.rank+' '+p.name+'</b><br>'+p.city+' &middot; fit '+p.fit+'<br>'+p.rec+'</div>').addTo(map);}});
var lg='<div><i style="background:#6b7fae"></i>Discovered, not investigated</div>';
Object.keys(legend).forEach(function(k){{lg+='<div><i style="background:'+legend[k]+'"></i>'+k+'</div>'}});
document.getElementById('lg').innerHTML=lg;
</script></body></html>"""
