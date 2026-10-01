"""Reads uploaded CSV text, validates it, and builds model objects into a Dataset."""
import csv
import io
from typing import List, Optional, Tuple

from models import Driver, DriverActivity, Trip
from utils.constants import ACTIVITY_COLUMNS, DRIVER_COLUMNS, TRIP_COLUMNS

from .dataset import Dataset
from .validation_service import DataValidator, Row, ValidationReport


def decode_bytes(raw: bytes) -> str:
    """Decode an uploaded file. UTF-8 (with/without BOM) first, then Latin-1; reject binary files."""
    if b"\x00" in raw:
        raise ValueError("The file looks binary, not a CSV text file.")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


class DataLoader:
    def __init__(self, validator: Optional[DataValidator] = None):
        self._validator = validator or DataValidator()

    # ---- CSV -> list of (line_number, row-dict) with normalised headers ----
    @staticmethod
    def read_rows(text: str, dataset: str, required: List[str], report: ValidationReport) -> Optional[List[Row]]:
        if text is None or not text.strip():
            report.add_fatal(f"{dataset.capitalize()} file is empty.")
            return None
        try:
            reader = csv.reader(io.StringIO(text.lstrip("\ufeff")))
            header = [h.strip().lower() for h in next(reader, [])]
            missing = [c for c in required if c not in header]
            if missing:
                report.add_fatal(f"{dataset.capitalize()} file is missing required column(s): {', '.join(missing)}.")
                return None
            rows: List[Row] = []
            for cells in reader:
                if not any(c.strip() for c in cells):
                    continue                                    # ignore blank lines
                rows.append((reader.line_num, {h: (cells[i] if i < len(cells) else "") for i, h in enumerate(header)}))
        except csv.Error as exc:
            report.add_fatal(f"{dataset.capitalize()} file could not be parsed as CSV ({exc}).")
            return None
        if not rows:
            report.add_fatal(f"{dataset.capitalize()} file has a header but no data rows.")
            return None
        return rows

    def load(self, drivers_text: str, trips_text: str, activity_text: Optional[str] = None
             ) -> Tuple[Optional[Dataset], ValidationReport]:
        """Returns (dataset, report). dataset is None when a fatal problem blocks loading."""
        report = ValidationReport()
        driver_rows = self.read_rows(drivers_text, "drivers", DRIVER_COLUMNS, report)
        trip_rows = self.read_rows(trips_text, "trips", TRIP_COLUMNS, report)
        activity_rows = None
        if activity_text is not None and activity_text.strip():
            activity_rows = self.read_rows(activity_text, "activity", ACTIVITY_COLUMNS, report)
        if report.has_fatal:
            return None, report

        clean_drivers = self._validator.validate_drivers(driver_rows, report)
        if not clean_drivers:
            report.add_fatal("No valid driver rows were found in the drivers file.")
            return None, report
        known = {d["driver_id"] for d in clean_drivers}
        clean_trips = self._validator.validate_trips(trip_rows, known, report)
        if not clean_trips:
            report.add_fatal("No valid trip rows were found in the trips file.")
            return None, report
        clean_activity = self._validator.validate_activity(activity_rows, known, report) if activity_rows else []

        data = Dataset()
        for d in clean_drivers:
            data.add_driver(Driver(d["driver_id"], d["name"], d["city"], d["vehicle_type"], d["rating"], d["status"]))
        for t in clean_trips:
            data.add_trip(Trip(**t))
        for a in clean_activity:
            data.add_activity(DriverActivity(a["driver_id"], a["timestamp"], a["status"]))
        data.finalize()
        return data, report
