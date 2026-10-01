from collections import Counter, defaultdict
from typing import Dict, List

from models import Driver, DriverActivity, Trip, Zone


class Dataset:
    """In-memory store of model objects plus the hash indexes the analyzers rely on.

    Indexes (all O(1) average lookup):
        drivers        driver_id -> Driver
        trips          trip_id   -> Trip
        zones          zone_id   -> Zone
        trips_by_driver / trips_by_rider / activity_by_driver   id -> list (grouping indexes)
        rider_trip_counts                       rider_id  -> trip count (frequency map)
    """

    def __init__(self):
        self.drivers: Dict[str, Driver] = {}
        self.trips: Dict[str, Trip] = {}
        self.zones: Dict[str, Zone] = {}
        self.activity: List[DriverActivity] = []
        self.trips_by_driver: Dict[str, List[Trip]] = defaultdict(list)
        self.activity_by_driver: Dict[str, List[DriverActivity]] = defaultdict(list)
        self.trips_by_rider: Dict[str, List[Trip]] = defaultdict(list)
        self.rider_trip_counts: Counter = Counter()
        self._zone_names: Dict[str, List[str]] = defaultdict(list)

    # ---- building ----
    def add_driver(self, driver: Driver) -> None:
        self.drivers[driver.driver_id] = driver

    def add_trip(self, trip: Trip) -> None:
        self.trips[trip.trip_id] = trip
        if trip.driver_id:
            self.trips_by_driver[trip.driver_id].append(trip)
        if trip.rider_id:
            self.rider_trip_counts[trip.rider_id] += 1
            self.trips_by_rider[trip.rider_id].append(trip)
        zone = self.zones.get(trip.zone_id)
        if zone is None:
            zone = Zone(trip.city, trip.pickup_zone)
            self.zones[zone.zone_id] = zone
            self._zone_names[zone.name.lower()].append(zone.zone_id)
        zone.add_trip(trip)

    def add_activity(self, event: DriverActivity) -> None:
        self.activity.append(event)
        self.activity_by_driver[event.driver_id].append(event)

    def finalize(self) -> None:
        """Sort each driver's activity log chronologically (Timsort, O(m log m) per driver)."""
        for events in self.activity_by_driver.values():
            events.sort()

    # ---- lookups ----
    def find_zone_ids_by_name(self, name: str) -> List[str]:
        return list(self._zone_names.get(name.strip().lower(), []))

    @property
    def has_activity(self) -> bool:
        return bool(self.activity)

    def trips_for_driver(self, driver_id: str) -> List[Trip]:
        return self.trips_by_driver.get(driver_id, [])

    @property
    def cities(self) -> List[str]:
        return sorted({z.city for z in self.zones.values()})
