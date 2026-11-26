"""Build the Kashmir overlay the map draws, from Natural Earth.

Why a script and not hand-typed coordinates
-------------------------------------------
The map has to show the Kashmir region the way the Government of
Pakistan's official map does. Boundary geometry is the one thing in
this project that must never be approximated by hand: a plausible-
looking line drawn from memory is wrong in a way nobody can check, and
on this particular subject being wrong is not a cosmetic defect.

So the geometry comes from Natural Earth's 10m disputed-areas dataset,
which is public domain (CC0) and ships exactly the features needed,
each already carrying its administration note:

    Azad Kashmir       Admin. by Pakistan; Claimed by India
    Gilgit-Baltistan   Admin. by Pakistan; Claimed by India
    Jammu and Kashmir  Admin. by India;    Claimed by Pakistan
    Siachen Glacier    Claimed by Pakistan and India
    Aksai Chin         Admin. by China;    Claimed by India
    Shaksam Valley     Admin. by China

Running it
----------
    python scripts/build_kashmir_geojson.py

It downloads the source, keeps only those six features, tags each with
the role the UI styles it by, rounds coordinates to 4 decimal places
(~11 m, far finer than a country-scale map can show) and writes

    frontend/src/data/kashmir.json

Re-run it only to refresh from upstream; the output is committed so the
frontend build never depends on the network.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

SOURCE = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_10m_admin_0_disputed_areas.geojson"
)

OUT = Path(__file__).resolve().parents[1] / "frontend/src/data/kashmir.json"

# Natural Earth BRK_NAME -> (role, label shown on the map)
#
# Roles drive the styling, and they are the distinction that matters:
# `pakistan` is territory Pakistan administers and the official map
# shows as Pakistan; `occupied` is Indian-held Jammu & Kashmir, which
# that map marks as disputed; `china` is Chinese-administered.
WANTED: dict[str, tuple[str, str]] = {
    "Azad Kashmir": ("pakistan", "Azad Jammu & Kashmir"),
    "Gilgit-Baltistan": ("pakistan", "Gilgit-Baltistan"),
    "Jammu and Kashmir": (
        "occupied",
        "Indian Illegally Occupied Jammu & Kashmir",
    ),
    "Siachen Glacier": ("disputed", "Siachen Glacier"),
    "Aksai Chin": ("china", "Aksai Chin"),
    "Shaksam Valley": ("china", "Shaksam Valley"),
}

PRECISION = 4


def round_coords(node):
    """Round every coordinate pair, at whatever nesting depth."""
    if isinstance(node[0], int | float):
        return [round(float(c), PRECISION) for c in node]
    return [round_coords(child) for child in node]


def main() -> None:
    print(f"Downloading {SOURCE} ...")
    with urllib.request.urlopen(SOURCE, timeout=120) as response:
        source = json.load(response)

    features = []
    for feature in source["features"]:
        props = feature["properties"]
        entry = WANTED.get(props.get("BRK_NAME"))
        if entry is None:
            continue
        role, label = entry
        geometry = feature["geometry"]
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "role": role,
                    "label": label,
                    # Kept verbatim from Natural Earth so the map can
                    # state the administration status rather than our
                    # paraphrase of it.
                    "note": props.get("NOTE_BRK"),
                    "source": "Natural Earth 10m disputed areas (public domain)",
                },
                "geometry": {
                    "type": geometry["type"],
                    "coordinates": round_coords(geometry["coordinates"]),
                },
            }
        )

    found = {f["properties"]["label"] for f in features}
    missing = {label for _, label in WANTED.values()} - found
    if missing:
        raise SystemExit(f"Natural Earth is missing: {sorted(missing)}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )

    size_kb = OUT.stat().st_size / 1024
    print(f"\nWrote {OUT.relative_to(OUT.parents[2])}  ({size_kb:.1f} KB)")
    for feature in features:
        props = feature["properties"]
        print(f"  {props['role']:<9} {props['label']:<42} {props['note']}")


if __name__ == "__main__":
    main()
