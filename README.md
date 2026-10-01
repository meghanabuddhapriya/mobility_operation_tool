# Mobility Marketplace Operations Intelligence Engine

A Flask web application that lets an operations user upload mobility data (drivers, trips, driver activity) and interactively analyse driver and trip performance, zone demand, cancellations, utilization, idle time, anomalies and automatically generated business insights.

Built as a 5-day capstone: **Python OOP + DSA + data processing + Flask**. No pandas, only the Python standard library plus Flask, so every algorithm is visible in the code.

## 1. Problem statement

Operations teams receive raw CSV exports and need quick answers: Which zones lose the most requests? Which drivers are underused or unreliable? When is demand highest? Is the data itself trustworthy? This tool validates the upload, turns rows into objects, runs the analytics with appropriate data structures, and presents the results in a browser.

## 2. Setup and run

Requires Python 3.9+ (developed on 3.12).

```bash
cd mobility_operations_tool
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python app.py                      # or: python python_app.py
# open http://127.0.0.1:5000
```

Click **Load sample data** on the first page, or upload your own three CSVs. To regenerate the sample dataset (seeded, reproducible): `python data/generate_sample_data.py`.

Run the tests: `python -m unittest discover -s tests -v` (56 tests, about 1 second).

Optional environment variables: `PORT` (default 5000), `FLASK_DEBUG=1`, `SECRET_KEY`.

## 3. Application flow

```
Upload CSVs / Sample data
        ↓
DataLoader.read_rows      → header check (case-insensitive), empty-file, missing-column and binary-file guards
        ↓
DataValidator             → row-level checks; drops untrustworthy rows, flags the rest (ValidationReport)
        ↓
Object creation           → Driver, Trip, Zone, DriverActivity  →  Dataset (hash indexes)
        ↓
AnalyticsEngine (facade)  → TripAnalyzer · DriverAnalyzer · ZoneAnalyzer · CancellationAnalyzer
                            UtilizationAnalyzer · IdleTimeAnalyzer · AnomalyDetector · TopKService · SearchService
        ↓
InsightsEngine            → plain-English findings computed from the analyzers
        ↓
Flask routes + Jinja templates → interactive pages
```

| Page | What it does |
|---|---|
| Load data | Upload three CSVs (activity optional) or use sample data; shows fatal errors clearly |
| Dashboard | 12 KPIs, all computed from the loaded data, plus the validation summary and a link to the row-level details |
| Trips | Demand by time slot, city, distance band, hour and day; peak slot |
| Drivers | Pick a driver for a full profile; rankings (most completed, highest revenue, lowest cancellation, highest utilization) and a "requiring attention" list |
| Zones | City/zone selector, KPIs, demand distribution by time slot, top drop zones, cancellation reasons |
| Top-K | Choose one of 8 metrics and K; heap-based ranking |
| Cancellations | Reason summary with tabs: by reason / zone / driver / time |
| Utilization | Online, busy, idle hours and utilization %, with configurable High/Low thresholds |
| Idle time | Consecutive-trip gaps above a configurable threshold |
| Anomalies | Trip and driver anomalies with configurable thresholds |
| Search | Driver, trip, zone (ID or name) and rider lookup via hash indexes |
| Insights | 5 to 7 dynamically generated findings |

## 4. Architecture (separation of responsibilities)

```
mobility_operations_tool/
├── app.py                     Flask app factory + thin routes (parse input → call engine → render)
├── python_app.py              alternative launcher
├── models/                    domain objects: driver.py, trip.py, zone.py, activity.py
├── services/
│   ├── data_loader.py         CSV text → rows → validated dicts → model objects → Dataset
│   ├── validation_service.py  DataValidator + ValidationReport / ValidationIssue
│   ├── dataset.py             object store + hash indexes
│   ├── metrics.py             one reusable O(n) aggregation (TripSummary)
│   ├── driver_analyzer.py  trip_analyzer.py  zone_analyzer.py  cancellation_analyzer.py
│   ├── utilization_analyzer.py    UtilizationAnalyzer + IdleTimeAnalyzer
│   ├── anomaly_detector.py    topk_service.py    search_service.py    insights_engine.py
│   └── analytics_engine.py    facade that wires everything together
├── utils/                     constants.py (all thresholds/labels), helpers.py, topk.py (heap)
├── templates/  static/        Jinja pages and CSS
├── data/                      sample CSVs + seeded generator
└── tests/                     56 unit and end-to-end tests
```

## 5. OOP approach

| Class | Responsibility |
|---|---|
| `Driver`, `Trip`, `Zone`, `DriverActivity` | Domain entities. State is private (`_x`) and exposed through read-only properties (encapsulation). Behaviour lives on the object: `driver.is_active()`, `driver.get_profile()`, `trip.is_completed()`, `trip.calculate_duration()`, `trip.calculate_fare_per_km()`, `trip.revenue`. `Zone` owns the trips requested from it; `DriverActivity` is orderable by timestamp. |
| `Dataset` | Container of entities and hash indexes. Analyzers depend on it, not on CSV or Flask. |
| `DataLoader` / `DataValidator` / `ValidationReport` | Reading, checking and reporting are three separate jobs. |
| `DriverAnalyzer`, `TripAnalyzer`, `ZoneAnalyzer`, `CancellationAnalyzer`, `UtilizationAnalyzer`, `IdleTimeAnalyzer`, `AnomalyDetector`, `TopKService`, `SearchService`, `InsightsEngine` | One analytical concern each; every analyzer consumes model objects and returns plain results (dataclasses or dicts). |
| `AnalyticsEngine` | Facade / composition root. Routes call it and contain no analytics. |
| `TopKHeap` | Reusable bounded-heap data structure. |
| `UtilizationThresholds`, `AnomalyThresholds` | Configuration objects that validate themselves. |

Design choices worth mentioning: dependency injection (each analyzer receives the `Dataset`), a single shared `summarize()` used for KPIs, drivers, zones and cities so the same rules are never re-implemented, and results kept separate from presentation.

## 6. DSA approach

| Concept | Where it is used |
|---|---|
| **Dictionaries (hash maps)** | `drivers`, `trips`, `zones` indexes give O(1) lookup by ID; `trips_by_driver`, `trips_by_rider`, `activity_by_driver` are grouping indexes; the search module uses these directly. |
| **Sets** | Distinct riders; duplicate-ID and duplicate-event detection during validation; known-driver membership tests. |
| **Frequency counting** | `Counter` for reasons, time slots, drop zones, hours, riders. |
| **Grouping** | Trips grouped by city, zone, driver; cancellation reasons grouped by zone. |
| **Heap / priority queue** | `TopKHeap` keeps a size-K min-heap so Top-K costs O(N log K) rather than a full sort. Ties are broken deterministically by ID. Also `heapq.nlargest` for the longest idle gaps. |
| **Sorting and ranking** | Chronological sort of trips and activity events; ranked tables everywhere. |
| **Sequential / interval processing** | Utilization walks each driver's time-sorted event log once, adding the duration between consecutive events to the state that was active. Idle analysis walks consecutive trip pairs per driver. |
| **Lookup table** | 24-entry hour → time-slot array gives O(1) slot assignment. |
| **Statistics** | Quartile/IQR "fence" to detect unusually high fares and unusually high driver trip counts without a hardcoded number. |

### Complexity of key functions

N = trips, D = drivers, E = activity events, K = requested top-K, C = completed trips, G = idle gaps found.

| Function | Approach | Time | Space |
|---|---|---|---|
| `TopKService.run` → `TopKHeap.push` | Bounded min-heap of size K over N candidates | O(N log K) | O(K) |
| `Dataset.add_trip` + lookups (`drivers.get`, `trips.get`, `zones.get`) | Hash indexes built once while loading; grouped lists per driver/rider/zone | O(1) per insert and per lookup (average); O(N) to build | O(N) |
| `DriverAnalyzer.all_stats` | One `summarize` pass over each driver's own trips via `trips_by_driver`; cached | O(D + N) | O(D) |
| `UtilizationAnalyzer.records` | Per-driver sort of events (already sorted, so Timsort is ~linear) then one pass over consecutive pairs | O(E log m) worst, ~O(E) in practice (m = events per driver) | O(D) |
| `IdleTimeAnalyzer.analyze` | Per-driver chronological sort, consecutive-pair scan, `nlargest` for display | O(C log t + G log L) (t = trips per driver, L = rows shown) | O(G) |
| `AnomalyDetector._detect_trips` | Quartile fence (sort of C fares) then a single pass over all trips | O(N + C log C) | O(C) |
| `DataValidator.validate_trips` | Single pass; `set` for duplicate detection | O(N) | O(N) |
| `CancellationAnalyzer.by_reason` | `Counter` then sort of the distinct reasons | O(N + r log r), r is small | O(r) |
| `slot_for` | Precomputed hour → slot table | O(1) | O(1) |

Measured on the sample data (4,500 trips, 16,518 events): load + validate 0.15 s; all analytics 0.04 s.

## 7. Validation rules

| Check | Behaviour |
|---|---|
| Empty file, header only, missing required column, binary file | **Fatal**: nothing loads; a clear message is shown |
| Missing / malformed / duplicate trip or driver ID, unrecognised status, unreadable `request_time` | Row **dropped**, listed in validation details |
| Missing values (rider, city, zone, fare, distance…) | Row kept with a placeholder, flagged |
| Unreadable or missing pickup/drop timestamps, drop before pickup | Row kept (timing fields empty), flagged |
| Negative fare or distance, non-numeric numbers | Row kept, flagged; negative fares earn no revenue |
| Unknown driver ID on a trip | Row kept, flagged |
| Activity: bad ID, unknown driver, unreadable time, bad status, exact duplicate | Row dropped |

Column headers are matched case-insensitively. The sample data reproduces the brief's example: **17** completed trips missing a pickup timestamp, **4** negative fares, **3** unknown drivers (plus 2 drop-before-pickup and 1 unreadable timestamp).

## 8. Tests

`tests/test_mobility_tool.py` has 56 tests. Analytics expectations are hand-calculated on a six-trip fixture.

- **Validation:** empty file, header-only file, missing columns, case-insensitive headers, missing values, invalid IDs, duplicates, invalid/missing timestamps, negative and non-numeric values, drop-before-pickup, unknown driver, invalid status, activity problems, binary upload, singular/plural messages.
- **Models:** encapsulation, duration, fare per km, zero distance, negative fare revenue, slot boundaries, currency formatting.
- **DSA:** `TopKHeap` equals a full sort for K = 1 to 500 including ties (largest and smallest), invalid K, empty input.
- **Analytics:** KPIs, driver stats, driver with no trips, zone stats and slots, cancellation breakdown, peak slot, utilization from intervals, configurable thresholds, stale segments, idle gaps / overlaps / off-shift, top-K validation, search (found, not found, blank, case-insensitive).
- **Anomalies and insights:** each anomaly type, IQR fence, no false positives on clean data, configurable thresholds, insights change with the data.
- **Flask end-to-end:** redirect without data, upload flow uses uploaded numbers, missing file, wrong extension, bad content, empty upload, every page renders, bad inputs on every form, reset, 404.

## 9. Business insights (generated by the app from the sample data)

1. Connaught Place (Delhi) has the highest cancellation rate at 15.6%, against 12.2% across all zones.
2. The 18–21 window has the highest demand: 576 requests, 12.8% of all trips.
3. 177 of 196 drivers with activity data (90%) have utilization below 50%.
4. 'Driver Cancelled' is the largest cancellation category with 182 cancellations (33.1% of 550).
5. 34 trips and 38 drivers are flagged for anomalies; the most common issue is 'Invalid timestamp' (20).
6. Delhi generates 38.9% of revenue (₹4,94,635 of ₹12,72,368).
7. The top 10% of drivers (25) earn 15.3% of revenue.

The sample data is synthetic and random, so these numbers show the mechanism rather than real operational truths. Upload real data and they change.

## 10. Assumptions

- **Zones:** a request belongs to the zone where the rider is picked up (`pickup_zone`). A zone is identified by city + name (e.g. `BANGALORE-KORAMANGALA`).
- **Revenue:** only completed trips with a positive fare count. Anomalous but positive fares (e.g. ₹5,000) are flagged, not removed.
- **Averages:** average distance ignores zero-distance trips; average duration ignores trips with missing/invalid timing; fare per km is total revenue ÷ total distance.
- **Time slots:** 3-hour buckets. The brief lists six (06–09 … 21–00); the remaining overnight hours are two more buckets (00–03, 03–06) so no request is lost and buckets are comparable.
- **Utilization:** a state lasts until the driver's next event. Online hours = Online + Busy + Idle time; utilization = busy ÷ online. Offline time is ignored. A state longer than 12 h is treated as a missing logout and skipped. Drivers with no activity are excluded, not counted as 0%. Default bands: High ≥ 50%, Low < 35%.
- **Idle time:** gap = next trip's pickup − previous trip's drop, using each driver's completed trips with valid timing. Overlapping trips are skipped and counted. Gaps above the "off-shift window" (default 6 h) are treated as breaks between shifts, not idling; the window is configurable on the page.
- **Anomaly defaults:** trip longer than 180 min; fare above Q3 + 3×IQR; driver cancellation rate above 30% with at least 5 trips; utilization below 35%; rating below 3.2; trip count above Q3 + 1.5×IQR. IQR fences need at least 8 data points. All main thresholds are editable on the Anomalies page.
- All timestamps are treated as naive local times (any timezone offset is ignored).

## 11. Known limitations

- One dataset is held in memory per running server (a single-user tool); it is shared by every browser tab and lost on restart. There is no database or login.
- Uses Flask's development server; put it behind a production WSGI server if deployed. Set `SECRET_KEY`.
- Uploads are capped at 25 MB and processed in memory.
- Overlapping trips for one driver (possible in raw data) are excluded from idle analysis rather than repaired.
- Utilization needs an activity file; without one, those pages explain that and everything else still works.
- Charts are simple CSS bars and tables; there is no interactive charting library.

## 12. Suggested 15-minute demo

| Min | Segment | Show |
|---|---|---|
| 2 | Business problem | Section 1; what an ops user needs to know |
| 3 | Architecture | Section 3 flow diagram and section 4 folders |
| 3 | OOP | `Trip` methods, `Dataset`, an analyzer consuming objects |
| 3 | DSA | `utils/topk.py`, hash indexes, utilization interval loop; complexity table |
| 3 | Live demo | Load sample data → validation details → dashboard → driver D102 → Top-K → idle threshold → anomalies → search a bad ID |
| 1 | Insights | Insights page |
