"""Flask entry point. Routes stay thin: parse input -> call the AnalyticsEngine -> render a template."""
import os
from functools import wraps

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

from services.analytics_engine import AnalyticsEngine
from services.anomaly_detector import AnomalyThresholds
from services.data_loader import DataLoader, decode_bytes
from services.search_service import SEARCH_TYPES
from services.utilization_analyzer import UtilizationThresholds
from services.validation_service import ValidationReport
from utils import constants as C
from utils.helpers import inr, parse_number_arg

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_FIELDS = [("drivers", "Drivers CSV", True), ("trips", "Trips CSV", True), ("activity", "Driver activity CSV", False)]


def create_app(data_dir: str = DATA_DIR) -> Flask:
    app = Flask(__name__)
    app.config.update(SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
                      MAX_CONTENT_LENGTH=C.MAX_UPLOAD_BYTES)
    state = {"engine": None}                     # one dataset per running server (single-user tool)
    app.extensions["state"] = state

    # ------------------------------------------------------------------ helpers
    app.jinja_env.filters["inr"] = lambda v, d=0: inr(v or 0, d)
    app.jinja_env.filters["num"] = lambda v, d=0: f"{v or 0:,.{d}f}"
    app.jinja_env.filters["pct"] = lambda v, d=1: f"{(v or 0):.{d}f}%"
    app.jinja_env.filters["frac_pct"] = lambda v, d=1: f"{(v or 0) * 100:.{d}f}%"

    def fmt_value(value, unit):
        return inr(value) if unit == "currency" else f"{value:.1f}%" if unit == "percent" else f"{value:,.0f}"
    app.jinja_env.filters["fmt_value"] = fmt_value

    @app.context_processor
    def inject_globals():
        return {"engine": state["engine"]}

    def needs_data(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if state["engine"] is None:
                flash("Load a dataset first.", "error")
                return redirect(url_for("index"))
            return view(*args, **kwargs)
        return wrapper

    def read_upload(field, label, required):
        file = request.files.get(field)
        if file is None or not file.filename:
            if required:
                raise ValueError(f"Choose a {label}.")
            return None
        if not file.filename.lower().endswith(".csv"):
            raise ValueError(f"{label}: '{file.filename}' is not a .csv file.")
        return decode_bytes(file.read())

    def load_texts(drivers, trips, activity, source):
        dataset, report = DataLoader().load(drivers, trips, activity)
        if dataset is None:
            return report
        state["engine"] = AnalyticsEngine(dataset, report, source)
        return None

    # ------------------------------------------------------------------ data loading
    @app.route("/")
    def index():
        return render_template("index.html", fields=UPLOAD_FIELDS, failed_report=None)

    @app.post("/upload")
    def upload():
        try:
            texts = {f: read_upload(f, label, req) for f, label, req in UPLOAD_FIELDS}
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("index"))
        failed = load_texts(texts["drivers"], texts["trips"], texts["activity"], "Uploaded files")
        if failed:
            return render_template("index.html", fields=UPLOAD_FIELDS, failed_report=failed), 400
        flash("Data loaded.", "ok")
        return redirect(url_for("dashboard"))

    @app.post("/load-sample")
    def load_sample():
        try:
            def read(name):
                with open(os.path.join(data_dir, name), encoding="utf-8") as handle:
                    return handle.read()
            failed = load_texts(read("drivers.csv"), read("trips.csv"), read("driver_activity.csv"), "Sample data")
        except OSError:
            flash("Sample files were not found in the data folder. Run: python data/generate_sample_data.py", "error")
            return redirect(url_for("index"))
        if failed:
            return render_template("index.html", fields=UPLOAD_FIELDS, failed_report=failed), 400
        flash("Sample data loaded.", "ok")
        return redirect(url_for("dashboard"))

    @app.post("/reset")
    def reset():
        state["engine"] = None
        flash("Dataset cleared.", "ok")
        return redirect(url_for("index"))

    @app.route("/validation")
    @needs_data
    def validation():
        report = state["engine"].report
        dataset, category = request.args.get("dataset", ""), request.args.get("category", "")
        issues = report.filtered(dataset or None, category or None)
        return render_template("validation.html", report=report, issues=issues[:C.MAX_VALIDATION_ROWS_SHOWN],
                               total_issues=len(issues), dataset=dataset, category=category)

    # ------------------------------------------------------------------ analytics pages
    @app.route("/dashboard")
    @needs_data
    def dashboard():
        e = state["engine"]
        return render_template("dashboard.html", kpis=e.trips.kpis(), report=e.report)

    @app.route("/api/kpis")
    @needs_data
    def api_kpis():
        return jsonify(state["engine"].trips.kpis())

    @app.route("/trips")
    @needs_data
    def trips():
        e = state["engine"]
        slots = e.trips.demand_by_slot()
        return render_template("trips.html", kpis=e.trips.kpis(), slots=slots, cities=e.trips.by_city(),
                               distance=e.trips.distance_distribution(), hours=e.trips.demand_by_hour(),
                               daily=e.trips.daily_trend(), peak=e.trips.peak_slot())

    @app.route("/drivers")
    @needs_data
    def drivers():
        e = state["engine"]
        driver_id = (request.args.get("driver_id") or "").strip()
        selected = None
        if driver_id:
            selected = e.drivers.stats_for(driver_id)
            if selected is None:
                flash(f"Driver {driver_id} was not found.", "error")
        util = {r.driver_id: r for r in e.utilization.records()} if e.dataset.has_activity else {}
        top_util = e.topk.run("driver_utilization", 5)["rows"] if e.dataset.has_activity else []
        return render_template(
            "driver.html", options=e.drivers.driver_options(), selected=selected, driver_id=driver_id,
            util=util.get(driver_id), top_completed=e.drivers.top_by_completed(5),
            low_cancel=e.drivers.lowest_cancellation(5), top_revenue=e.drivers.highest_revenue(5),
            top_util=top_util, attention=e.anomalies().drivers_needing_attention()[:15])

    @app.route("/zones")
    @needs_data
    def zones():
        e = state["engine"]
        zone_id = (request.args.get("zone_id") or "").strip()
        city = (request.args.get("city") or "").strip()
        selected = None
        if zone_id:
            selected = e.zones.stats(zone_id)
            if selected is None:
                flash(f"Zone {zone_id} was not found.", "error")
        return render_template("zone.html", cities=e.dataset.cities, city=city, options=e.zones.zone_options(),
                               zone_id=zone_id, selected=selected, rows=e.zones.all_zone_rows(city or None))

    @app.route("/topk")
    @needs_data
    def topk():
        e = state["engine"]
        metric, k = request.args.get("metric"), request.args.get("k", "10")
        result = None
        if metric:
            try:
                result = e.topk.run(metric, k)
            except ValueError as exc:
                flash(str(exc), "error")
        return render_template("topk.html", metrics=e.topk.metrics(), metric=metric, k=k, result=result)

    @app.route("/cancellations")
    @needs_data
    def cancellations():
        e = state["engine"]
        view = request.args.get("view", "reason")
        if view not in ("reason", "zone", "driver", "time"):
            view = "reason"
        rows = {"reason": e.cancellations.by_reason, "zone": e.cancellations.by_zone,
                "driver": e.cancellations.by_driver, "time": e.cancellations.by_time}[view]()
        return render_template("cancellations.html", view=view, rows=rows, total=e.cancellations.total,
                               reasons=e.cancellations.by_reason(), rate=e.trips.kpis()["cancellation_rate"])

    @app.route("/utilization")
    @needs_data
    def utilization():
        e = state["engine"]
        if not e.dataset.has_activity:
            return render_template("utilization.html", available=False)
        high, low = request.args.get("high"), request.args.get("low")
        try:
            th = UtilizationThresholds(
                high=parse_number_arg(high, "High threshold", C.HIGH_UTILIZATION * 100, 0, 100) / 100,
                low=parse_number_arg(low, "Low threshold", C.LOW_UTILIZATION * 100, 0, 100) / 100)
        except ValueError as exc:
            flash(str(exc), "error")
            th = UtilizationThresholds()
        records = e.utilization.records(th)
        category = request.args.get("category", "")
        shown = [r for r in records if not category or r.category == category]
        return render_template("utilization.html", available=True, th=th, summary=e.utilization.summary(th),
                               records=shown[:200], shown=len(shown), category=category)

    @app.route("/idle")
    @needs_data
    def idle():
        e = state["engine"]
        args = request.args
        result, error = None, None
        params = {"threshold": args.get("threshold", str(C.DEFAULT_IDLE_THRESHOLD_MIN)),
                  "window": args.get("window", str(C.DEFAULT_IDLE_WINDOW_MIN)),
                  "driver_id": (args.get("driver_id") or "").strip().upper()}
        if "threshold" in args:
            try:
                threshold = parse_number_arg(params["threshold"], "Idle threshold", C.DEFAULT_IDLE_THRESHOLD_MIN, 0, 10080)
                window = parse_number_arg(params["window"], "Idle window", C.DEFAULT_IDLE_WINDOW_MIN, 1, 10080)
                result = e.idle.analyze(threshold, window, params["driver_id"] or None)
            except ValueError as exc:
                flash(str(exc), "error")
        return render_template("idle.html", params=params, result=result)

    @app.route("/anomalies")
    @needs_data
    def anomalies():
        e = state["engine"]
        try:
            th = AnomalyThresholds.from_args(request.args) if request.args else None
        except ValueError as exc:
            flash(str(exc), "error")
            th = None
        report = e.anomalies(th)
        return render_template("anomalies.html", report=report, th=report.thresholds or AnomalyThresholds(),
                               trip_rows=report.trip_anomalies[:300], driver_rows=report.driver_anomalies[:300])

    @app.route("/search")
    @needs_data
    def search():
        e = state["engine"]
        kind, query = request.args.get("type", "driver"), request.args.get("q", "")
        outcome = None
        if "q" in request.args:
            try:
                outcome = e.search.search(kind, query)
            except ValueError as exc:
                flash(str(exc), "error")
        return render_template("search.html", types=SEARCH_TYPES, kind=kind, query=query, outcome=outcome)

    @app.route("/insights")
    @needs_data
    def insights():
        return render_template("insights.html", insights=state["engine"].insights())

    # ------------------------------------------------------------------ errors
    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", title="Page not found", message="That page does not exist."), 404

    @app.errorhandler(413)
    def too_large(_):
        flash(f"That upload is larger than {C.MAX_UPLOAD_BYTES // (1024 * 1024)} MB.", "error")
        return redirect(url_for("index"))

    @app.errorhandler(500)
    def server_error(_):
        return render_template("error.html", title="Something went wrong",
                               message="The analysis failed unexpectedly. Check the data and try again."), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=int(os.environ.get("PORT", "5000")))
