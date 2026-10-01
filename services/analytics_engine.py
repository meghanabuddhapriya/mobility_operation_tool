"""Facade that wires the dataset to every analyzer, so Flask routes stay thin."""
from typing import Optional

from .anomaly_detector import AnomalyDetector, AnomalyReport, AnomalyThresholds
from .cancellation_analyzer import CancellationAnalyzer
from .dataset import Dataset
from .driver_analyzer import DriverAnalyzer
from .insights_engine import InsightsEngine
from .search_service import SearchService
from .topk_service import TopKService
from .trip_analyzer import TripAnalyzer
from .utilization_analyzer import IdleTimeAnalyzer, UtilizationAnalyzer
from .validation_service import ValidationReport
from .zone_analyzer import ZoneAnalyzer


class AnalyticsEngine:
    def __init__(self, dataset: Dataset, report: ValidationReport, source: str = "upload"):
        self.dataset = dataset
        self.report = report
        self.source = source
        self.trips = TripAnalyzer(dataset)
        self.drivers = DriverAnalyzer(dataset)
        self.zones = ZoneAnalyzer(dataset)
        self.cancellations = CancellationAnalyzer(dataset)
        self.utilization = UtilizationAnalyzer(dataset)
        self.idle = IdleTimeAnalyzer(dataset)
        self.topk = TopKService(dataset, self.drivers, self.utilization, self.cancellations)
        self.search = SearchService(dataset, self.drivers)
        self._detector = AnomalyDetector(dataset, self.drivers, self.utilization)
        self._insights = InsightsEngine(dataset, self.trips, self.drivers, self.cancellations, self.utilization)
        self._default_anomalies: Optional[AnomalyReport] = None

    def anomalies(self, thresholds: Optional[AnomalyThresholds] = None) -> AnomalyReport:
        if thresholds is None:
            if self._default_anomalies is None:
                self._default_anomalies = self._detector.detect()
            return self._default_anomalies
        return self._detector.detect(thresholds)

    def insights(self):
        return self._insights.generate(self.anomalies())
