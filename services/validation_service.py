"""Row-level validation. Produces a ValidationReport and clean, typed dictionaries.

Policy: rows whose *key fields* cannot be trusted (ID, status, request time) are dropped;
everything else is kept and flagged so the anomaly module can surface it.
"""
from collections import Counter, OrderedDict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

from utils.constants import (ACTIVITY_STATUSES, DRIVER_STATUSES, ISSUE_LABELS, TRIP_STATUSES,
                             UNKNOWN, UNSPECIFIED_REASON)
from utils.helpers import is_valid_id, parse_float, parse_timestamp

Row = Tuple[int, Dict[str, str]]


@dataclass(frozen=True)
class ValidationIssue:
    dataset: str
    line: int
    record_id: str
    category: str
    message: str
    action: str          # "kept" or "dropped"


class ValidationReport:
    def __init__(self):
        self.issues: List[ValidationIssue] = []
        self.fatal: List[str] = []
        self.row_counts: "OrderedDict[str, List[int]]" = OrderedDict()   # dataset -> [read, accepted]

    def add(self, dataset, line, record_id, category, message, action="kept") -> None:
        self.issues.append(ValidationIssue(dataset, line, record_id or "", category, message, action))

    def add_fatal(self, message: str) -> None:
        self.fatal.append(message)

    @property
    def has_fatal(self) -> bool:
        return bool(self.fatal)

    def set_counts(self, dataset: str, read: int, accepted: int) -> None:
        self.row_counts[dataset] = [read, accepted]

    def counts(self) -> "OrderedDict[Tuple[str, str], int]":
        """Distinct affected rows per (dataset, category), largest first."""
        rows: Dict[Tuple[str, str], Set[int]] = {}
        for i in self.issues:
            rows.setdefault((i.dataset, i.category), set()).add(i.line)
        ordered = sorted(rows.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        return OrderedDict((k, len(v)) for k, v in ordered)

    def summary_lines(self) -> List[str]:
        lines = []
        for name, (read, accepted) in self.row_counts.items():
            lines.append(f"{name.capitalize()} dataset loaded: {accepted} of {read} rows accepted")
        for (dataset, category), n in self.counts().items():
            template = ISSUE_LABELS.get((dataset, category), "{n} " + dataset + " rows: " + category)
            lines.append(_singular(template.format(n=n)) if n == 1 else template.format(n=n))
        return lines

    def filtered(self, dataset: Optional[str] = None, category: Optional[str] = None) -> List[ValidationIssue]:
        return [i for i in self.issues
                if (not dataset or i.dataset == dataset) and (not category or i.category == category)]

    @property
    def dropped_rows(self) -> int:
        return len({(i.dataset, i.line) for i in self.issues if i.action == "dropped"})


_SINGULAR = [("trips contain", "trip contains"), ("trips are", "trip is"), ("trips have", "trip has"),
             ("trips reference", "trip references"), ("trips repeat", "trip repeats"), ("rows have", "row has"),
             ("rows repeat", "row repeats"), ("rows are", "row is"), ("rows reference", "row references"),
             ("drivers have", "driver has")]


def _singular(text: str) -> str:
    """'1 trips contain…' -> '1 trip contains…' (only used when the count is exactly one)."""
    for plural, singular in _SINGULAR:
        if plural in text:
            return text.replace(plural, singular, 1)
    return text


def _get(row: Dict[str, str], col: str) -> str:
    return (row.get(col) or "").strip()


class DataValidator:
    """Validates raw CSV rows for each of the three datasets."""

    # ---------------- drivers ----------------
    def validate_drivers(self, rows: Iterable[Row], report: ValidationReport) -> List[dict]:
        clean, seen = [], set()
        total = 0
        for line, row in rows:
            total += 1
            did = _get(row, "driver_id")
            if not did:
                report.add("drivers", line, "", "missing_value", "driver_id is empty", "dropped"); continue
            if not is_valid_id(did):
                report.add("drivers", line, did, "invalid_id", f"'{did}' is not a valid driver ID", "dropped"); continue
            if did in seen:
                report.add("drivers", line, did, "duplicate_id", "Driver ID already seen", "dropped"); continue
            seen.add(did)

            def text(col):
                value = _get(row, col)
                if not value:
                    report.add("drivers", line, did, "missing_value", f"{col} is empty")
                    return UNKNOWN
                return value

            rating = None
            raw_rating = _get(row, "rating")
            try:
                rating = parse_float(raw_rating)
                if rating is None or not (0 <= rating <= 5):
                    raise ValueError
            except ValueError:
                rating = None
                report.add("drivers", line, did, "invalid_rating", f"rating '{raw_rating}' is missing or outside 0–5")

            raw_status = _get(row, "status")
            status = DRIVER_STATUSES.get(raw_status.lower())
            if status is None:
                report.add("drivers", line, did, "invalid_status", f"status '{raw_status}' is not Active/Inactive")
                status = raw_status.title() if raw_status else UNKNOWN

            clean.append({"driver_id": did, "name": text("driver_name"), "city": text("city"),
                          "vehicle_type": text("vehicle_type"), "rating": rating, "status": status})
        report.set_counts("drivers", total, len(clean))
        return clean

    # ---------------- trips ----------------
    def validate_trips(self, rows: Iterable[Row], known_driver_ids: Set[str], report: ValidationReport) -> List[dict]:
        clean, seen = [], set()
        total = 0
        for line, row in rows:
            total += 1
            tid = _get(row, "trip_id")
            if not tid:
                report.add("trips", line, "", "missing_value", "trip_id is empty", "dropped"); continue
            if not is_valid_id(tid):
                report.add("trips", line, tid, "invalid_id", f"'{tid}' is not a valid trip ID", "dropped"); continue
            if tid in seen:
                report.add("trips", line, tid, "duplicate_id", "Trip ID already seen", "dropped"); continue

            raw_status = _get(row, "status")
            status = TRIP_STATUSES.get(raw_status.lower())
            if status is None:
                report.add("trips", line, tid, "invalid_status",
                           f"status '{raw_status}' is not Completed/Cancelled", "dropped"); continue
            completed = status == "Completed"

            try:
                request_time = parse_timestamp(_get(row, "request_time"))
            except ValueError:
                report.add("trips", line, tid, "invalid_timestamp",
                           f"request_time '{_get(row, 'request_time')}' is unreadable", "dropped"); continue
            if request_time is None:
                report.add("trips", line, tid, "missing_value", "request_time is empty", "dropped"); continue

            seen.add(tid)

            # --- identifiers ---
            driver_id = _get(row, "driver_id")
            if not driver_id:
                driver_id = None
                if completed:
                    report.add("trips", line, tid, "missing_value", "driver_id is empty on a completed trip")
            elif not is_valid_id(driver_id):
                report.add("trips", line, tid, "invalid_id", f"driver_id '{driver_id}' is malformed")
                driver_id = None
            elif driver_id not in known_driver_ids:
                report.add("trips", line, tid, "unknown_driver", f"driver {driver_id} is not in the drivers file")

            rider_id = _get(row, "rider_id")
            if not rider_id:
                rider_id = None
                report.add("trips", line, tid, "missing_value", "rider_id is empty")
            elif not is_valid_id(rider_id):
                report.add("trips", line, tid, "invalid_id", f"rider_id '{rider_id}' is malformed")
                rider_id = None

            # --- places ---
            city = _get(row, "city")
            if not city:
                city = UNKNOWN
                report.add("trips", line, tid, "missing_value", "city is empty")
            pickup_zone = _get(row, "pickup_zone")
            if not pickup_zone:
                pickup_zone = UNKNOWN
                report.add("trips", line, tid, "missing_value", "pickup_zone is empty")
            drop_zone = _get(row, "drop_zone")
            if not drop_zone:
                drop_zone = UNKNOWN
                if completed:
                    report.add("trips", line, tid, "missing_value", "drop_zone is empty on a completed trip")

            # --- timestamps ---
            times = {}
            for col in ("pickup_time", "drop_time"):
                raw = _get(row, col)
                try:
                    times[col] = parse_timestamp(raw)
                except ValueError:
                    times[col] = None
                    report.add("trips", line, tid, "invalid_timestamp", f"{col} '{raw}' is unreadable")
                    continue
                if times[col] is None and completed:
                    key = "missing_pickup" if col == "pickup_time" else "missing_drop"
                    report.add("trips", line, tid, key, f"{col} is empty on a completed trip")
            if times["pickup_time"] and times["drop_time"] and times["drop_time"] < times["pickup_time"]:
                report.add("trips", line, tid, "invalid_duration", "drop_time is earlier than pickup_time")

            # --- numbers ---
            nums = {}
            for col in ("distance_km", "fare"):
                raw = _get(row, col)
                try:
                    nums[col] = parse_float(raw)
                except ValueError:
                    nums[col] = None
                    report.add("trips", line, tid, "invalid_number", f"{col} '{raw}' is not a number")
                    continue
                if nums[col] is None and completed:
                    report.add("trips", line, tid, "missing_value", f"{col} is empty on a completed trip")
            if nums["fare"] is not None and nums["fare"] < 0:
                report.add("trips", line, tid, "negative_fare", f"fare {nums['fare']:g} is negative")
            if nums["distance_km"] is not None and nums["distance_km"] < 0:
                report.add("trips", line, tid, "negative_distance", f"distance {nums['distance_km']:g} is negative")

            reason = ""
            if not completed:
                reason = _get(row, "cancellation_reason")
                if not reason:
                    reason = UNSPECIFIED_REASON
                    report.add("trips", line, tid, "missing_value", "cancellation_reason is empty on a cancelled trip")

            clean.append({
                "trip_id": tid, "driver_id": driver_id, "rider_id": rider_id, "city": city,
                "pickup_zone": pickup_zone, "drop_zone": drop_zone, "request_time": request_time,
                "pickup_time": times["pickup_time"], "drop_time": times["drop_time"],
                "distance_km": nums["distance_km"], "fare": nums["fare"], "status": status,
                "cancellation_reason": reason,
            })
        report.set_counts("trips", total, len(clean))
        return clean

    # ---------------- driver activity ----------------
    def validate_activity(self, rows: Iterable[Row], known_driver_ids: Set[str], report: ValidationReport) -> List[dict]:
        clean, seen = [], set()
        total = 0
        for line, row in rows:
            total += 1
            did = _get(row, "driver_id")
            if not did:
                report.add("activity", line, "", "missing_value", "driver_id is empty", "dropped"); continue
            if not is_valid_id(did):
                report.add("activity", line, did, "invalid_id", f"'{did}' is not a valid driver ID", "dropped"); continue
            if did not in known_driver_ids:
                report.add("activity", line, did, "unknown_driver", "Driver not in drivers file", "dropped"); continue
            status = ACTIVITY_STATUSES.get(_get(row, "status").lower())
            if status is None:
                report.add("activity", line, did, "invalid_status",
                           f"status '{_get(row, 'status')}' is not Online/Busy/Idle/Offline", "dropped"); continue
            try:
                moment = parse_timestamp(_get(row, "timestamp"))
            except ValueError:
                report.add("activity", line, did, "invalid_timestamp",
                           f"timestamp '{_get(row, 'timestamp')}' is unreadable", "dropped"); continue
            if moment is None:
                report.add("activity", line, did, "missing_value", "timestamp is empty", "dropped"); continue
            key = (did, moment, status)
            if key in seen:
                report.add("activity", line, did, "duplicate_record", "Identical event already recorded", "dropped"); continue
            seen.add(key)
            clean.append({"driver_id": did, "timestamp": moment, "status": status})
        report.set_counts("activity", total, len(clean))
        return clean
