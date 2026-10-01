from typing import Optional


class Driver:
    """A driver on the platform. Attributes are read-only properties (encapsulation)."""

    def __init__(self, driver_id: str, name: str, city: str, vehicle_type: str,
                 rating: Optional[float], status: str):
        self._driver_id = driver_id
        self._name = name
        self._city = city
        self._vehicle_type = vehicle_type
        self._rating = rating
        self._status = status

    driver_id = property(lambda self: self._driver_id)
    name = property(lambda self: self._name)
    city = property(lambda self: self._city)
    vehicle_type = property(lambda self: self._vehicle_type)
    rating = property(lambda self: self._rating)
    status = property(lambda self: self._status)

    def is_active(self) -> bool:
        return self._status == "Active"

    def get_profile(self) -> dict:
        return {
            "driver_id": self._driver_id, "name": self._name, "city": self._city,
            "vehicle_type": self._vehicle_type, "rating": self._rating, "status": self._status,
        }

    def __repr__(self) -> str:
        return f"Driver({self._driver_id!r}, {self._name!r}, {self._city!r}, {self._status!r})"
