from typing import List, Optional

from .dataset import Dataset
from .driver_analyzer import DriverAnalyzer

SEARCH_TYPES = [("driver", "Driver ID"), ("trip", "Trip ID"), ("zone", "Zone ID or name"), ("rider", "Rider ID")]


class SearchService:
    """Hash-index lookups: driver_id, trip_id, zone_id and rider_id resolve in O(1) average."""

    def __init__(self, dataset: Dataset, drivers: DriverAnalyzer):
        self._data = dataset
        self._drivers = drivers

    def search(self, kind: str, query: str) -> dict:
        query = (query or "").strip()
        if kind not in dict(SEARCH_TYPES):
            raise ValueError("Choose a search type.")
        if not query:
            raise ValueError("Enter an ID to search for.")
        handler = getattr(self, f"_search_{kind}")
        result = handler(query)
        return {"kind": kind, "query": query, "found": result is not None, "result": result}

    def _search_driver(self, q: str) -> Optional[dict]:
        driver = self._data.drivers.get(q.upper())
        if driver is None:
            return None
        recent = sorted(self._data.trips_for_driver(driver.driver_id), key=lambda t: t.request_time, reverse=True)[:10]
        return {"profile": driver.get_profile(), "stats": self._drivers.stats_for(driver.driver_id),
                "recent_trips": [t.to_dict() for t in recent]}

    def _search_trip(self, q: str) -> Optional[dict]:
        trip = self._data.trips.get(q.upper())
        return {"trip": trip.to_dict(), "fare_per_km": trip.calculate_fare_per_km()} if trip else None

    def _search_zone(self, q: str) -> Optional[dict]:
        zone_ids: List[str] = [q.upper()] if q.upper() in self._data.zones else self._data.find_zone_ids_by_name(q)
        if not zone_ids:
            return None
        return {"zones": [{"zone_id": zid, "name": self._data.zones[zid].name, "city": self._data.zones[zid].city,
                           "requests": self._data.zones[zid].request_count} for zid in zone_ids]}

    def _search_rider(self, q: str) -> Optional[dict]:
        trips = self._data.trips_by_rider.get(q.upper())
        if not trips:
            return None
        return {"rider_id": q.upper(), "trip_count": len(trips),
                "trips": [t.to_dict() for t in sorted(trips, key=lambda t: t.request_time, reverse=True)[:10]]}
