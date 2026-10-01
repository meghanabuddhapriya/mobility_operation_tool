"""One reusable aggregation used by driver, zone, city and overall KPIs (single pass, O(n))."""
from dataclasses import dataclass
from typing import Iterable

from models import Trip
from utils.helpers import pct, safe_div


@dataclass
class TripSummary:
    total: int = 0
    completed: int = 0
    cancelled: int = 0
    revenue: float = 0.0
    revenue_trips: int = 0            # completed trips with a positive fare
    fare_distance_sum: float = 0.0    # distance of the revenue trips that have distance > 0
    fare_distance_revenue: float = 0.0
    distance_sum: float = 0.0
    distance_count: int = 0
    duration_sum: float = 0.0
    duration_count: int = 0

    @property
    def completion_rate(self) -> float:
        return pct(self.completed, self.total)

    @property
    def cancellation_rate(self) -> float:
        return pct(self.cancelled, self.total)

    @property
    def avg_fare(self) -> float:
        return safe_div(self.revenue, self.revenue_trips)

    @property
    def avg_distance(self) -> float:
        return safe_div(self.distance_sum, self.distance_count)

    @property
    def avg_duration(self) -> float:
        return safe_div(self.duration_sum, self.duration_count)

    @property
    def avg_fare_per_km(self) -> float:
        return safe_div(self.fare_distance_revenue, self.fare_distance_sum)


def summarize(trips: Iterable[Trip]) -> TripSummary:
    s = TripSummary()
    for t in trips:
        s.total += 1
        if t.is_cancelled():
            s.cancelled += 1
            continue
        s.completed += 1
        if t.revenue > 0:
            s.revenue += t.revenue
            s.revenue_trips += 1
            if t.distance_km and t.distance_km > 0:
                s.fare_distance_revenue += t.revenue
                s.fare_distance_sum += t.distance_km
        if t.distance_km and t.distance_km > 0:
            s.distance_sum += t.distance_km
            s.distance_count += 1
        duration = t.calculate_duration()
        if duration is not None:
            s.duration_sum += duration
            s.duration_count += 1
    return s
