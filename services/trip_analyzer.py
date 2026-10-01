from collections import Counter, defaultdict
from typing import Dict, List

from utils.constants import TIME_SLOTS
from utils.helpers import pct, slot_for

from .dataset import Dataset
from .metrics import summarize

DISTANCE_BUCKETS = [(0, 5, "0–5 km"), (5, 10, "5–10 km"), (10, 15, "10–15 km"),
                    (15, 20, "15–20 km"), (20, float("inf"), "20+ km")]


class TripAnalyzer:
    def __init__(self, dataset: Dataset):
        self._data = dataset
        self._all = list(dataset.trips.values())

    def kpis(self) -> dict:
        s = summarize(self._all)
        riders = {t.rider_id for t in self._all if t.rider_id}          # set -> distinct riders
        return {
            "total_drivers": len(self._data.drivers),
            "active_drivers": sum(1 for d in self._data.drivers.values() if d.is_active()),
            "total_riders": len(riders),
            "total_trips": s.total, "completed_trips": s.completed, "cancelled_trips": s.cancelled,
            "completion_rate": s.completion_rate, "cancellation_rate": s.cancellation_rate,
            "total_revenue": round(s.revenue, 2), "avg_fare": round(s.avg_fare, 2),
            "avg_distance": round(s.avg_distance, 2), "avg_duration": round(s.avg_duration, 1),
        }

    # ---- frequency counting / grouping ----
    def demand_by_slot(self) -> List[dict]:
        counts = Counter(slot_for(t.request_time) for t in self._all)
        total = len(self._all)
        return [{"slot": label, "requests": counts.get(label, 0), "share": pct(counts.get(label, 0), total)}
                for label, _, _ in TIME_SLOTS]

    def demand_by_hour(self) -> List[dict]:
        counts = Counter(t.request_time.hour for t in self._all)
        return [{"hour": f"{h:02d}:00", "requests": counts.get(h, 0)} for h in range(24)]

    def peak_slot(self) -> dict:
        return max(self.demand_by_slot(), key=lambda r: r["requests"])

    def by_city(self) -> List[dict]:
        groups: Dict[str, list] = defaultdict(list)
        for t in self._all:
            groups[t.city].append(t)
        rows = []
        for city, trips in groups.items():
            s = summarize(trips)
            rows.append({"city": city, "requests": s.total, "completed": s.completed, "cancelled": s.cancelled,
                         "cancellation_rate": s.cancellation_rate, "revenue": round(s.revenue, 2),
                         "avg_fare": round(s.avg_fare, 2)})
        return sorted(rows, key=lambda r: (-r["requests"], r["city"]))

    def daily_trend(self) -> List[dict]:
        counts: Counter = Counter()
        done: Counter = Counter()
        for t in self._all:
            day = t.request_time.date()
            counts[day] += 1
            done[day] += t.is_completed()
        return [{"date": d.isoformat(), "requests": counts[d], "completed": done[d]} for d in sorted(counts)]

    def distance_distribution(self) -> List[dict]:
        counts = Counter()
        for t in self._all:
            if t.is_completed() and t.distance_km and t.distance_km > 0:
                for lo, hi, label in DISTANCE_BUCKETS:
                    if lo <= t.distance_km < hi:
                        counts[label] += 1
                        break
        return [{"bucket": label, "trips": counts.get(label, 0)} for _, _, label in DISTANCE_BUCKETS]

    def revenue_share_by_city(self) -> List[dict]:
        rows = self.by_city()
        total = sum(r["revenue"] for r in rows)
        return [{"city": r["city"], "revenue": r["revenue"], "share": pct(r["revenue"], total)} for r in rows]
