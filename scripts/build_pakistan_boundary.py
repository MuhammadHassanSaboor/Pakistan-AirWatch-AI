"""Build the Pakistan outline the map draws, from Natural Earth.

What it produces
----------------
    frontend/src/data/pakistan-boundary.json
        One outline of Pakistan as the Government of Pakistan's
        official map shows it: the admin-0 country polygon merged with
        Azad Jammu & Kashmir and Gilgit-Baltistan, so the north has a
        single continuous national border and no internal seams.

    frontend/src/data/map-labels.json
        Map labels placed by coordinate. Currently one: Indian Occupied
        Kashmir, marked by name only -- no outline, no fill.

Why the union matters
---------------------
Natural Earth keeps Azad Kashmir and Gilgit-Baltistan in its
*disputed areas* file, separate from the Pakistan country polygon.
Drawing the three as three strokes puts black lines through the middle
of the country where they touch, which is exactly what a national
border must not do. Dissolving them into one geometry first means the
stroke follows only the outer edge.

Why not hand-typed coordinates
------------------------------
A boundary drawn from memory is wrong in a way no reviewer can check,
and on this subject that is not a cosmetic defect. Natural Earth is
public domain (CC0), so the geometry is both citable and free to use.

Running it
----------
    pip install shapely        # only this script needs it
    python scripts/build_pakistan_boundary.py

The outputs are committed, so the frontend build never touches the
network.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
COUNTRIES = BASE + "ne_10m_admin_0_countries.geojson"
DISPUTED = BASE + "ne_10m_admin_0_disputed_areas.geojson"

DATA = Path(__file__).resolve().parents[1] / "frontend/src/data"

# Natural Earth BRK_NAMEs dissolved into the single Pakistan landmass.
#
# The whole of Jammu & Kashmir is included, which is what makes the
# north read as one country with one border rather than a country with
# a separate piece floating beside it. Siachen is in the list because
# leaving it out punches a hole between Gilgit-Baltistan and Jammu &
# Kashmir, and a hole in a national outline looks like a rendering bug.
# Aksai Chin and the Shaksam Valley are deliberately NOT included:
# they are Chinese-administered.
PAKISTAN_PARTS = {
    "Azad Kashmir",
    "Gilgit-Baltistan",
    "Jammu and Kashmir",
    "Siachen Glacier",
}

# Named on the map. The area is inside the national outline and is not
# shaded or outlined separately -- the label is the only marking.
LABELLED = {"Jammu and Kashmir": "Indian Occupied Kashmir"}

PRECISION = 4
# Snaps near-identical vertices together before the union, so the
# shared Pakistan/Kashmir edges dissolve instead of leaving hairline
# slivers that would show up as stray marks along the border.
SNAP = 0.002


def fetch(url: str) -> dict:
    print(f"  {url.rsplit('/', 1)[-1]}")
    with urllib.request.urlopen(url, timeout=180) as response:
        return json.load(response)


def round_coords(node):
    if isinstance(node[0], int | float):
        return [round(float(c), PRECISION) for c in node]
    return [round_coords(child) for child in node]


def main() -> None:
    print("Downloading Natural Earth 10m:")
    countries = fetch(COUNTRIES)
    disputed = fetch(DISPUTED)

    pieces = []

    for feature in countries["features"]:
        if feature["properties"].get("ADM0_A3") == "PAK":
            pieces.append(shape(feature["geometry"]))

    labels = []
    for feature in disputed["features"]:
        name = feature["properties"].get("BRK_NAME")
        if name in PAKISTAN_PARTS:
            pieces.append(shape(feature["geometry"]))
        if name in LABELLED:
            bounds = shape(feature["geometry"]).bounds
            labels.append(
                {
                    "label": LABELLED[name],
                    # representative_point stays inside an awkward
                    # shape; a centroid can fall outside one.
                    "lat": round(
                        shape(feature["geometry"]).representative_point().y, 4
                    ),
                    "lon": round(
                        shape(feature["geometry"]).representative_point().x, 4
                    ),
                    "bounds": [round(b, 4) for b in bounds],
                }
            )

    if not pieces:
        raise SystemExit("Pakistan geometry not found in Natural Earth")
    if not labels:
        raise SystemExit("Jammu and Kashmir not found in Natural Earth")

    merged = unary_union([p.buffer(SNAP) for p in pieces]).buffer(-SNAP)
    merged = merged.simplify(0.004, preserve_topology=True)

    DATA.mkdir(parents=True, exist_ok=True)

    boundary = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "name": "Pakistan",
                    "note": (
                        "Admin-0 polygon dissolved with Azad Jammu & Kashmir, "
                        "Gilgit-Baltistan, Jammu & Kashmir and Siachen."
                    ),
                    "source": "Natural Earth 10m (public domain)",
                },
                "geometry": {
                    "type": mapping(merged)["type"],
                    "coordinates": round_coords(mapping(merged)["coordinates"]),
                },
            }
        ],
    }
    (DATA / "pakistan-boundary.json").write_text(json.dumps(boundary), encoding="utf-8")
    (DATA / "map-labels.json").write_text(json.dumps(labels), encoding="utf-8")

    size = (DATA / "pakistan-boundary.json").stat().st_size / 1024
    print(f"\npakistan-boundary.json  {size:.1f} KB  ({merged.geom_type})")
    print(f"  bounds {[round(b, 2) for b in merged.bounds]}")
    for entry in labels:
        print(f"map-labels.json  {entry['label']} at {entry['lat']}, {entry['lon']}")


if __name__ == "__main__":
    main()
