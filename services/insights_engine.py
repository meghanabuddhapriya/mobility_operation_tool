"""Turns analyzer outputs into plain-English insights. Every sentence is computed from the data."""
from typing import List

from utils import constants as C
from utils.helpers import inr, pct

from .anomaly_detector import AnomalyReport
from .cancellation_analyzer import CancellationAnalyzer
from .driver_analyzer import DriverAnalyzer
from .trip_analyzer import TripAnalyzer
from .utilization_analyzer import UtilizationAnalyzer
from .dataset import Dataset


class InsightsEngine:
    def __init__(self, dataset: Dataset, trips: TripAnalyzer, drivers: DriverAnalyzer,
                 cancellations: CancellationAnalyzer, utilization: UtilizationAnalyzer):
        self._data, self._trips, self._drivers = dataset, trips, drivers
        self._cancel, self._util = cancellations, utilization

    def generate(self, anomalies: AnomalyReport) -> List[str]:
        kpis = self._trips.kpis()
        insights: List[str] = []

        # 1. zone with the highest cancellation rate (only zones with enough requests)
        zones = [z for z in self._cancel.by_zone() if z["requests"] >= C.ZONE_MIN_REQUESTS_FOR_RATE]
        if zones:
            worst = max(zones, key=lambda z: (z["rate"], z["requests"]))
            insights.append(f"{worst['zone']} ({worst['city']}) has the highest cancellation rate at "
                            f"{worst['rate']:.1f}%, against {kpis['cancellation_rate']:.1f}% across all zones.")

        # 2. peak demand slot
        if kpis["total_trips"]:
            peak = self._trips.peak_slot()
            insights.append(f"The {peak['slot']} window has the highest demand: {peak['requests']:,} requests, "
                            f"{peak['share']:.1f}% of all trips.")

        # 3. low-utilisation drivers
        if self._data.has_activity:
            recs = self._util.records()
            low = [r for r in recs if r.utilization < C.INSIGHT_UTILIZATION_CUTOFF]
            if recs:
                insights.append(f"{len(low)} of {len(recs)} drivers with activity data "
                                f"({pct(len(low), len(recs)):.0f}%) have utilization below "
                                f"{C.INSIGHT_UTILIZATION_CUTOFF * 100:.0f}%.")

        # 4. largest cancellation category
        reasons = self._cancel.by_reason()
        if reasons:
            top = reasons[0]
            insights.append(f"'{top['reason']}' is the largest cancellation category with {top['count']:,} "
                            f"cancellations ({top['share']:.1f}% of {self._cancel.total:,}).")

        # 5. anomalies
        if anomalies.total:
            top_cat, top_n = anomalies.category_counts()[0]
            insights.append(f"{anomalies.flagged_trips} trips and {anomalies.flagged_drivers} drivers are flagged "
                            f"for anomalies; the most common issue is '{top_cat}' ({top_n}).")
        else:
            insights.append("No trip or driver anomalies were flagged at the current thresholds.")

        # 6. revenue concentration by city
        shares = self._trips.revenue_share_by_city()
        if shares and kpis["total_revenue"] > 0:
            lead = max(shares, key=lambda r: r["revenue"])
            insights.append(f"{lead['city']} generates {lead['share']:.1f}% of revenue "
                            f"({inr(lead['revenue'])} of {inr(kpis['total_revenue'])}).")

        # 7. driver revenue concentration
        earners = sorted((s.revenue for s in self._drivers.all_stats().values()), reverse=True)
        total_rev = sum(earners)
        if len(earners) >= 10 and total_rev > 0:
            n = max(1, len(earners) // 10)
            insights.append(f"The top 10% of drivers ({n}) earn {pct(sum(earners[:n]), total_rev):.1f}% of revenue.")
        return insights
