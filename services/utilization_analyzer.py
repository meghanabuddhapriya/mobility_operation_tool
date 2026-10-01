"""Driver utilisation (interval processing over activity logs) and idle-gap analysis."""
import heapq
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from utils import constants as C

from .dataset import Dataset

HOUR = 3600.0


@dataclass
class UtilizationThresholds:
    high: float = C.HIGH_UTILIZATION       # fraction, e.g. 0.60
    low: float = C.LOW_UTILIZATION

    def __post_init__(self):
        if not (0 <= self.low <= self.high <= 1):
            raise ValueError("Utilization thresholds must satisfy 0 ≤ low ≤ high ≤ 100%.")

    def classify(self, utilization: float) -> str:
        if utilization >= self.high:
            return "High"
        if utilization < self.low:
            return "Low"
        return "Medium"


@dataclass
class UtilizationRecord:
    driver_id: str
    name: str
    online_hours: float
    busy_hours: float
    idle_hours: float
    utilization: float           # fraction 0..1
    category: str
    skipped_segments: int = 0    # states longer than MAX_SEGMENT_HOURS (missing logout)


class UtilizationAnalyzer:
    """For each driver: walk the time-sorted event log once, summing the time spent in each state.

    A state lasts from its own timestamp until the next event. 'Offline' periods are ignored.
    Online hours = Online + Busy + Idle time; Busy hours = Busy time; Idle = Online - Busy.
    Utilisation = Busy / Online.
    """

    def __init__(self, dataset: Dataset, max_segment_hours: float = C.MAX_SEGMENT_HOURS):
        self._data = dataset
        self._max_seconds = max_segment_hours * HOUR
        self._raw: Optional[Dict[str, tuple]] = None

    def _totals(self) -> Dict[str, tuple]:
        if self._raw is None:
            self._raw = {}
            for did, events in self._data.activity_by_driver.items():
                events = sorted(events)                                  # already sorted; Timsort ~O(m)
                busy = online = 0.0
                skipped = 0
                for cur, nxt in zip(events, events[1:]):                 # sequential consecutive-pair traversal
                    if cur.status == "Offline":
                        continue
                    seconds = (nxt.timestamp - cur.timestamp).total_seconds()
                    if seconds <= 0:
                        continue
                    if seconds > self._max_seconds:
                        skipped += 1
                        continue
                    online += seconds
                    if cur.status == "Busy":
                        busy += seconds
                self._raw[did] = (online, busy, skipped)
        return self._raw

    def records(self, thresholds: Optional[UtilizationThresholds] = None) -> List[UtilizationRecord]:
        thresholds = thresholds or UtilizationThresholds()
        out = []
        for did, (online, busy, skipped) in self._totals().items():
            if online <= 0:
                continue                                                 # no usable online time
            driver = self._data.drivers.get(did)
            util = busy / online
            out.append(UtilizationRecord(did, driver.name if driver else "Unknown", round(online / HOUR, 2),
                                         round(busy / HOUR, 2), round((online - busy) / HOUR, 2),
                                         util, thresholds.classify(util), skipped))
        return sorted(out, key=lambda r: (-r.utilization, r.driver_id))

    def summary(self, thresholds: Optional[UtilizationThresholds] = None) -> dict:
        recs = self.records(thresholds)
        counts = {"High": 0, "Medium": 0, "Low": 0}
        for r in recs:
            counts[r.category] += 1
        no_data = len(self._data.drivers) - len(recs)
        return {"drivers_measured": len(recs), "drivers_without_activity": no_data, "counts": counts,
                "avg_utilization": (sum(r.utilization for r in recs) / len(recs)) if recs else 0.0}

    def utilization_map(self) -> Dict[str, float]:
        return {r.driver_id: r.utilization for r in self.records()}


@dataclass
class IdleGap:
    driver_id: str
    driver_name: str
    prev_trip: str
    next_trip: str
    prev_drop: object
    next_pickup: object
    minutes: float


@dataclass
class IdleResult:
    gaps: List[IdleGap] = field(default_factory=list)          # largest first, truncated to `limit`
    total_significant: int = 0
    overlaps: int = 0                                          # next trip started before previous ended
    off_shift: int = 0                                         # gap longer than the window
    pairs_examined: int = 0
    drivers_affected: int = 0
    avg_gap_min: float = 0.0
    per_driver: List[dict] = field(default_factory=list)


class IdleTimeAnalyzer:
    """Sort each driver's completed trips chronologically and inspect consecutive pairs."""

    def __init__(self, dataset: Dataset):
        self._data = dataset

    def analyze(self, threshold_min: float = C.DEFAULT_IDLE_THRESHOLD_MIN,
                window_min: float = C.DEFAULT_IDLE_WINDOW_MIN, driver_id: Optional[str] = None,
                limit: int = 100) -> IdleResult:
        if threshold_min < 0 or window_min < threshold_min:
            raise ValueError("Idle window must be at least as large as the idle threshold.")
        result = IdleResult()
        if driver_id:
            if driver_id not in self._data.drivers:
                raise ValueError(f"Driver {driver_id} was not found.")
            sources = [(driver_id, self._data.trips_for_driver(driver_id))]
        else:
            sources = self._data.trips_by_driver.items()

        significant: List[IdleGap] = []
        per_driver = []
        for did, trips in sources:
            timed = [t for t in trips if t.is_completed() and t.pickup_time and t.drop_time
                     and t.drop_time >= t.pickup_time]
            timed.sort(key=lambda t: t.pickup_time)                     # chronological order
            driver = self._data.drivers.get(did)
            name = driver.name if driver else "Unknown driver"
            count = 0
            total = longest = 0.0
            for prev, nxt in zip(timed, timed[1:]):                     # consecutive pairs
                result.pairs_examined += 1
                minutes = (nxt.pickup_time - prev.drop_time).total_seconds() / 60
                if minutes < 0:
                    result.overlaps += 1
                elif minutes > window_min:
                    result.off_shift += 1
                elif minutes >= threshold_min:
                    significant.append(IdleGap(did, name, prev.trip_id, nxt.trip_id,
                                               prev.drop_time, nxt.pickup_time, round(minutes, 1)))
                    count += 1
                    total += minutes
                    longest = max(longest, minutes)
            if count:
                per_driver.append({"driver_id": did, "name": name, "gaps": count,
                                   "total_min": round(total, 1), "longest_min": round(longest, 1)})
        result.total_significant = len(significant)
        result.drivers_affected = len(per_driver)
        result.avg_gap_min = round(sum(g.minutes for g in significant) / len(significant), 1) if significant else 0.0
        result.gaps = heapq.nlargest(limit, significant, key=lambda g: (g.minutes, g.driver_id))
        result.per_driver = sorted(per_driver, key=lambda r: (-r["total_min"], r["driver_id"]))[:20]
        return result
