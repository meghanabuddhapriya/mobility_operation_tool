"""Rule-based + statistical (IQR fence) anomaly detection for trips and drivers."""
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional

from utils import constants as C
from utils.helpers import parse_number_arg

from .dataset import Dataset
from .driver_analyzer import DriverAnalyzer
from .utilization_analyzer import UtilizationAnalyzer


@dataclass
class AnomalyThresholds:
    max_duration_min: float = C.MAX_TRIP_DURATION_MIN
    fare_iqr_multiplier: float = C.FARE_IQR_MULTIPLIER
    cancel_rate: float = C.DRIVER_CANCEL_RATE          # fraction
    min_trips: int = C.DRIVER_MIN_TRIPS_FOR_RATE
    low_utilization: float = C.DRIVER_LOW_UTILIZATION  # fraction
    trip_count_iqr_multiplier: float = C.TRIP_COUNT_IQR_MULTIPLIER
    low_rating: float = C.DRIVER_LOW_RATING

    @classmethod
    def from_args(cls, args: Mapping[str, str]) -> "AnomalyThresholds":
        """Build from query-string values (percentages given as 0-100). Raises ValueError on bad input."""
        d = cls()
        return cls(
            max_duration_min=parse_number_arg(args.get("max_duration"), "Max trip duration", d.max_duration_min, 1, 10000),
            fare_iqr_multiplier=parse_number_arg(args.get("fare_iqr"), "Fare IQR multiplier", d.fare_iqr_multiplier, 0.5, 20),
            cancel_rate=parse_number_arg(args.get("cancel_rate"), "Cancellation rate", d.cancel_rate * 100, 0, 100) / 100,
            min_trips=int(parse_number_arg(args.get("min_trips"), "Minimum trips", d.min_trips, 1, 1000)),
            low_utilization=parse_number_arg(args.get("low_util"), "Low utilization", d.low_utilization * 100, 0, 100) / 100,
            trip_count_iqr_multiplier=d.trip_count_iqr_multiplier,
            low_rating=parse_number_arg(args.get("low_rating"), "Low rating", d.low_rating, 0, 5),
        )


@dataclass
class Anomaly:
    entity_type: str      # "trip" or "driver"
    entity_id: str
    category: str
    detail: str


@dataclass
class AnomalyReport:
    trip_anomalies: List[Anomaly] = field(default_factory=list)
    driver_anomalies: List[Anomaly] = field(default_factory=list)
    thresholds: Optional[AnomalyThresholds] = None
    fare_fence: Optional[float] = None
    trip_count_fence: Optional[float] = None

    @property
    def total(self) -> int:
        return len(self.trip_anomalies) + len(self.driver_anomalies)

    @property
    def flagged_trips(self) -> int:
        return len({a.entity_id for a in self.trip_anomalies})

    @property
    def flagged_drivers(self) -> int:
        return len({a.entity_id for a in self.driver_anomalies})

    def category_counts(self) -> List[tuple]:
        return Counter(a.category for a in self.trip_anomalies + self.driver_anomalies).most_common()

    def drivers_needing_attention(self) -> List[tuple]:
        """[(driver_id, [issues])] ordered by number of distinct issues, then id."""
        grouped: Dict[str, List[str]] = defaultdict(list)
        for a in self.driver_anomalies:
            grouped[a.entity_id].append(a.detail)
        return sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0]))


def _upper_fence(values: List[float], multiplier: float) -> Optional[float]:
    """Q3 + multiplier * IQR; None when there is too little data for a meaningful quartile."""
    if len(values) < 8:
        return None
    q1, _, q3 = statistics.quantiles(values, n=4)
    return q3 + multiplier * (q3 - q1)


class AnomalyDetector:
    def __init__(self, dataset: Dataset, driver_analyzer: DriverAnalyzer, utilization: UtilizationAnalyzer):
        self._data = dataset
        self._drivers = driver_analyzer
        self._util = utilization

    def detect(self, thresholds: Optional[AnomalyThresholds] = None) -> AnomalyReport:
        th = thresholds or AnomalyThresholds()
        report = AnomalyReport(thresholds=th)
        self._detect_trips(th, report)
        self._detect_drivers(th, report)
        return report

    # ---------------- trips: one pass after computing the fare fence ----------------
    def _detect_trips(self, th: AnomalyThresholds, report: AnomalyReport) -> None:
        trips = self._data.trips.values()
        fares = [t.fare for t in trips if t.is_completed() and t.fare and t.fare > 0]
        fence = _upper_fence(fares, th.fare_iqr_multiplier)
        report.fare_fence = fence
        add = report.trip_anomalies.append

        for t in trips:
            tid = t.trip_id
            if t.fare is not None and t.fare < 0:
                add(Anomaly("trip", tid, "Negative fare", f"Fare {t.fare:g}"))
            if t.distance_km is not None and t.distance_km < 0:
                add(Anomaly("trip", tid, "Negative distance", f"Distance {t.distance_km:g} km"))
            if t.driver_id and t.driver_id not in self._data.drivers:
                add(Anomaly("trip", tid, "Unknown driver", f"Driver {t.driver_id} not in drivers file"))
            if not t.is_completed():
                continue
            if t.driver_id is None:
                add(Anomaly("trip", tid, "Missing driver", "Completed trip has no valid driver"))
            if t.distance_km == 0:
                add(Anomaly("trip", tid, "Zero distance", "Completed trip with 0 km"))
            if t.fare is not None and t.fare == 0:
                add(Anomaly("trip", tid, "Zero fare", "Completed trip with fare 0"))
            if t.pickup_time is None:
                add(Anomaly("trip", tid, "Invalid timestamp", "Missing or unreadable pickup time"))
            if t.drop_time is None:
                add(Anomaly("trip", tid, "Invalid timestamp", "Missing or unreadable drop time"))
            if t.pickup_time and t.drop_time and t.drop_time < t.pickup_time:
                add(Anomaly("trip", tid, "Invalid timestamp", "Drop time is before pickup time"))
            if t.pickup_time and t.pickup_time < t.request_time:
                add(Anomaly("trip", tid, "Invalid timestamp", "Pickup time is before request time"))
            duration = t.calculate_duration()
            if duration is not None and duration > th.max_duration_min:
                add(Anomaly("trip", tid, "Extremely long trip", f"{duration:.0f} min (limit {th.max_duration_min:g})"))
            if fence is not None and t.fare and t.fare > fence:
                add(Anomaly("trip", tid, "Unusual fare", f"Fare {t.fare:g} exceeds fence {fence:.0f}"))

    # ---------------- drivers ----------------
    def _detect_drivers(self, th: AnomalyThresholds, report: AnomalyReport) -> None:
        stats = self._drivers.all_stats()
        add = report.driver_anomalies.append
        counts = [s.total_trips for s in stats.values() if s.total_trips > 0]
        fence = _upper_fence(counts, th.trip_count_iqr_multiplier)
        report.trip_count_fence = fence
        util = self._util.utilization_map() if self._data.has_activity else {}

        for did, s in sorted(stats.items()):
            if s.total_trips >= th.min_trips and s.cancellation_rate / 100 > th.cancel_rate:
                add(Anomaly("driver", did, "High cancellation rate",
                            f"Cancellation rate {s.cancellation_rate:.1f}% over {s.total_trips} trips"))
            if did in util and util[did] < th.low_utilization:
                add(Anomaly("driver", did, "Low utilization", f"Utilization {util[did] * 100:.1f}%"))
            if fence is not None and s.total_trips > fence:
                add(Anomaly("driver", did, "Unusually high trip count", f"{s.total_trips} trips (fence {fence:.0f})"))
            if s.rating is not None and s.rating < th.low_rating:
                add(Anomaly("driver", did, "Low rating", f"Rating {s.rating:.1f}"))
