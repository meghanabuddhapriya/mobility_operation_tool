from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

from utils.topk import TopKHeap

from .dataset import Dataset
from .metrics import summarize


@dataclass
class DriverStats:
    driver_id: str
    name: str
    city: str
    vehicle_type: str
    rating: Optional[float]
    status: str
    total_trips: int
    completed: int
    cancelled: int
    completion_rate: float
    cancellation_rate: float
    revenue: float
    avg_fare: float
    avg_distance: float
    avg_fare_per_km: float
    avg_duration: float

    def as_dict(self) -> dict:
        return asdict(self)


class DriverAnalyzer:
    """Consumes Driver/Trip objects (via Dataset indexes) and returns per-driver analytics."""

    def __init__(self, dataset: Dataset):
        self._data = dataset
        self._cache: Optional[Dict[str, DriverStats]] = None

    def stats_for(self, driver_id: str) -> Optional[DriverStats]:
        """O(1) driver lookup + O(t) over that driver's own trips."""
        driver = self._data.drivers.get(driver_id)
        if driver is None:
            return None
        s = summarize(self._data.trips_for_driver(driver_id))
        return DriverStats(driver.driver_id, driver.name, driver.city, driver.vehicle_type, driver.rating,
                           driver.status, s.total, s.completed, s.cancelled, s.completion_rate,
                           s.cancellation_rate, round(s.revenue, 2), round(s.avg_fare, 2),
                           round(s.avg_distance, 2), round(s.avg_fare_per_km, 2), round(s.avg_duration, 1))

    def all_stats(self) -> Dict[str, DriverStats]:
        """Computed once (O(D + T)) and cached."""
        if self._cache is None:
            self._cache = {did: self.stats_for(did) for did in self._data.drivers}
        return self._cache

    # ---- rankings (bounded heap, O(D log K)) ----
    def _rank(self, key, k, largest=True, min_trips=0):
        heap = TopKHeap(k, largest)
        for st in self.all_stats().values():
            if st.total_trips >= min_trips:
                heap.push(st.driver_id, key(st), st)
        return [(st, value) for _, value, st in heap.result()]

    def top_by_completed(self, k: int = 10):
        return self._rank(lambda s: s.completed, k)

    def highest_revenue(self, k: int = 10):
        return self._rank(lambda s: s.revenue, k)

    def lowest_cancellation(self, k: int = 10, min_trips: int = 5):
        return self._rank(lambda s: s.cancellation_rate, k, largest=False, min_trips=min_trips)

    def driver_options(self) -> List[tuple]:
        return sorted((d.driver_id, d.name) for d in self._data.drivers.values())
