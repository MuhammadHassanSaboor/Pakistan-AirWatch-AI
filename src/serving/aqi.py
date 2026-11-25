"""US EPA Air Quality Index conversion for PM2.5.

We name the standard explicitly everywhere it appears — in the API
response, the map legend and the report. Mixing µg/m³ thresholds with
AQI category numbers is a common and misleading error, so the two are
kept strictly separate: `pm2_5_pred` is always a concentration,
`aqi_us` is always an index value.

Breakpoints: US EPA, 2024 revision (PM2.5 24-hour standard).
Reference: https://www.airnow.gov/aqi/aqi-basics/
"""

from __future__ import annotations

from dataclasses import dataclass

# (C_low, C_high, I_low, I_high) — concentration µg/m³ -> index
_BREAKPOINTS: list[tuple[float, float, int, int]] = [
    (0.0, 9.0, 0, 50),
    (9.1, 35.4, 51, 100),
    (35.5, 55.4, 101, 150),
    (55.5, 125.4, 151, 200),
    (125.5, 225.4, 201, 300),
    (225.5, 325.4, 301, 500),
]

STANDARD = "US EPA (2024 PM2.5 revision)"


@dataclass(frozen=True)
class AqiCategory:
    name: str
    lower: int
    upper: int
    color: str
    advice: str


CATEGORIES: list[AqiCategory] = [
    AqiCategory("Good", 0, 50, "#00E400", "Air quality is satisfactory."),
    AqiCategory(
        "Moderate",
        51,
        100,
        "#FFFF00",
        "Unusually sensitive people should consider limiting "
        "prolonged outdoor exertion.",
    ),
    AqiCategory(
        "Unhealthy for Sensitive Groups",
        101,
        150,
        "#FF7E00",
        "Children, older adults and people with heart or lung "
        "disease should reduce prolonged outdoor exertion.",
    ),
    AqiCategory(
        "Unhealthy",
        151,
        200,
        "#FF0000",
        "Everyone may begin to experience health effects.",
    ),
    AqiCategory(
        "Very Unhealthy",
        201,
        300,
        "#8F3F97",
        "Health alert: everyone may experience more serious " "health effects.",
    ),
    AqiCategory(
        "Hazardous", 301, 500, "#7E0023", "Health warning of emergency conditions."
    ),
]


def pm25_to_aqi(concentration: float | None) -> int | None:
    """Convert a PM2.5 concentration (µg/m³) to a US EPA AQI value.

    Returns None for missing input. Values above the top breakpoint are
    capped at 500, which is the maximum the scale defines.
    """
    if concentration is None:
        return None
    try:
        c = float(concentration)
    except (TypeError, ValueError):
        return None
    if c != c or c < 0:  # NaN or negative
        return None

    # The EPA truncates to one decimal place before applying the formula.
    c = int(c * 10) / 10.0

    for c_low, c_high, i_low, i_high in _BREAKPOINTS:
        if c_low <= c <= c_high:
            aqi = (i_high - i_low) / (c_high - c_low) * (c - c_low) + i_low
            return int(round(aqi))

    return 500  # beyond the defined scale


def aqi_category(aqi: int | None) -> AqiCategory | None:
    if aqi is None:
        return None
    for cat in CATEGORIES:
        if cat.lower <= aqi <= cat.upper:
            return cat
    return CATEGORIES[-1]


def describe(concentration: float | None) -> dict:
    """Full AQI description for one concentration, ready for JSON."""
    aqi = pm25_to_aqi(concentration)
    cat = aqi_category(aqi)
    return {
        "aqi_us": aqi,
        "aqi_category": cat.name if cat else None,
        "aqi_color": cat.color if cat else None,
        "aqi_advice": cat.advice if cat else None,
        "aqi_standard": STANDARD,
    }


def legend() -> list[dict]:
    """Legend data for the frontend, so colours never drift apart."""
    return [
        {
            "name": c.name,
            "aqi_lower": c.lower,
            "aqi_upper": c.upper,
            "color": c.color,
            "advice": c.advice,
            "pm25_lower": _aqi_to_pm25(c.lower),
            "pm25_upper": _aqi_to_pm25(c.upper),
        }
        for c in CATEGORIES
    ]


def _aqi_to_pm25(aqi: int) -> float | None:
    """Inverse conversion, used only to label the legend."""
    for c_low, c_high, i_low, i_high in _BREAKPOINTS:
        if i_low <= aqi <= i_high:
            c = (c_high - c_low) / (i_high - i_low) * (aqi - i_low) + c_low
            return round(c, 1)
    return None


__all__ = [
    "STANDARD",
    "CATEGORIES",
    "pm25_to_aqi",
    "aqi_category",
    "describe",
    "legend",
]
