"""Central place for every tunable value and label used across the application."""
import re

# ---- CSV schemas (headers are normalised to lower-case before comparison) ----
DRIVER_COLUMNS = ["driver_id", "driver_name", "city", "vehicle_type", "rating", "status"]
TRIP_COLUMNS = [
    "trip_id", "driver_id", "rider_id", "city", "pickup_zone", "drop_zone",
    "request_time", "pickup_time", "drop_time", "distance_km", "fare",
    "status", "cancellation_reason",
]
ACTIVITY_COLUMNS = ["driver_id", "timestamp", "status"]

# ---- Domain vocabularies ----
TRIP_STATUSES = {"completed": "Completed", "cancelled": "Cancelled", "canceled": "Cancelled"}
DRIVER_STATUSES = {"active": "Active", "inactive": "Inactive"}
ACTIVITY_STATUSES = {"online": "Online", "busy": "Busy", "idle": "Idle", "offline": "Offline"}
UNKNOWN = "Unknown"
UNSPECIFIED_REASON = "Unspecified"

# ---- ID formats: one or more letters followed by digits (D101, T1001, R2044) ----
ID_PATTERN = re.compile(r"^[A-Za-z]+\d+$")

# ---- Upload limits ----
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_VALIDATION_ROWS_SHOWN = 500

# ---- Demand time slots: (label, start_hour inclusive, end_hour exclusive) ----
TIME_SLOTS = [
    ("00–03", 0, 3),
    ("03–06", 3, 6),
    ("06–09", 6, 9),
    ("09–12", 9, 12),
    ("12–15", 12, 15),
    ("15–18", 15, 18),
    ("18–21", 18, 21),
    ("21–00", 21, 24),
]

# ---- Utilisation (fractions of online time) ----
HIGH_UTILIZATION = 0.50
LOW_UTILIZATION = 0.35
MAX_SEGMENT_HOURS = 12          # an activity state lasting longer than this is treated as a missing logout

# ---- Idle-time analysis ----
DEFAULT_IDLE_THRESHOLD_MIN = 30
DEFAULT_IDLE_WINDOW_MIN = 360   # gaps longer than this are treated as off-shift, not idle

# ---- Anomaly thresholds ----
MAX_TRIP_DURATION_MIN = 180
FARE_IQR_MULTIPLIER = 3.0       # "far-out" fence for unusual fares
DRIVER_CANCEL_RATE = 0.30
DRIVER_MIN_TRIPS_FOR_RATE = 5
DRIVER_LOW_UTILIZATION = 0.35
TRIP_COUNT_IQR_MULTIPLIER = 1.5
DRIVER_LOW_RATING = 3.2

# ---- Insights ----
INSIGHT_UTILIZATION_CUTOFF = 0.50
ZONE_MIN_REQUESTS_FOR_RATE = 20  # avoid ranking tiny zones by cancellation rate

# ---- Human-readable validation messages: {n} is the number of affected rows ----
ISSUE_LABELS = {
    ("drivers", "missing_value"): "{n} driver rows have a missing value",
    ("drivers", "invalid_id"): "{n} driver rows have an invalid driver ID",
    ("drivers", "duplicate_id"): "{n} driver rows repeat an earlier driver ID",
    ("drivers", "invalid_rating"): "{n} drivers have a missing or invalid rating",
    ("drivers", "invalid_status"): "{n} drivers have an unrecognised status",
    ("trips", "missing_value"): "{n} trips contain a missing value",
    ("trips", "invalid_id"): "{n} trips contain an invalid trip, driver or rider ID",
    ("trips", "duplicate_id"): "{n} trips repeat an earlier trip ID",
    ("trips", "invalid_status"): "{n} trips have an unrecognised status",
    ("trips", "invalid_timestamp"): "{n} trips contain an unreadable timestamp",
    ("trips", "missing_pickup"): "{n} completed trips are missing a pickup timestamp",
    ("trips", "missing_drop"): "{n} completed trips are missing a drop timestamp",
    ("trips", "invalid_duration"): "{n} trips have a drop time before the pickup time",
    ("trips", "negative_fare"): "{n} trips contain a negative fare",
    ("trips", "invalid_number"): "{n} trips contain a non-numeric fare or distance",
    ("trips", "negative_distance"): "{n} trips contain a negative distance",
    ("trips", "unknown_driver"): "{n} trips reference unknown driver IDs",
    ("activity", "invalid_id"): "{n} activity rows have an invalid driver ID",
    ("activity", "invalid_timestamp"): "{n} activity rows have an unreadable timestamp",
    ("activity", "invalid_status"): "{n} activity rows have an unrecognised status",
    ("activity", "unknown_driver"): "{n} activity rows reference unknown driver IDs",
    ("activity", "duplicate_record"): "{n} activity rows are exact duplicates",
    ("activity", "missing_value"): "{n} activity rows have a missing value",
}
