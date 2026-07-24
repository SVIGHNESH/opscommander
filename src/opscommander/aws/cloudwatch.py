"""CloudWatch Logs / Metrics adapter used by Detection and Log Analysis.

In mock mode it synthesises log lines and metrics that are internally
consistent with the incoming alarm, so the downstream agents have something
realistic to reason about.
"""

from __future__ import annotations

from typing import Any

from ..config import Settings, get_settings
from ..logging_config import get_logger
from .clients import make_client

log = get_logger("aws.cloudwatch")


# Canonical mock log fixtures keyed by an alarm keyword.
_MOCK_LOGS: dict[str, list[str]] = {
    "timeout": [
        "ERROR Task timed out after 30.00 seconds",
        "ERROR psycopg2.OperationalError: could not connect to server: Connection timed out",
        "WARN  connection pool exhausted (size=10, in_use=10)",
        "ERROR Database connection timeout while acquiring connection",
    ],
    "cpu": [
        "WARN  CPUUtilization sustained above 90% for 10 minutes",
        "WARN  request latency p99 climbing (2400ms)",
        "INFO  autoscaling cooldown active",
    ],
    "memory": [
        "ERROR Runtime exited with error: signal: killed (OOM)",
        "WARN  memory usage 98% of limit",
        "ERROR java.lang.OutOfMemoryError: Java heap space",
    ],
    "5xx": [
        "ERROR upstream returned 502 Bad Gateway",
        "ERROR unhandled exception: NullPointerException at Handler.process",
        "WARN  circuit breaker open for downstream service",
    ],
}


class CloudWatchAdapter:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._logs = make_client("logs", self.settings)
        self._cw = make_client("cloudwatch", self.settings)

    # ------------------------------------------------------------------ #
    def fetch_logs(self, service: str, alarm: str, limit: int = 20) -> list[str]:
        if self._logs is not None:
            try:
                return self._fetch_logs_aws(service, limit)
            except Exception as exc:  # noqa: BLE001
                log.warning("CloudWatch Logs fetch failed: %s; using mock", exc)
        return self._mock_logs(alarm)

    def fetch_metrics(self, service: str, alarm: str) -> dict[str, Any]:
        if self._cw is not None:
            try:
                return self._fetch_metrics_aws(service)
            except Exception as exc:  # noqa: BLE001
                log.warning("CloudWatch metrics fetch failed: %s; using mock", exc)
        return self._mock_metrics(alarm)

    # ------------------------------------------------------------------ #
    def _fetch_logs_aws(self, service: str, limit: int) -> list[str]:
        group = f"/aws/lambda/{service}"
        streams = self._logs.describe_log_streams(  # type: ignore[union-attr]
            logGroupName=group, orderBy="LastEventTime", descending=True, limit=1
        )
        if not streams.get("logStreams"):
            return []
        stream = streams["logStreams"][0]["logStreamName"]
        events = self._logs.get_log_events(  # type: ignore[union-attr]
            logGroupName=group, logStreamName=stream, limit=limit, startFromHead=False
        )
        return [e["message"].rstrip() for e in events.get("events", [])]

    def _fetch_metrics_aws(self, service: str) -> dict[str, Any]:
        # Kept intentionally light; a real deployment would issue
        # get_metric_data calls per relevant metric here.
        return {"source": "cloudwatch", "service": service}

    # ------------------------------------------------------------------ #
    @staticmethod
    def _keyword(alarm: str) -> str:
        a = alarm.lower()
        for key in _MOCK_LOGS:
            if key in a:
                return key
        if "database" in a or "db" in a:
            return "timeout"
        return "5xx"

    def _mock_logs(self, alarm: str) -> list[str]:
        return list(_MOCK_LOGS[self._keyword(alarm)])

    def _mock_metrics(self, alarm: str) -> dict[str, Any]:
        key = self._keyword(alarm)
        base = {
            "timeout": {"Duration_p99_ms": 30000, "Errors": 42, "Throttles": 0},
            "cpu": {"CPUUtilization_pct": 93, "Latency_p99_ms": 2400},
            "memory": {"MemoryUtilization_pct": 98, "Errors": 17},
            "5xx": {"HTTP5xx": 128, "HTTP2xx": 4020},
        }[key]
        return {"source": "mock", **base}
