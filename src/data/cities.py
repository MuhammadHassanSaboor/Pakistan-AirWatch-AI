"""Pakistan city reference data.

Builds `data/reference/pakistan_cities.csv`, the entity table that
anchors the whole project. Every row is one forecasting location.

The coordinates are embedded here rather than downloaded so that the
pipeline is fully reproducible offline and needs no third-party
account. Values are drawn from the public GeoNames gazetteer
(CC BY 4.0) and cross-checked against official district listings.

All seven administrative units are represented:
Punjab, Sindh, Khyber Pakhtunkhwa, Balochistan, Gilgit-Baltistan,
Azad Jammu & Kashmir, and Islamabad Capital Territory.

Run
---
    python -m src.data.cities
"""

from __future__ import annotations

import logging
import re

import pandas as pd

from src.config import DATA_CFG, resolve

log = logging.getLogger(__name__)

# name, province, lat, lon, population, elevation_m
_CITIES: list[tuple[str, str, float, float, int, int]] = [
    # ── Islamabad Capital Territory ───────────────────────────
    ("Islamabad", "Islamabad", 33.6844, 73.0479, 1_014_825, 540),
    # ── Punjab ────────────────────────────────────────────────
    ("Lahore", "Punjab", 31.5204, 74.3587, 11_126_285, 217),
    ("Faisalabad", "Punjab", 31.4504, 73.1350, 3_204_726, 186),
    ("Rawalpindi", "Punjab", 33.5651, 73.0169, 2_098_231, 508),
    ("Gujranwala", "Punjab", 32.1877, 74.1945, 2_027_001, 226),
    ("Multan", "Punjab", 30.1575, 71.5249, 1_871_843, 122),
    ("Bahawalpur", "Punjab", 29.3956, 71.6836, 762_111, 117),
    ("Sargodha", "Punjab", 32.0836, 72.6711, 659_862, 193),
    ("Sialkot", "Punjab", 32.4945, 74.5229, 655_852, 256),
    ("Sheikhupura", "Punjab", 31.7131, 73.9783, 473_129, 214),
    ("Rahim Yar Khan", "Punjab", 28.4202, 70.2952, 420_419, 83),
    ("Jhang", "Punjab", 31.2781, 72.3317, 414_131, 158),
    ("Dera Ghazi Khan", "Punjab", 30.0489, 70.6455, 399_064, 128),
    ("Gujrat", "Punjab", 32.5731, 74.0789, 390_533, 243),
    ("Sahiwal", "Punjab", 30.6682, 73.1114, 389_605, 170),
    ("Wah Cantonment", "Punjab", 33.7940, 72.7461, 380_103, 532),
    ("Kasur", "Punjab", 31.1187, 74.4504, 358_409, 218),
    ("Okara", "Punjab", 30.8081, 73.4458, 357_935, 177),
    ("Chiniot", "Punjab", 31.7200, 72.9789, 278_747, 163),
    ("Kamoke", "Punjab", 31.9742, 74.2239, 249_767, 219),
    ("Hafizabad", "Punjab", 32.0712, 73.6895, 245_784, 207),
    ("Sadiqabad", "Punjab", 28.3091, 70.1300, 239_677, 85),
    ("Burewala", "Punjab", 30.1667, 72.6500, 231_797, 143),
    ("Khanewal", "Punjab", 30.3017, 71.9321, 227_059, 126),
    ("Muzaffargarh", "Punjab", 30.0736, 71.1805, 182_458, 123),
    ("Jhelum", "Punjab", 32.9425, 73.7257, 190_425, 233),
    ("Khanpur", "Punjab", 28.6453, 70.6567, 170_626, 88),
    ("Gojra", "Punjab", 31.1489, 72.6825, 158_586, 174),
    ("Mandi Bahauddin", "Punjab", 32.5861, 73.4917, 157_352, 223),
    ("Abdul Hakim", "Punjab", 30.5525, 72.1278, 150_000, 134),
    ("Daska", "Punjab", 32.3242, 74.3500, 142_586, 239),
    ("Pakpattan", "Punjab", 30.3453, 73.3906, 139_525, 162),
    ("Bahawalnagar", "Punjab", 29.9942, 73.2536, 134_936, 152),
    ("Tando Adam", "Sindh", 25.7614, 68.6628, 152_689, 26),
    ("Vehari", "Punjab", 30.0442, 72.3528, 124_019, 139),
    ("Nankana Sahib", "Punjab", 31.4492, 73.7067, 121_000, 199),
    ("Toba Tek Singh", "Punjab", 30.9709, 72.4826, 117_629, 166),
    ("Jaranwala", "Punjab", 31.3333, 73.4167, 116_000, 180),
    ("Attock", "Punjab", 33.7667, 72.3667, 114_000, 350),
    ("Chakwal", "Punjab", 32.9328, 72.8630, 113_524, 498),
    ("Kot Addu", "Punjab", 30.4697, 70.9644, 110_000, 124),
    ("Layyah", "Punjab", 30.9611, 70.9428, 106_000, 143),
    ("Mianwali", "Punjab", 32.5839, 71.5370, 103_000, 210),
    ("Bhakkar", "Punjab", 31.6260, 71.0654, 98_000, 168),
    ("Lodhran", "Punjab", 29.5339, 71.6336, 95_000, 112),
    ("Narowal", "Punjab", 32.1014, 74.8731, 92_000, 243),
    ("Rajanpur", "Punjab", 29.1041, 70.3302, 88_000, 96),
    ("Hasilpur", "Punjab", 29.6939, 72.5461, 87_000, 128),
    ("Arifwala", "Punjab", 30.2914, 73.0656, 85_000, 155),
    ("Kabirwala", "Punjab", 30.4042, 71.8697, 83_000, 130),
    ("Mian Channu", "Punjab", 30.4397, 72.3544, 82_000, 136),
    ("Jalalpur Jattan", "Punjab", 32.6417, 74.2056, 80_000, 251),
    ("Kharian", "Punjab", 32.8181, 73.8814, 78_000, 263),
    ("Shakargarh", "Punjab", 32.2631, 75.1600, 76_000, 265),
    ("Murree", "Punjab", 33.9070, 73.3903, 30_000, 2_291),
    ("Talagang", "Punjab", 32.9292, 72.4150, 72_000, 460),
    ("Pind Dadan Khan", "Punjab", 32.5869, 73.0497, 70_000, 219),
    ("Kot Radha Kishan", "Punjab", 31.1667, 74.1000, 68_000, 208),
    ("Chishtian", "Punjab", 29.7971, 72.8578, 101_000, 148),
    ("Shorkot", "Punjab", 31.1500, 72.4167, 66_000, 152),
    ("Fort Abbas", "Punjab", 29.1933, 72.8569, 64_000, 143),
    # ── Sindh ─────────────────────────────────────────────────
    ("Karachi", "Sindh", 24.8607, 67.0011, 14_910_352, 10),
    ("Hyderabad", "Sindh", 25.3960, 68.3578, 1_732_693, 13),
    ("Sukkur", "Sindh", 27.7052, 68.8574, 499_900, 59),
    ("Larkana", "Sindh", 27.5600, 68.2264, 490_508, 46),
    ("Nawabshah", "Sindh", 26.2442, 68.4100, 279_688, 36),
    ("Mirpur Khas", "Sindh", 25.5276, 69.0111, 233_916, 19),
    ("Jacobabad", "Sindh", 28.2769, 68.4514, 200_815, 56),
    ("Shikarpur", "Sindh", 27.9556, 68.6382, 177_682, 52),
    ("Khairpur", "Sindh", 27.5295, 68.7592, 150_425, 53),
    ("Dadu", "Sindh", 26.7319, 67.7764, 146_179, 32),
    ("Tando Allahyar", "Sindh", 25.4608, 68.7192, 133_487, 22),
    ("Badin", "Sindh", 24.6556, 68.8370, 102_000, 8),
    ("Thatta", "Sindh", 24.7461, 67.9239, 60_000, 12),
    ("Ghotki", "Sindh", 28.0042, 69.3153, 75_000, 65),
    ("Kashmore", "Sindh", 28.4333, 69.5833, 62_000, 62),
    ("Umerkot", "Sindh", 25.3614, 69.7361, 68_000, 25),
    ("Sanghar", "Sindh", 26.0464, 68.9492, 72_000, 29),
    ("Matiari", "Sindh", 25.5969, 68.4461, 58_000, 18),
    ("Sujawal", "Sindh", 24.6031, 68.0750, 52_000, 9),
    ("Shahdadkot", "Sindh", 27.8475, 67.9072, 71_000, 42),
    ("Kandhkot", "Sindh", 28.2558, 69.1792, 65_000, 58),
    ("Rohri", "Sindh", 27.6947, 68.8961, 60_000, 57),
    ("Mithi", "Sindh", 24.7333, 69.8000, 45_000, 50),
    ("Gwadar", "Balochistan", 25.1264, 62.3225, 90_000, 9),
    # ── Khyber Pakhtunkhwa ────────────────────────────────────
    ("Peshawar", "Khyber Pakhtunkhwa", 34.0151, 71.5249, 1_970_042, 331),
    ("Mardan", "Khyber Pakhtunkhwa", 34.1989, 72.0400, 358_604, 283),
    ("Mingora", "Khyber Pakhtunkhwa", 34.7795, 72.3614, 331_091, 984),
    ("Kohat", "Khyber Pakhtunkhwa", 33.5869, 71.4414, 228_779, 489),
    ("Abbottabad", "Khyber Pakhtunkhwa", 34.1558, 73.2194, 148_587, 1_256),
    ("Dera Ismail Khan", "Khyber Pakhtunkhwa", 31.8313, 70.9019, 217_457, 173),
    ("Nowshera", "Khyber Pakhtunkhwa", 34.0153, 71.9747, 118_594, 288),
    ("Swabi", "Khyber Pakhtunkhwa", 34.1203, 72.4700, 111_911, 305),
    ("Charsadda", "Khyber Pakhtunkhwa", 34.1453, 71.7308, 105_414, 276),
    ("Mansehra", "Khyber Pakhtunkhwa", 34.3300, 73.1968, 98_000, 1_088),
    ("Bannu", "Khyber Pakhtunkhwa", 32.9889, 70.6056, 99_000, 367),
    ("Haripur", "Khyber Pakhtunkhwa", 33.9947, 72.9339, 87_000, 520),
    ("Batkhela", "Khyber Pakhtunkhwa", 34.6181, 71.9728, 82_000, 686),
    ("Timergara", "Khyber Pakhtunkhwa", 34.8281, 71.8428, 78_000, 823),
    ("Hangu", "Khyber Pakhtunkhwa", 33.5331, 71.0586, 60_000, 873),
    ("Karak", "Khyber Pakhtunkhwa", 33.1167, 71.0931, 55_000, 666),
    ("Chitral", "Khyber Pakhtunkhwa", 35.8518, 71.7864, 50_000, 1_494),
    ("Parachinar", "Khyber Pakhtunkhwa", 33.8989, 70.1011, 62_000, 1_726),
    ("Tank", "Khyber Pakhtunkhwa", 32.2167, 70.3833, 48_000, 310),
    ("Lakki Marwat", "Khyber Pakhtunkhwa", 32.6075, 70.9117, 60_000, 290),
    ("Dir", "Khyber Pakhtunkhwa", 35.2069, 71.8761, 45_000, 1_425),
    ("Saidu Sharif", "Khyber Pakhtunkhwa", 34.7500, 72.3572, 50_000, 961),
    # ── Balochistan ───────────────────────────────────────────
    ("Quetta", "Balochistan", 30.1798, 66.9750, 1_001_205, 1_680),
    ("Turbat", "Balochistan", 26.0023, 63.0440, 213_557, 142),
    ("Khuzdar", "Balochistan", 27.8120, 66.6100, 141_000, 1_237),
    ("Chaman", "Balochistan", 30.9180, 66.4518, 134_000, 1_326),
    ("Hub", "Balochistan", 25.0000, 66.9000, 110_000, 30),
    ("Sibi", "Balochistan", 29.5430, 67.8773, 75_000, 133),
    ("Zhob", "Balochistan", 31.3417, 69.4486, 68_000, 1_405),
    ("Loralai", "Balochistan", 30.3705, 68.5968, 58_000, 1_444),
    ("Gandava", "Balochistan", 28.6167, 67.4833, 42_000, 60),
    ("Pasni", "Balochistan", 25.2631, 63.4703, 48_000, 6),
    ("Mastung", "Balochistan", 29.7994, 66.8456, 52_000, 1_698),
    ("Nushki", "Balochistan", 29.5503, 66.0217, 45_000, 1_000),
    ("Kalat", "Balochistan", 29.0264, 66.5897, 40_000, 2_015),
    ("Dera Murad Jamali", "Balochistan", 28.5486, 68.2203, 55_000, 50),
    ("Usta Mohammad", "Balochistan", 28.1811, 68.0433, 47_000, 46),
    ("Dalbandin", "Balochistan", 28.8886, 64.4061, 35_000, 848),
    # ── Gilgit-Baltistan ──────────────────────────────────────
    ("Gilgit", "Gilgit-Baltistan", 35.9208, 74.3083, 216_760, 1_500),
    ("Skardu", "Gilgit-Baltistan", 35.2971, 75.6333, 95_000, 2_228),
    ("Chilas", "Gilgit-Baltistan", 35.4208, 74.0994, 35_000, 1_265),
    ("Hunza", "Gilgit-Baltistan", 36.3167, 74.6500, 30_000, 2_438),
    ("Astore", "Gilgit-Baltistan", 35.3667, 74.8500, 25_000, 2_600),
    # ── Azad Jammu & Kashmir ──────────────────────────────────
    ("Muzaffarabad", "Azad Jammu & Kashmir", 34.3700, 73.4711, 150_000, 737),
    ("Mirpur", "Azad Jammu & Kashmir", 33.1472, 73.7519, 124_000, 459),
    ("Kotli", "Azad Jammu & Kashmir", 33.5181, 73.9022, 72_000, 610),
    ("Rawalakot", "Azad Jammu & Kashmir", 33.8578, 73.7604, 60_000, 1_638),
    ("Bhimber", "Azad Jammu & Kashmir", 32.9742, 74.0789, 48_000, 360),
    ("Bagh", "Azad Jammu & Kashmir", 33.9792, 73.7722, 40_000, 1_006),
]


def slugify(name: str) -> str:
    """'Dera Ghazi Khan' -> 'dera_ghazi_khan' (stable entity key)."""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def build_city_table() -> pd.DataFrame:
    """Return the validated city reference table."""
    df = pd.DataFrame(
        _CITIES,
        columns=[
            "city_name",
            "province",
            "latitude",
            "longitude",
            "population",
            "elevation_m",
        ],
    )
    df.insert(0, "city_id", df["city_name"].map(slugify))

    # Deterministic order so the file diff is stable across runs.
    df = df.sort_values(["province", "city_name"]).reset_index(drop=True)

    _validate(df)
    return df


def _validate(df: pd.DataFrame) -> None:
    """Fail loudly rather than ship a broken reference table."""
    bbox = DATA_CFG["cities"]["bbox"]

    dupes = df.loc[df["city_id"].duplicated(), "city_id"].tolist()
    if dupes:
        raise ValueError(f"Duplicate city_id values: {dupes}")

    outside = df[
        (df["latitude"] < bbox["lat_min"])
        | (df["latitude"] > bbox["lat_max"])
        | (df["longitude"] < bbox["lon_min"])
        | (df["longitude"] > bbox["lon_max"])
    ]
    if not outside.empty:
        raise ValueError(
            "Cities outside the Pakistan bounding box:\n"
            f"{outside[['city_name', 'latitude', 'longitude']]}"
        )

    target = DATA_CFG["cities"]["target_count"]
    if len(df) < 100:
        raise ValueError(
            f"Only {len(df)} cities — the project requires 100+. "
            f"Target is {target}."
        )

    missing_provinces = {
        "Punjab",
        "Sindh",
        "Khyber Pakhtunkhwa",
        "Balochistan",
        "Gilgit-Baltistan",
        "Azad Jammu & Kashmir",
        "Islamabad",
    } - set(df["province"])
    if missing_provinces:
        raise ValueError(f"Provinces not represented: {missing_provinces}")


def write_city_table() -> pd.DataFrame:
    """Build the table and write it to the configured CSV path."""
    df = build_city_table()
    out = resolve(DATA_CFG["cities"]["file"])
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    log.info("Wrote %d cities to %s", len(df), out)
    return df


def load_cities() -> pd.DataFrame:
    """Read the city table, building it first if it does not exist."""
    path = resolve(DATA_CFG["cities"]["file"])
    if not path.exists():
        return write_city_table()
    return pd.read_csv(path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    table = write_city_table()
    print(f"\n{len(table)} cities written to {DATA_CFG['cities']['file']}\n")
    print(table.groupby("province").size().to_string())
    print(f"\nLatitude range : {table.latitude.min():.2f} .. {table.latitude.max():.2f}")
    print(f"Longitude range: {table.longitude.min():.2f} .. {table.longitude.max():.2f}")
    print(f"Elevation range: {table.elevation_m.min()} .. {table.elevation_m.max()} m")
