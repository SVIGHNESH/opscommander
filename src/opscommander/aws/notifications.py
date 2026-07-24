"""Outbound notifications: SNS, Slack webhook, and email (SES).

All channels degrade to logging so the pipeline never fails because a
notification could not be sent.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from ..config import Settings, get_settings
from ..logging_config import get_logger
from .clients import make_client

log = get_logger("aws.notifications")


class Notifier:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._sns = make_client("sns", self.settings)
        self.sent: list[dict[str, Any]] = []  # in-memory audit for tests/demos

    def notify(self, subject: str, message: str) -> None:
        self._publish_sns(subject, message)
        self._post_slack(subject, message)

    # ------------------------------------------------------------------ #
    def _publish_sns(self, subject: str, message: str) -> None:
        record = {"channel": "sns", "subject": subject, "message": message}
        if self._sns is not None and self.settings.sns_topic_arn:
            try:
                self._sns.publish(  # type: ignore[union-attr]
                    TopicArn=self.settings.sns_topic_arn,
                    Subject=subject[:100],
                    Message=message,
                )
                record["delivered"] = True
            except Exception as exc:  # noqa: BLE001
                log.warning("SNS publish failed: %s", exc)
                record["delivered"] = False
        else:
            log.info("[SNS] %s", subject)
            record["delivered"] = False
        self.sent.append(record)

    def _post_slack(self, subject: str, message: str) -> None:
        url = self.settings.slack_webhook_url
        record = {"channel": "slack", "subject": subject, "message": message}
        if not url:
            record["delivered"] = False
            self.sent.append(record)
            return
        try:
            payload = json.dumps({"text": f"*{subject}*\n{message}"}).encode()
            req = urllib.request.Request(
                url, data=payload, headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=5)  # noqa: S310 - user-provided webhook
            record["delivered"] = True
        except Exception as exc:  # noqa: BLE001
            log.warning("Slack post failed: %s", exc)
            record["delivered"] = False
        self.sent.append(record)
