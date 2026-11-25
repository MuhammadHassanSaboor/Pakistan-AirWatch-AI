"""Feast entity definitions.

The entity key is the join key for every feature lookup. `city_id` is
a stable, human-readable slug generated from the city name
(see src/data/cities.py), which means a feature row can be traced back
to a real place without a lookup table.
"""

from feast import Entity, ValueType

city = Entity(
    name="city_id",
    join_keys=["city_id"],
    value_type=ValueType.STRING,
    description=(
        "Stable identifier for one of the 134 Pakistani cities we "
        "forecast. Slug form, e.g. 'lahore', 'dera_ghazi_khan'."
    ),
    tags={"owner": "hassan", "domain": "geography"},
)
