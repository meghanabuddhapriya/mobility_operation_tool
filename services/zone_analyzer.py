from collections import Counter
from typing import List, Optional

from utils.constants import TIME_SLOTS
from utils.helpers import slot_for

from .dataset import Dataset
from .metrics import summarize


class ZoneAnalyzer:
    def __init__(self, dataset: Dataset):
        self._data = dataset

    def zone_options(self, city: Optional[str] = None) -> List[dict]:
        zones = [z for z in self._data.zones.values() if not city or z.city == city]
        return sorted(({"zone_id": z.zone_id, "label": f"{z.name} ({z.city})", "city": z.city} for z in zones),
                      key=lambda r: (r["city"], r["label"]))

    def stats(self, zone_id: str) -> Optional[dict]:
        zone = self._data.zones.get(zone_id)                 # O(1) hash lookup
        if zone is None:
            return None
        trips = zone.trips
        s = summarize(trips)
        slot_counts = Counter(slot_for(t.request_time) for t in trips)
        slots = [{"slot": label, "requests": slot_counts.get(label, 0)} for label, _, _ in TIME_SLOTS]
        peak = max(slots, key=lambda r: r["requests"])
        return {
            "zone_id": zone.zone_id, "name": zone.name, "city": zone.city,
            "requests": s.total, "completed": s.completed, "cancelled": s.cancelled,
            "completion_rate": s.completion_rate, "cancellation_rate": s.cancellation_rate,
            "revenue": round(s.revenue, 2), "avg_fare": round(s.avg_fare, 2),
            "slots": slots, "peak_slot": peak["slot"] if peak["requests"] else None,
            "top_drop_zones": Counter(t.drop_zone for t in trips).most_common(3),
            "cancel_reasons": Counter(t.cancellation_reason for t in trips if t.is_cancelled()).most_common(),
        }

    def all_zone_rows(self, city: Optional[str] = None) -> List[dict]:
        rows = []
        for z in self._data.zones.values():
            if city and z.city != city:
                continue
            s = summarize(z.trips)
            rows.append({"zone_id": z.zone_id, "zone": z.name, "city": z.city, "requests": s.total,
                         "completed": s.completed, "cancelled": s.cancelled,
                         "cancellation_rate": s.cancellation_rate, "revenue": round(s.revenue, 2),
                         "avg_fare": round(s.avg_fare, 2)})
        return sorted(rows, key=lambda r: (-r["requests"], r["zone_id"]))
