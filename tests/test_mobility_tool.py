"""Test suite: normal + edge scenarios. Run with:  python -m unittest discover -s tests -v"""
import io
import os
import random
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app                                                    # noqa: E402
from models import Driver, DriverActivity, Trip                               # noqa: E402
from services.analytics_engine import AnalyticsEngine                         # noqa: E402
from services.anomaly_detector import AnomalyThresholds                       # noqa: E402
from services.data_loader import DataLoader, decode_bytes                     # noqa: E402
from services.utilization_analyzer import UtilizationThresholds               # noqa: E402
from utils.helpers import inr, make_zone_id, parse_timestamp, slot_for        # noqa: E402
from utils.topk import TopKHeap                                               # noqa: E402

DRIVER_HEADER = "driver_id,driver_name,city,vehicle_type,rating,status"
TRIP_HEADER = ("trip_id,driver_id,rider_id,city,pickup_zone,drop_zone,request_time,pickup_time,drop_time,"
               "distance_km,fare,status,cancellation_reason")
ACT_HEADER = "driver_id,timestamp,status"

DRIVERS = [DRIVER_HEADER, "D1,Asha,Bangalore,Sedan,4.5,Active", "D2,Ben,Bangalore,SUV,3.0,Active",
           "D3,Chen,Mumbai,Hatchback,4.0,Inactive"]


def trips_csv(evening="19", extra=()):
    rows = [
        TRIP_HEADER,
        "T1,D1,R1,Bangalore,Koramangala,Indiranagar,2023-10-01 08:00:00,2023-10-01 08:10:00,2023-10-01 08:40:00,10,200,Completed,",
        "T2,D1,R2,Bangalore,Koramangala,Indiranagar,2023-10-01 09:00:00,2023-10-01 09:10:00,2023-10-01 09:50:00,5,100,Completed,",
        f"T3,D1,R1,Bangalore,Koramangala,Indiranagar,2023-10-01 {evening}:00:00,,,0,0,Cancelled,Driver Cancelled",
        f"T4,D2,R3,Bangalore,Indiranagar,Koramangala,2023-10-01 {evening}:30:00,2023-10-01 {evening}:40:00,2023-10-01 {int(evening)}:59:00,4,80,Completed,",
        f"T5,D2,R3,Bangalore,Indiranagar,Koramangala,2023-10-01 {evening}:50:00,,,0,0,Cancelled,Rider Cancelled",
        "T6,D3,R4,Mumbai,Bandra,Juhu,2023-10-02 07:00:00,2023-10-02 07:05:00,2023-10-02 07:35:00,8,160,Completed,",
    ]
    return "\n".join(rows + list(extra))


ACTIVITY = "\n".join([
    ACT_HEADER,
    "D1,2023-10-01 08:00:00,Online", "D1,2023-10-01 09:00:00,Busy", "D1,2023-10-01 11:00:00,Idle", "D1,2023-10-01 12:00:00,Offline",
    "D2,2023-10-01 10:00:00,Online", "D2,2023-10-01 10:30:00,Idle", "D2,2023-10-01 11:00:00,Offline",
])


def load(drivers=DRIVERS, trips=None, activity=ACTIVITY):
    d = "\n".join(drivers) if isinstance(drivers, list) else drivers
    return DataLoader().load(d, trips if trips is not None else trips_csv(), activity)


def engine(**kw):
    data, report = load(**kw)
    assert data is not None, report.fatal
    return AnalyticsEngine(data, report)


# =============================================================== validation / loading
class ValidationTests(unittest.TestCase):
    def test_empty_file_is_fatal(self):
        data, report = load(trips="")
        self.assertIsNone(data)
        self.assertIn("Trips file is empty.", report.fatal)

    def test_header_only_file_is_fatal(self):
        data, report = load(trips=TRIP_HEADER)
        self.assertIsNone(data)
        self.assertTrue(any("no data rows" in m for m in report.fatal))

    def test_missing_columns_are_named(self):
        data, report = load(trips="trip_id,driver_id\nT1,D1")
        self.assertIsNone(data)
        self.assertTrue(any("fare" in m and "missing required column" in m for m in report.fatal))

    def test_headers_are_case_insensitive_and_trimmed(self):
        header = " Driver_ID , Driver_Name,City,Vehicle_Type,Rating,Status"
        data, report = load(drivers=[header] + DRIVERS[1:])
        self.assertIsNotNone(data)
        self.assertEqual(len(data.drivers), 3)

    def test_missing_values_are_flagged_not_fatal(self):
        bad = trips_csv(extra=["T7,D1,,,Koramangala,Indiranagar,2023-10-03 10:00:00,2023-10-03 10:05:00,2023-10-03 10:30:00,5,90,Completed,"])
        data, report = load(trips=bad)
        cats = {i.category for i in report.issues if i.record_id == "T7"}
        self.assertIn("missing_value", cats)
        self.assertIn("T7", data.trips)                     # kept, but flagged
        self.assertEqual(data.trips["T7"].city, "Unknown")

    def test_invalid_ids_dropped_or_cleared(self):
        bad = trips_csv(extra=["BAD-ID,D1,R1,Bangalore,A,B,2023-10-03 10:00:00,,,0,0,Cancelled,Other",
                               "T8,12345,R1,Bangalore,A,B,2023-10-03 10:00:00,,,0,0,Cancelled,Other"])
        data, report = load(trips=bad)
        self.assertNotIn("BAD-ID", data.trips)
        self.assertIsNone(data.trips["T8"].driver_id)       # malformed driver id is cleared
        self.assertGreaterEqual(report.counts()[("trips", "invalid_id")], 2)

    def test_duplicate_ids_keep_first(self):
        dup_t = trips_csv(extra=["T1,D2,R9,Bangalore,X,Y,2023-10-05 10:00:00,,,0,0,Cancelled,Other"])
        data, report = load(trips=dup_t, drivers=DRIVERS + ["D1,Clone,Delhi,SUV,4,Active"])
        self.assertEqual(data.trips["T1"].driver_id, "D1")
        self.assertEqual(data.drivers["D1"].name, "Asha")
        self.assertEqual(report.counts()[("trips", "duplicate_id")], 1)
        self.assertEqual(report.counts()[("drivers", "duplicate_id")], 1)

    def test_invalid_and_missing_timestamps(self):
        bad = trips_csv(extra=[
            "T7,D1,R1,Bangalore,A,B,not-a-date,,,0,0,Cancelled,Other",                                            # dropped
            "T8,D1,R1,Bangalore,A,B,2023-10-03 10:00:00,garbage,2023-10-03 10:30:00,5,90,Completed,",              # kept
            "T9,D1,R1,Bangalore,A,B,2023-10-03 10:00:00,,2023-10-03 10:30:00,5,90,Completed,"])                    # missing pickup
        data, report = load(trips=bad)
        self.assertNotIn("T7", data.trips)
        self.assertIsNone(data.trips["T8"].pickup_time)
        counts = report.counts()
        self.assertEqual(counts[("trips", "invalid_timestamp")], 2)
        self.assertEqual(counts[("trips", "missing_pickup")], 1)

    def test_negative_and_non_numeric_values(self):
        bad = trips_csv(extra=[
            "T7,D1,R1,Bangalore,A,B,2023-10-03 10:00:00,2023-10-03 10:05:00,2023-10-03 10:30:00,5,-90,Completed,",
            "T8,D1,R1,Bangalore,A,B,2023-10-03 10:00:00,2023-10-03 10:05:00,2023-10-03 10:30:00,-5,90,Completed,",
            "T9,D1,R1,Bangalore,A,B,2023-10-03 10:00:00,2023-10-03 10:05:00,2023-10-03 10:30:00,abc,90,Completed,"])
        _, report = load(trips=bad)
        c = report.counts()
        self.assertEqual(c[("trips", "negative_fare")], 1)
        self.assertEqual(c[("trips", "negative_distance")], 1)
        self.assertEqual(c[("trips", "invalid_number")], 1)

    def test_drop_before_pickup_and_unknown_driver(self):
        bad = trips_csv(extra=["T7,D9,R1,Bangalore,A,B,2023-10-03 10:00:00,2023-10-03 10:30:00,2023-10-03 10:00:00,5,90,Completed,"])
        data, report = load(trips=bad)
        self.assertIsNone(data.trips["T7"].calculate_duration())
        self.assertEqual(report.counts()[("trips", "invalid_duration")], 1)
        self.assertEqual(report.counts()[("trips", "unknown_driver")], 1)

    def test_invalid_status_row_dropped(self):
        bad = trips_csv(extra=["T7,D1,R1,Bangalore,A,B,2023-10-03 10:00:00,,,0,0,Pending,"])
        data, report = load(trips=bad)
        self.assertNotIn("T7", data.trips)
        self.assertEqual(report.dropped_rows, 1)

    def test_activity_problems_are_dropped_and_counted(self):
        act = ACTIVITY + "\nD1,2023-10-01 08:00:00,Online\nD9,2023-10-01 08:00:00,Online\nD1,bad,Busy\nD1,2023-10-01 13:00:00,Flying"
        data, report = load(activity=act)
        c = report.counts()
        self.assertEqual(c[("activity", "duplicate_record")], 1)
        self.assertEqual(c[("activity", "unknown_driver")], 1)
        self.assertEqual(c[("activity", "invalid_timestamp")], 1)
        self.assertEqual(c[("activity", "invalid_status")], 1)
        self.assertEqual(len(data.activity), 7)

    def test_summary_grammar_for_single_row(self):
        _, report = load(trips=trips_csv(extra=["T7,D1,R1,Bangalore,A,B,2023-10-03 10:00:00,garbage,,5,90,Completed,"]))
        self.assertIn("1 trip contains an unreadable timestamp", report.summary_lines())

    def test_binary_upload_rejected(self):
        with self.assertRaises(ValueError):
            decode_bytes(b"PK\x03\x04\x00\x00binary")

    def test_activity_is_optional(self):
        data, _ = load(activity=None)
        self.assertFalse(data.has_activity)


# =============================================================== models + helpers
class ModelTests(unittest.TestCase):
    def test_driver_behaviour(self):
        d = Driver("D1", "Asha", "Bangalore", "Sedan", 4.5, "Active")
        self.assertTrue(d.is_active())
        self.assertEqual(d.get_profile()["name"], "Asha")
        self.assertFalse(Driver("D2", "B", "C", "V", None, "Inactive").is_active())
        with self.assertRaises(AttributeError):
            d.rating = 1                                     # encapsulated: read-only property

    def test_trip_calculations(self):
        t0 = datetime(2023, 10, 1, 8, 0)
        t = Trip("T1", "D1", "R1", "Bangalore", "A", "B", t0, datetime(2023, 10, 1, 8, 10),
                 datetime(2023, 10, 1, 8, 40), 10.0, 200.0, "Completed")
        self.assertEqual(t.calculate_duration(), 30)
        self.assertEqual(t.calculate_fare_per_km(), 20)
        self.assertEqual(t.revenue, 200)
        self.assertEqual(t.zone_id, "BANGALORE-A")

    def test_trip_edge_cases(self):
        t0 = datetime(2023, 10, 1, 8, 0)
        zero = Trip("T2", "D1", "R1", "C", "A", "B", t0, t0, t0, 0.0, 50.0, "Completed")
        self.assertIsNone(zero.calculate_fare_per_km())
        neg = Trip("T3", "D1", "R1", "C", "A", "B", t0, t0, t0, 5.0, -50.0, "Completed")
        self.assertEqual(neg.revenue, 0)
        cancelled = Trip("T4", None, "R1", "C", "A", "B", t0, None, None, 0.0, 0.0, "Cancelled", "Other")
        self.assertTrue(cancelled.is_cancelled())
        self.assertIsNone(cancelled.calculate_duration())

    def test_activity_sorting_uses_timestamp(self):
        a = DriverActivity("D1", datetime(2023, 1, 2), "Busy")
        b = DriverActivity("D1", datetime(2023, 1, 1), "Online")
        self.assertEqual(sorted([a, b])[0], b)

    def test_time_slot_boundaries(self):
        self.assertEqual(slot_for(datetime(2023, 1, 1, 5, 59)), "03–06")
        self.assertEqual(slot_for(datetime(2023, 1, 1, 6, 0)), "06–09")
        self.assertEqual(slot_for(datetime(2023, 1, 1, 23, 59)), "21–00")

    def test_helpers(self):
        self.assertEqual(inr(1272368), "₹12,72,368")
        self.assertEqual(inr(-450.5, 2), "-₹450.50")
        self.assertEqual(make_zone_id("Bangalore", "HSR Layout"), "BANGALORE-HSR-LAYOUT")
        self.assertIsNone(parse_timestamp("  "))
        with self.assertRaises(ValueError):
            parse_timestamp("31/02/2023 25:61")


# =============================================================== DSA
class TopKTests(unittest.TestCase):
    def test_heap_matches_full_sort(self):
        rng = random.Random(7)
        items = [(f"I{i:03d}", rng.randint(0, 20)) for i in range(300)]      # many ties on purpose
        for k in (1, 5, 17, 300, 500):
            expected = sorted(items, key=lambda x: (-x[1], x[0]))[:k]
            got = TopKHeap(k).extend((i, v, None) for i, v in items).result()
            self.assertEqual([(i, v) for i, v, _ in got], expected)
            expected_low = sorted(items, key=lambda x: (x[1], x[0]))[:k]
            got_low = TopKHeap(k, largest=False).extend((i, v, None) for i, v in items).result()
            self.assertEqual([(i, v) for i, v, _ in got_low], expected_low)

    def test_invalid_k(self):
        for bad in (0, -1, "3", None):
            with self.assertRaises(ValueError):
                TopKHeap(bad)

    def test_empty_input(self):
        self.assertEqual(TopKHeap(3).result(), [])


# =============================================================== analytics on the fixture
class AnalyticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = engine()

    def test_kpis_match_hand_calculation(self):
        k = self.e.trips.kpis()
        self.assertEqual((k["total_drivers"], k["active_drivers"], k["total_riders"]), (3, 2, 4))
        self.assertEqual((k["total_trips"], k["completed_trips"], k["cancelled_trips"]), (6, 4, 2))
        self.assertEqual(k["total_revenue"], 540)
        self.assertEqual(k["avg_fare"], 135)
        self.assertEqual(k["cancellation_rate"], 33.33)
        self.assertEqual(k["avg_distance"], 6.75)
        self.assertEqual(k["avg_duration"], 29.8)               # (30 + 40 + 19 + 30) / 4 = 29.75

    def test_driver_stats(self):
        s = self.e.drivers.stats_for("D1")
        self.assertEqual((s.total_trips, s.completed, s.cancelled), (3, 2, 1))
        self.assertEqual(s.revenue, 300)
        self.assertEqual(s.avg_fare, 150)
        self.assertEqual(s.completion_rate, 66.67)
        self.assertEqual(s.avg_fare_per_km, 20)
        self.assertIsNone(self.e.drivers.stats_for("D404"))

    def test_driver_without_trips_has_zero_rates(self):
        e = engine(drivers=DRIVERS + ["D4,Dev,Delhi,SUV,4.2,Active"])
        s = e.drivers.stats_for("D4")
        self.assertEqual((s.total_trips, s.cancellation_rate, s.avg_fare), (0, 0.0, 0.0))

    def test_zone_stats_and_slots(self):
        z = self.e.zones.stats("BANGALORE-KORAMANGALA")
        self.assertEqual((z["requests"], z["completed"], z["cancelled"], z["revenue"]), (3, 2, 1, 300))
        slots = {s["slot"]: s["requests"] for s in z["slots"]}
        self.assertEqual((slots["06–09"], slots["09–12"], slots["18–21"]), (1, 1, 1))
        self.assertIsNone(self.e.zones.stats("NOWHERE"))

    def test_cancellation_breakdown(self):
        rows = self.e.cancellations.by_reason()
        self.assertEqual([(r["reason"], r["count"]) for r in rows], [("Driver Cancelled", 1), ("Rider Cancelled", 1)])
        by_slot = {r["slot"]: r for r in self.e.cancellations.by_time()}
        self.assertEqual((by_slot["18–21"]["requests"], by_slot["18–21"]["cancelled"]), (3, 2))
        self.assertEqual(self.e.cancellations.by_driver()[0]["cancelled"], 1)

    def test_peak_slot(self):
        self.assertEqual(self.e.trips.peak_slot()["slot"], "18–21")
        self.assertEqual(engine(trips=trips_csv(evening="07")).trips.peak_slot()["slot"], "06–09")

    def test_utilization_from_intervals(self):
        rec = {r.driver_id: r for r in self.e.utilization.records()}
        self.assertEqual((rec["D1"].online_hours, rec["D1"].busy_hours, rec["D1"].idle_hours), (4.0, 2.0, 2.0))
        self.assertAlmostEqual(rec["D1"].utilization, 0.5)
        self.assertEqual(rec["D1"].category, "High")
        self.assertEqual(rec["D2"].category, "Low")
        self.assertNotIn("D3", rec)                                                  # no activity -> not measured

    def test_utilization_thresholds_are_configurable(self):
        strict = self.e.utilization.records(UtilizationThresholds(high=0.9, low=0.6))
        self.assertEqual({r.driver_id: r.category for r in strict}, {"D1": "Low", "D2": "Low"})
        with self.assertRaises(ValueError):
            UtilizationThresholds(high=0.2, low=0.8)

    def test_stale_segment_is_skipped(self):
        act = ACT_HEADER + "\nD1,2023-10-01 08:00:00,Online\nD1,2023-10-03 08:00:00,Busy\nD1,2023-10-03 09:00:00,Offline"
        rec = engine(activity=act).utilization.records()
        self.assertEqual(rec[0].online_hours, 1.0)                                   # 48h "Online" gap ignored
        self.assertEqual(rec[0].skipped_segments, 1)

    def test_idle_gap_detection(self):
        r = self.e.idle.analyze(threshold_min=30, window_min=360)
        self.assertEqual(r.total_significant, 1)                                     # T1 -> T2 : 08:40 -> 09:10 = 30 min
        self.assertEqual((r.gaps[0].prev_trip, r.gaps[0].next_trip, r.gaps[0].minutes), ("T1", "T2", 30.0))
        self.assertEqual(self.e.idle.analyze(31, 360).total_significant, 0)
        self.assertEqual(self.e.idle.analyze(0, 360, driver_id="D1").pairs_examined, 1)

    def test_idle_overlap_and_off_shift(self):
        extra = ["T7,D1,R1,Bangalore,A,B,2023-10-01 09:20:00,2023-10-01 09:30:00,2023-10-01 10:00:00,5,90,Completed,",     # overlaps T2 end 09:50
                 "T8,D1,R1,Bangalore,A,B,2023-10-02 09:00:00,2023-10-02 09:10:00,2023-10-02 09:40:00,5,90,Completed,"]     # next day
        r = engine(trips=trips_csv(extra=extra)).idle.analyze(30, 360, "D1")
        self.assertEqual((r.overlaps, r.off_shift), (1, 1))

    def test_idle_invalid_inputs(self):
        with self.assertRaises(ValueError):
            self.e.idle.analyze(60, 30)
        with self.assertRaises(ValueError):
            self.e.idle.analyze(30, 360, driver_id="NOPE")

    def test_topk_service(self):
        res = self.e.topk.run("driver_completed", "2")
        self.assertEqual([r["id"] for r in res["rows"]], ["D1", "D2"])
        self.assertEqual(res["rows"][0]["value"], 2)
        self.assertIn("Only", self.e.topk.run("rider_trips", 50)["note"])
        for bad_k in ("0", "-3", "abc", "", "5000", None):
            with self.assertRaises(ValueError):
                self.e.topk.run("driver_completed", bad_k)
        with self.assertRaises(ValueError):
            self.e.topk.run("not_a_metric", 5)

    def test_topk_utilization_needs_activity(self):
        with self.assertRaises(ValueError):
            engine(activity=None).topk.run("driver_utilization", 5)

    def test_search_uses_indexes(self):
        s = self.e.search
        self.assertTrue(s.search("driver", " d1 ")["found"])
        self.assertEqual(s.search("trip", "t4")["result"]["trip"]["driver_id"], "D2")
        self.assertEqual(s.search("zone", "koramangala")["result"]["zones"][0]["zone_id"], "BANGALORE-KORAMANGALA")
        self.assertEqual(s.search("rider", "R1")["result"]["trip_count"], 2)
        self.assertFalse(s.search("driver", "D404")["found"])
        for bad in ("", "   "):
            with self.assertRaises(ValueError):
                s.search("driver", bad)
        with self.assertRaises(ValueError):
            s.search("planet", "X")


class AnomalyAndInsightTests(unittest.TestCase):
    EXTRA = [
        "T7,D1,R1,Bangalore,A,B,2023-10-03 10:00:00,2023-10-03 10:30:00,2023-10-03 10:00:00,5,90,Completed,",   # drop < pickup
        "T8,D9,R1,Bangalore,A,B,2023-10-03 10:00:00,2023-10-03 10:05:00,2023-10-03 10:30:00,5,-50,Completed,",  # unknown + negative
        "T9,D1,R1,Bangalore,A,B,2023-10-03 10:00:00,2023-10-03 10:05:00,2023-10-03 10:30:00,0,100,Completed,",  # zero distance
        "T10,D1,R1,Bangalore,A,B,2023-10-03 10:00:00,2023-10-03 10:05:00,2023-10-03 16:05:00,5,100,Completed,", # 360 min
        "T11,D1,R1,Bangalore,A,B,2023-10-03 10:00:00,,,0,0,Cancelled,",                                            # missing reason
    ]

    def test_trip_anomalies_detected(self):
        report = engine(trips=trips_csv(extra=self.EXTRA)).anomalies()
        found = {(a.entity_id, a.category) for a in report.trip_anomalies}
        for expected in [("T7", "Invalid timestamp"), ("T8", "Negative fare"), ("T8", "Unknown driver"),
                         ("T9", "Zero distance"), ("T10", "Extremely long trip")]:
            self.assertIn(expected, found)

    def test_clean_data_has_no_trip_anomalies(self):
        self.assertEqual(engine().anomalies().trip_anomalies, [])

    def test_unusual_fare_uses_iqr_fence(self):
        many = [f"T{100 + i},D1,R1,Bangalore,A,B,2023-10-04 10:00:00,2023-10-04 10:05:00,2023-10-04 10:30:00,5,{90 + (i * 7) % 121},Completed," for i in range(20)]
        many.append("T999,D1,R1,Bangalore,A,B,2023-10-04 10:00:00,2023-10-04 10:05:00,2023-10-04 10:30:00,5,9000,Completed,")
        report = engine(trips=trips_csv(extra=many)).anomalies()
        flagged = [a.entity_id for a in report.trip_anomalies if a.category == "Unusual fare"]
        self.assertEqual(flagged, ["T999"])

    def test_driver_anomalies_and_configurable_thresholds(self):
        e = engine()
        default = {(a.entity_id, a.category) for a in e.anomalies().driver_anomalies}
        self.assertNotIn(("D2", "High cancellation rate"), default)                  # only 2 trips < min_trips
        self.assertIn(("D2", "Low rating"), default)
        self.assertIn(("D2", "Low utilization"), default)
        loose = e.anomalies(AnomalyThresholds(min_trips=2, cancel_rate=0.3))
        self.assertIn(("D2", "High cancellation rate"), {(a.entity_id, a.category) for a in loose.driver_anomalies})

    def test_thresholds_from_args_validation(self):
        self.assertEqual(AnomalyThresholds.from_args({"cancel_rate": "20"}).cancel_rate, 0.2)
        for bad in ({"cancel_rate": "abc"}, {"cancel_rate": "150"}, {"low_rating": "9"}, {"min_trips": "0"}):
            with self.assertRaises(ValueError):
                AnomalyThresholds.from_args(bad)

    def test_insights_are_dynamic(self):
        evening, morning = engine().insights(), engine(trips=trips_csv(evening="07")).insights()
        self.assertTrue(any("18–21" in i for i in evening))
        self.assertTrue(any("06–09" in i for i in morning))
        self.assertTrue(any("Driver Cancelled" in i for i in evening))
        self.assertNotEqual(evening, morning)

    def test_insights_without_activity_skip_utilization(self):
        self.assertFalse(any("utilization" in i for i in engine(activity=None).insights()))


# =============================================================== Flask end-to-end
class FlaskTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def upload(self, drivers="\n".join(DRIVERS), trips=None, activity=ACTIVITY, drivers_name="drivers.csv"):
        data = {"drivers": (io.BytesIO(drivers.encode()), drivers_name), "trips": (io.BytesIO((trips or trips_csv()).encode()), "trips.csv")}
        if activity:
            data["activity"] = (io.BytesIO(activity.encode()), "activity.csv")
        return self.client.post("/upload", data=data, content_type="multipart/form-data")

    def test_pages_redirect_when_no_data(self):
        for path in ("/dashboard", "/drivers", "/zones", "/anomalies", "/insights"):
            self.assertEqual(self.client.get(path).status_code, 302, path)

    def test_upload_flow_shows_dashboard_from_uploaded_data(self):
        r = self.upload()
        self.assertEqual(r.status_code, 302)
        page = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn("₹540", page)                            # revenue from the *uploaded* fixture, not the sample
        self.assertIn("Data validation", page)

    def test_upload_without_required_file_is_rejected_politely(self):
        r = self.client.post("/upload", data={"drivers": (io.BytesIO(b"x"), "d.csv")}, content_type="multipart/form-data", follow_redirects=True)
        self.assertIn("Choose a Trips CSV", r.get_data(as_text=True))

    def test_upload_wrong_extension_and_bad_content(self):
        r = self.upload(drivers_name="drivers.xlsx")
        self.assertEqual(r.status_code, 302)
        r = self.upload(trips="trip_id,fare\nT1,10")
        self.assertEqual(r.status_code, 400)
        self.assertIn("missing required column", r.get_data(as_text=True))

    def test_upload_empty_file(self):
        r = self.upload(drivers="")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Drivers file is empty", r.get_data(as_text=True))

    def test_every_page_renders_with_sample_data(self):
        self.assertEqual(self.client.post("/load-sample").status_code, 302)
        paths = ["/dashboard", "/validation", "/trips", "/drivers?driver_id=D102", "/zones?zone_id=BANGALORE-KORAMANGALA",
                 "/topk?metric=driver_revenue&k=5", "/cancellations?view=zone", "/cancellations?view=time", "/utilization",
                 "/idle?threshold=30&window=360", "/anomalies", "/search?type=driver&q=D102", "/insights", "/api/kpis"]
        for p in paths:
            self.assertEqual(self.client.get(p).status_code, 200, p)

    def test_bad_inputs_are_handled_without_errors(self):
        self.client.post("/load-sample")
        checks = {"/search?type=driver&q=NOPE": "No driver matches", "/search?type=driver&q=": "Enter an ID",
                  "/topk?metric=driver_completed&k=-4": "K must be between", "/topk?metric=driver_completed&k=xyz": "whole number",
                  "/idle?threshold=abc&window=360": "must be a number", "/idle?threshold=60&window=30": "at least as large",
                  "/utilization?high=20&low=80": "thresholds must satisfy", "/anomalies?cancel_rate=oops": "must be a number",
                  "/drivers?driver_id=NOPE": "was not found", "/zones?zone_id=NOPE": "was not found"}
        for path, message in checks.items():
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn(message, r.get_data(as_text=True), path)

    def test_utilization_page_without_activity_file(self):
        self.upload(activity=None)
        self.assertIn("No driver activity file", self.client.get("/utilization").get_data(as_text=True))

    def test_unknown_route_gives_404_page(self):
        self.assertEqual(self.client.get("/nope").status_code, 404)

    def test_reset_clears_data(self):
        self.client.post("/load-sample")
        self.client.post("/reset")
        self.assertEqual(self.client.get("/dashboard").status_code, 302)


if __name__ == "__main__":
    unittest.main()
