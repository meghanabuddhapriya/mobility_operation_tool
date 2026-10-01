from collections import Counter, defaultdict
from typing import List

from utils.constants import TIME_SLOTS
from utils.helpers import pct, slot_for

from .dataset import Dataset


class CancellationAnalyzer:
    """Frequency counting + grouping + sorting over cancelled trips."""

    def __init__(self, dataset: Dataset):
        self._data = dataset
        self._cancelled = [t for t in dataset.trips.values() if t.is_cancelled()]       # filtering

    @property
    def total(self) -> int:
        return len(self._cancelled)

    def by_reason(self) -> List[dict]:
        counts = Counter(t.cancellation_reason for t in self._cancelled)
        rows = [{"reason": r, "count": c, "share": pct(c, self.total)} for r, c in counts.items()]
        return sorted(rows, key=lambda r: (-r["count"], r["reason"]))

    def by_zone(self) -> List[dict]:
        rows = []
        for z in self._data.zones.values():
            cancelled = sum(1 for t in z.trips if t.is_cancelled())
            rows.append({"zone_id": z.zone_id, "zone": z.name, "city": z.city, "requests": z.request_count,
                         "cancelled": cancelled, "rate": pct(cancelled, z.request_count)})
        return sorted(rows, key=lambda r: (-r["cancelled"], -r["rate"], r["zone_id"]))

    def by_driver(self, limit: int = 50) -> List[dict]:
        rows = []
        for did, trips in self._data.trips_by_driver.items():
            cancelled = sum(1 for t in trips if t.is_cancelled())
            if cancelled:
                driver = self._data.drivers.get(did)
                rows.append({"driver_id": did, "name": driver.name if driver else "Unknown driver",
                             "trips": len(trips), "cancelled": cancelled, "rate": pct(cancelled, len(trips)),
                             "top_reason": Counter(t.cancellation_reason for t in trips if t.is_cancelled()).most_common(1)[0][0]})
        rows.sort(key=lambda r: (-r["cancelled"], -r["rate"], r["driver_id"]))
        return rows[:limit]

    def by_time(self) -> List[dict]:
        requests, cancelled = Counter(), Counter()
        for t in self._data.trips.values():
            slot = slot_for(t.request_time)
            requests[slot] += 1
            cancelled[slot] += t.is_cancelled()
        return [{"slot": label, "requests": requests[label], "cancelled": cancelled[label],
                 "rate": pct(cancelled[label], requests[label])} for label, _, _ in TIME_SLOTS]

    def reason_by_zone(self) -> dict:
        """zone_id -> Counter of reasons (nested dictionary grouping)."""
        grouped = defaultdict(Counter)
        for t in self._cancelled:
            grouped[t.zone_id][t.cancellation_reason] += 1
        return grouped
