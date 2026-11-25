"""Request validation for the Flask API.

Hand-written rather than pulled from a library so the rules are
explicit and the error messages are useful to a client. Every rule
here exists because an unvalidated version of it is an attack surface
or a 500 error:

* unbounded `cities` list      -> cheap denial of service
* unbounded string lengths     -> log flooding
* unknown horizon              -> KeyError deep inside the model
* non-numeric overrides        -> pandas raises mid-prediction

The API returns 422 with a list of problems, never a stack trace.
"""

from __future__ import annotations

from typing import Any

from src.config import MODEL_CFG

VALID_HORIZONS: set[int] = set(MODEL_CFG["horizons"])
MAX_CITIES_PER_REQUEST = 200
MAX_ID_LENGTH = 64


class ValidationResult:
    def __init__(self, errors: list[str], cleaned: Any = None):
        self.errors = errors
        self.cleaned = cleaned

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_response(self) -> dict:
        return {
            "error": "validation_failed",
            "message": "The request body did not pass validation.",
            "details": self.errors[:25],
        }


def validate_predict_request(payload: Any) -> ValidationResult:
    """Validate POST /predict.

    Accepted shape::

        {
          "cities": [
            {"city_id": "lahore", "horizon": 24},
            {"city_id": "karachi"}            # horizon defaults to 24
          ]
        }
    """
    errors: list[str] = []

    if not isinstance(payload, dict):
        return ValidationResult(["body must be a JSON object"])

    if "cities" not in payload:
        return ValidationResult(["body must contain a 'cities' array"])

    cities = payload["cities"]
    if not isinstance(cities, list):
        return ValidationResult(["'cities' must be an array"])

    if len(cities) == 0:
        return ValidationResult(["'cities' must contain at least one entry"])

    if len(cities) > MAX_CITIES_PER_REQUEST:
        return ValidationResult(
            [
                f"'cities' may contain at most {MAX_CITIES_PER_REQUEST} "
                f"entries, received {len(cities)}"
            ]
        )

    cleaned: list[dict] = []
    seen: set[tuple[str, int]] = set()

    for i, entry in enumerate(cities):
        if not isinstance(entry, dict):
            errors.append(f"cities[{i}]: must be an object")
            continue

        raw_id = entry.get("city_id")
        if raw_id is None:
            errors.append(f"cities[{i}]: 'city_id' is required")
            continue
        if not isinstance(raw_id, str):
            errors.append(f"cities[{i}]: 'city_id' must be a string")
            continue

        city_id = raw_id.strip().lower()
        if not city_id:
            errors.append(f"cities[{i}]: 'city_id' must not be empty")
            continue
        if len(city_id) > MAX_ID_LENGTH:
            errors.append(f"cities[{i}]: 'city_id' exceeds {MAX_ID_LENGTH} characters")
            continue
        if not all(ch.isalnum() or ch == "_" for ch in city_id):
            errors.append(
                f"cities[{i}]: 'city_id' may contain only letters, digits "
                "and underscores"
            )
            continue

        horizon = entry.get("horizon", 24)
        if isinstance(horizon, bool) or not isinstance(horizon, int | float):
            errors.append(f"cities[{i}]: 'horizon' must be a number")
            continue
        horizon = int(horizon)
        if horizon not in VALID_HORIZONS:
            errors.append(
                f"cities[{i}]: 'horizon' must be one of "
                f"{sorted(VALID_HORIZONS)}, received {horizon}"
            )
            continue

        key = (city_id, horizon)
        if key in seen:
            continue  # silently de-duplicate; not an error
        seen.add(key)
        cleaned.append({"city_id": city_id, "horizon": horizon})

    if errors:
        return ValidationResult(errors)
    if not cleaned:
        return ValidationResult(["no valid city entries after validation"])

    return ValidationResult([], cleaned)


def validate_forecast_query(args: dict) -> ValidationResult:
    """Validate GET /api/forecast query parameters."""
    errors: list[str] = []
    cleaned: dict[str, Any] = {}

    horizon = args.get("horizon", "24")
    try:
        h = int(horizon)
    except (TypeError, ValueError):
        return ValidationResult([f"'horizon' must be an integer, got {horizon!r}"])
    if h not in VALID_HORIZONS:
        errors.append(f"'horizon' must be one of {sorted(VALID_HORIZONS)}")
    cleaned["horizon"] = h

    province = args.get("province")
    if province is not None:
        if not isinstance(province, str) or len(province) > MAX_ID_LENGTH:
            errors.append("'province' must be a short string")
        else:
            cleaned["province"] = province.strip()

    fmt = args.get("format", "json")
    if fmt not in {"json", "geojson"}:
        errors.append("'format' must be 'json' or 'geojson'")
    cleaned["format"] = fmt

    return ValidationResult(errors, cleaned if not errors else None)


def validate_history_query(args: dict) -> ValidationResult:
    """Validate GET /api/history/<city_id> query parameters."""
    errors: list[str] = []
    cleaned: dict[str, Any] = {}

    days = args.get("days", "7")
    try:
        d = int(days)
    except (TypeError, ValueError):
        return ValidationResult([f"'days' must be an integer, got {days!r}"])
    if not 1 <= d <= 90:
        errors.append("'days' must be between 1 and 90")
    cleaned["days"] = d

    return ValidationResult(errors, cleaned if not errors else None)


__all__ = [
    "VALID_HORIZONS",
    "MAX_CITIES_PER_REQUEST",
    "ValidationResult",
    "validate_predict_request",
    "validate_forecast_query",
    "validate_history_query",
]
