from typing import List

from utils.helpers import make_zone_id


class Zone:
    """A pickup zone within a city; owns the trips that were requested from it."""

    def __init__(self, city: str, name: str):
        self._city = city
        self._name = name
        self._zone_id = make_zone_id(city, name)
        self._trips: List["Trip"] = []          # noqa: F821  (Trip imported lazily to avoid cycles)

    zone_id = property(lambda self: self._zone_id)
    city = property(lambda self: self._city)
    name = property(lambda self: self._name)

    def add_trip(self, trip) -> None:
        self._trips.append(trip)

    @property
    def trips(self) -> tuple:
        return tuple(self._trips)

    @property
    def request_count(self) -> int:
        return len(self._trips)

    def __repr__(self) -> str:
        return f"Zone({self._zone_id!r}, requests={len(self._trips)})"
