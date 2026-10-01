from datetime import datetime


class DriverActivity:
    """One status-change event in a driver's activity log (Online / Busy / Idle / Offline)."""

    def __init__(self, driver_id: str, timestamp: datetime, status: str):
        self._driver_id = driver_id
        self._timestamp = timestamp
        self._status = status

    driver_id = property(lambda self: self._driver_id)
    timestamp = property(lambda self: self._timestamp)
    status = property(lambda self: self._status)

    def is_online(self) -> bool:
        return self._status != "Offline"

    def __lt__(self, other: "DriverActivity") -> bool:
        return self._timestamp < other._timestamp

    def __repr__(self) -> str:
        return f"DriverActivity({self._driver_id!r}, {self._timestamp:%Y-%m-%d %H:%M}, {self._status!r})"
