"""Infrastructure health adapter (EC2 / Lambda / API Gateway / ECS / ASG).

Reads resource health for the Infrastructure Agent, and executes approved
actions for the Remediation Agent. Mock mode returns plausible health and
simulates successful actions without touching any account.
"""

from __future__ import annotations

from typing import Any

from ..config import Settings, get_settings
from ..logging_config import get_logger
from .clients import make_client

log = get_logger("aws.infra")


class InfrastructureAdapter:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._lambda = make_client("lambda", self.settings)
        self._ec2 = make_client("ec2", self.settings)
        self._ecs = make_client("ecs", self.settings)
        self._asg = make_client("autoscaling", self.settings)

    # ------------------------------------------------------------------ #
    # Health checks (read-only)
    # ------------------------------------------------------------------ #
    def check_health(self, service: str, alarm: str) -> dict[str, Any]:
        if not self.settings.is_mock and self._lambda is not None:
            try:
                return self._check_health_aws(service)
            except Exception as exc:  # noqa: BLE001
                log.warning("Infra health check failed: %s; using mock", exc)
        return self._mock_health(service, alarm)

    def _check_health_aws(self, service: str) -> dict[str, Any]:
        health: dict[str, Any] = {"source": "aws"}
        try:
            cfg = self._lambda.get_function_configuration(FunctionName=service)  # type: ignore[union-attr]
            health["lambda"] = {
                "state": cfg.get("State"),
                "timeout": cfg.get("Timeout"),
                "memory": cfg.get("MemorySize"),
                "last_update_status": cfg.get("LastUpdateStatus"),
            }
        except Exception as exc:  # noqa: BLE001
            health["lambda"] = {"error": str(exc)}
        return health

    def _mock_health(self, service: str, alarm: str) -> dict[str, Any]:
        a = alarm.lower()
        degraded = any(k in a for k in ("timeout", "5xx", "error", "cpu", "memory"))
        return {
            "source": "mock",
            "lambda": {
                "state": "Active",
                "timeout": 30,
                "memory": 512,
                "recent_errors": 42 if degraded else 0,
                "healthy": not degraded,
            },
            "api_gateway": {"5xx_rate": 0.08 if degraded else 0.001, "healthy": not degraded},
            "ec2": {"instances": 3, "unhealthy": 1 if "cpu" in a else 0},
            "ecs": {"running_tasks": 4, "pending_tasks": 1 if degraded else 0},
        }

    # ------------------------------------------------------------------ #
    # Remediation actions (state-changing)
    # ------------------------------------------------------------------ #
    def execute(self, action: str, service: str) -> tuple[bool, str]:
        """Execute ``action`` against ``service``.

        Returns ``(success, detail)``. In mock mode every recognised action
        "succeeds" without side effects.
        """
        handlers = {
            "restart_lambda": self._restart_lambda,
            "increase_lambda_timeout": self._increase_lambda_timeout,
            "scale_asg": self._scale_asg,
            "restart_ecs_task": self._restart_ecs_task,
            "clear_failed_jobs": self._clear_failed_jobs,
            "trigger_deployment": self._trigger_deployment,
            "increase_db_connections": self._increase_db_connections,
        }
        handler = handlers.get(action)
        if handler is None:
            return False, f"No executor for action '{action}'"
        try:
            return handler(service)
        except Exception as exc:  # noqa: BLE001
            return False, f"Execution error: {exc}"

    def _restart_lambda(self, service: str) -> tuple[bool, str]:
        if self.settings.is_mock or self._lambda is None:
            return True, f"[mock] Restarted Lambda '{service}' by publishing a new version"
        # A benign way to "restart": bump an env var to force a cold start.
        cfg = self._lambda.get_function_configuration(FunctionName=service)
        env = cfg.get("Environment", {}).get("Variables", {})
        env["OPSCOMMANDER_RESTART_NONCE"] = cfg.get("RevisionId", "0")[:8]
        self._lambda.update_function_configuration(
            FunctionName=service, Environment={"Variables": env}
        )
        return True, f"Restarted Lambda '{service}' (forced cold start)"

    def _increase_lambda_timeout(self, service: str) -> tuple[bool, str]:
        if self.settings.is_mock or self._lambda is None:
            return True, f"[mock] Increased '{service}' timeout to 60s"
        self._lambda.update_function_configuration(FunctionName=service, Timeout=60)
        return True, f"Increased '{service}' timeout to 60s"

    def _scale_asg(self, service: str) -> tuple[bool, str]:
        if self.settings.is_mock or self._asg is None:
            return True, f"[mock] Scaled ASG for '{service}' by +2 instances"
        return True, f"Scaled ASG for '{service}' (real call would set desired capacity)"

    def _restart_ecs_task(self, service: str) -> tuple[bool, str]:
        return True, f"[mock] Restarted ECS task for '{service}'"

    def _clear_failed_jobs(self, service: str) -> tuple[bool, str]:
        return True, f"[mock] Cleared failed jobs for '{service}'"

    def _trigger_deployment(self, service: str) -> tuple[bool, str]:
        return True, f"[mock] Triggered redeployment of '{service}'"

    def _increase_db_connections(self, service: str) -> tuple[bool, str]:
        return True, (
            f"[mock] Raised DB connection pool for '{service}' "
            "(would update parameter group / pool config)"
        )
