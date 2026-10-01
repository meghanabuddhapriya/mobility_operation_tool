from datetime import datetime
from typing import Optional

from utils.helpers import make_zone_id, safe_div


class Trip:
    """A single ride request, completed or cancelled."""

    def __init__(self, trip_id: str, driver_id: Optional[str], rider_id: Optional[str], city: str,
                 pickup_zone: str, drop_zone: str, request_time: datetime,
                 pickup_time: Optional[datetime], drop_time: Optional[datetime],
                 distance_km: Optional[float], fare: Optional[float], status: str,
                 cancellation_reason: str = ""):
        self._trip_id = trip_id
        self._driver_id = driver_id
        self._rider_id = rider_id
        self._city = city
        self._pickup_zone = pickup_zone
        self._drop_zone = drop_zone
        self._request_time = request_time
        self._pickup_time = pickup_time
        self._drop_time = drop_time
        self._distance_km = distance_km
        self._fare = fare
        self._status = status
        self._cancellation_reason = cancellation_reason

    trip_id = property(lambda self: self._trip_id)
    driver_id = property(lambda self: self._driver_id)
    rider_id = property(lambda self: self._rider_id)
    city = property(lambda self: self._city)
    pickup_zone = property(lambda self: self._pickup_zone)
    drop_zone = property(lambda self: self._drop_zone)
    request_time = property(lambda self: self._request_time)
    pickup_time = property(lambda self: self._pickup_time)
    drop_time = property(lambda self: self._drop_time)
    distance_km = property(lambda self: self._distance_km)
    fare = property(lambda self: self._fare)
    status = property(lambda self: self._status)
    cancellation_reason = property(lambda self: self._cancellation_reason)

    @property
    def zone_id(self) -> str:
        return make_zone_id(self._city, self._pickup_zone)

    def is_completed(self) -> bool:
        return self._status == "Completed"

    def is_cancelled(self) -> bool:
        return self._status == "Cancelled"

    def calculate_duration(self) -> Optional[float]:
        """Trip duration in minutes (pickup -> drop); None when timing is missing or inconsistent."""
        if self._pickup_time is None or self._drop_time is None:
            return None
        minutes = (self._drop_time - self._pickup_time).total_seconds() / 60
        return minutes if minutes >= 0 else None

    def calculate_fare_per_km(self) -> Optional[float]:
        if self._fare is None or self._distance_km is None or self._distance_km <= 0:
            return None
        return safe_div(self._fare, self._distance_km)

    @property
    def revenue(self) -> float:
        """Money earned: fare of a completed trip with a positive fare; otherwise 0."""
        if self.is_completed() and self._fare is not None and self._fare > 0:
            return self._fare
        return 0.0

    def to_dict(self) -> dict:
        fmt = lambda d: d.strftime("%Y-%m-%d %H:%M:%S") if d else ""
        duration = self.calculate_duration()
        return {
            "trip_id": self._trip_id, "driver_id": self._driver_id or "", "rider_id": self._rider_id or "",
            "city": self._city, "pickup_zone": self._pickup_zone, "drop_zone": self._drop_zone,
            "request_time": fmt(self._request_time), "pickup_time": fmt(self._pickup_time),
            "drop_time": fmt(self._drop_time), "distance_km": self._distance_km, "fare": self._fare,
            "status": self._status, "cancellation_reason": self._cancellation_reason,
            "duration_min": round(duration, 1) if duration is not None else None,
        }

    def __repr__(self) -> str:
        return f"Trip({self._trip_id!r}, {self._status!r}, driver={self._driver_id!r})"
