from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, List

from utils.constants import ZONE_MIN_REQUESTS_FOR_RATE
from utils.helpers import pct
from utils.topk import TopKHeap

from .cancellation_analyzer import CancellationAnalyzer
from .dataset import Dataset
from .driver_analyzer import DriverAnalyzer
from .utilization_analyzer import UtilizationAnalyzer


@dataclass
class MetricSpec:
    label: str
    unit: str                 # "count" | "currency" | "percent"
    entity: str               # column heading
    candidates: Callable      # () -> iterable of (id, name, value)
    largest: bool = True
    needs_activity: bool = False


class TopKService:
    """Registry of rankable metrics; every ranking goes through the bounded TopKHeap."""

    def __init__(self, dataset: Dataset, drivers: DriverAnalyzer, utilization: UtilizationAnalyzer,
                 cancellations: CancellationAnalyzer):
        self._data = dataset
        self._specs: "OrderedDict[str, MetricSpec]" = OrderedDict([
            ("driver_completed", MetricSpec("Top drivers by completed trips", "count", "Driver",
                lambda: ((s.driver_id, s.name, s.completed) for s in drivers.all_stats().values()))),
            ("driver_revenue", MetricSpec("Top drivers by revenue", "currency", "Driver",
                lambda: ((s.driver_id, s.name, s.revenue) for s in drivers.all_stats().values()))),
            ("driver_low_cancel", MetricSpec("Drivers with the lowest cancellation rate (min 5 trips)", "percent", "Driver",
                lambda: ((s.driver_id, s.name, s.cancellation_rate) for s in drivers.all_stats().values()
                         if s.total_trips >= 5), largest=False)),
            ("driver_utilization", MetricSpec("Top drivers by utilization", "percent", "Driver",
                lambda: ((r.driver_id, r.name, round(r.utilization * 100, 2)) for r in utilization.records()),
                needs_activity=True)),
            ("zone_demand", MetricSpec("Top zones by demand (requests)", "count", "Zone",
                lambda: ((z.zone_id, f"{z.name} ({z.city})", z.request_count) for z in dataset.zones.values()))),
            ("zone_cancellations", MetricSpec("Top zones by cancellations", "count", "Zone",
                lambda: ((r["zone_id"], f"{r['zone']} ({r['city']})", r["cancelled"]) for r in cancellations.by_zone()))),
            ("zone_cancel_rate", MetricSpec(f"Top zones by cancellation rate (min {ZONE_MIN_REQUESTS_FOR_RATE} requests)", "percent", "Zone",
                lambda: ((r["zone_id"], f"{r['zone']} ({r['city']})", r["rate"]) for r in cancellations.by_zone()
                         if r["requests"] >= ZONE_MIN_REQUESTS_FOR_RATE))),
            ("rider_trips", MetricSpec("Top riders by trip count", "count", "Rider",
                lambda: ((rid, rid, n) for rid, n in dataset.rider_trip_counts.items()))),
        ])

    def metrics(self) -> List[tuple]:
        return [(key, spec.label) for key, spec in self._specs.items()]

    def run(self, metric: str, k_raw) -> dict:
        spec = self._specs.get(metric)
        if spec is None:
            raise ValueError("Choose one of the listed metrics.")
        try:
            k = int(str(k_raw).strip())
        except (TypeError, ValueError):
            raise ValueError("K must be a whole number.")
        if not 1 <= k <= 1000:
            raise ValueError("K must be between 1 and 1000.")
        if spec.needs_activity and not self._data.has_activity:
            raise ValueError("This metric needs a driver activity file. Load one and try again.")

        heap = TopKHeap(k, spec.largest)
        seen = 0
        for item_id, name, value in spec.candidates():                 # O(N log K)
            heap.push(item_id, value, name)
            seen += 1
        rows = [{"rank": i, "id": item_id, "name": name, "value": value}
                for i, (item_id, value, name) in enumerate(heap.result(), start=1)]
        return {"metric": metric, "label": spec.label, "unit": spec.unit, "entity": spec.entity,
                "k": k, "candidates": seen, "rows": rows, "note": (f"Only {seen} candidates available."
                                                                  if seen < k else "")}
