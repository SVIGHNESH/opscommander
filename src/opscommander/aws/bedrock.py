"""Amazon Bedrock LLM wrapper used by the Recommendation Agent.

Prefers the Anthropic SDK's ``AnthropicBedrockMantle`` client (the Messages-API
Bedrock endpoint). If neither the SDK nor credentials are available, it falls
back to a deterministic rule-based generator so the whole pipeline still runs
and demos offline.
"""

from __future__ import annotations

import json
from typing import Any

from ..config import Settings, get_settings
from ..logging_config import get_logger

log = get_logger("aws.bedrock")


SYSTEM_PROMPT = (
    "You are a senior Site Reliability Engineer embedded in an automated "
    "incident-response system. Given an incident summary, its likely root "
    "cause, and infrastructure health, propose concrete, safe remediation "
    "recommendations. Respond ONLY with minified JSON of the form: "
    '{"recommendations": [{"title": str, "rationale": str, "action": str, '
    '"confidence": number, "references": [str]}]}. '
    'The "action" field MUST be a machine key from this set: '
    "restart_lambda, increase_lambda_timeout, scale_asg, restart_ecs_task, "
    "clear_failed_jobs, trigger_deployment, rotate_credentials, "
    "increase_db_connections, manual_investigation."
)


class BedrockLLM:
    """Thin wrapper exposing ``recommend(context) -> list[dict]``."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._client = None
        self._mode = "mock"
        if not self.settings.is_mock:
            self._client, self._mode = self._init_client()

    def _init_client(self):
        # Preferred: Anthropic SDK Bedrock (Mantle) client.
        try:
            from anthropic import AnthropicBedrockMantle  # type: ignore

            client = AnthropicBedrockMantle(aws_region=self.settings.aws_region)
            log.info("Using AnthropicBedrockMantle for recommendations")
            return client, "anthropic"
        except Exception as exc:  # noqa: BLE001
            log.info("AnthropicBedrockMantle unavailable (%s); trying boto3", exc)

        # Fallback: raw boto3 bedrock-runtime InvokeModel.
        from .clients import make_client

        client = make_client("bedrock-runtime", self.settings)
        if client is not None:
            return client, "boto3"

        log.warning("No Bedrock backend available; using rule-based recommendations")
        return None, "mock"

    # ------------------------------------------------------------------ #
    def recommend(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        if self._mode == "anthropic":
            return self._recommend_anthropic(context)
        if self._mode == "boto3":
            return self._recommend_boto3(context)
        return self._recommend_mock(context)

    # ------------------------------------------------------------------ #
    def _user_prompt(self, context: dict[str, Any]) -> str:
        return (
            "Incident:\n" + json.dumps(context, indent=2, default=str) +
            "\n\nReturn 1-3 prioritised recommendations as JSON."
        )

    def _recommend_anthropic(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            resp = self._client.messages.create(  # type: ignore[union-attr]
                model=self.settings.bedrock_model_id,
                max_tokens=self.settings.bedrock_max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": self._user_prompt(context)}],
            )
            text = "".join(
                b.text for b in resp.content if getattr(b, "type", None) == "text"
            )
            return self._parse(text, context)
        except Exception as exc:  # noqa: BLE001
            log.warning("Bedrock (anthropic) call failed: %s; using fallback", exc)
            return self._recommend_mock(context)

    def _recommend_boto3(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": self.settings.bedrock_max_tokens,
                "system": SYSTEM_PROMPT,
                "messages": [
                    {"role": "user", "content": self._user_prompt(context)}
                ],
            }
            resp = self._client.invoke_model(  # type: ignore[union-attr]
                modelId=self.settings.bedrock_model_id,
                body=json.dumps(body),
            )
            payload = json.loads(resp["body"].read())
            text = "".join(
                b.get("text", "")
                for b in payload.get("content", [])
                if b.get("type") == "text"
            )
            return self._parse(text, context)
        except Exception as exc:  # noqa: BLE001
            log.warning("Bedrock (boto3) call failed: %s; using fallback", exc)
            return self._recommend_mock(context)

    def _parse(self, text: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        text = text.strip()
        # Tolerate models that wrap JSON in prose or code fences.
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            text = text[start : end + 1]
        try:
            recs = json.loads(text).get("recommendations", [])
            if recs:
                return recs
        except json.JSONDecodeError:
            log.warning("Could not parse Bedrock JSON; using fallback")
        return self._recommend_mock(context)

    # ------------------------------------------------------------------ #
    def _recommend_mock(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        """Deterministic recommendations keyed off the detected root cause.

        Good enough to drive the pipeline and demos with no AWS access, and it
        mirrors the JSON contract the real model is asked to produce.
        """
        rc = (context.get("root_cause") or "").lower()
        service = (context.get("service") or "").lower()

        if "timeout" in rc and "database" in rc:
            return [
                {
                    "title": "Increase database connection pool and Lambda timeout",
                    "rationale": "Root cause is a database connection timeout; the "
                    "pool is likely exhausted under load and the function times out "
                    "waiting for a connection.",
                    "action": "increase_db_connections",
                    "confidence": 0.82,
                    "references": [
                        "https://docs.aws.amazon.com/lambda/latest/dg/configuration-database.html"
                    ],
                },
                {
                    "title": "Restart the affected Lambda to clear stuck connections",
                    "rationale": "A restart clears half-open connections while the "
                    "pool change propagates.",
                    "action": "restart_lambda",
                    "confidence": 0.6,
                    "references": [],
                },
            ]
        if "timeout" in rc and "lambda" in service:
            return [
                {
                    "title": "Increase Lambda timeout and optimise slow calls",
                    "rationale": "The function is exceeding its configured timeout.",
                    "action": "increase_lambda_timeout",
                    "confidence": 0.75,
                    "references": [],
                }
            ]
        if "cpu" in rc or "cpu" in context.get("alarm", "").lower():
            return [
                {
                    "title": "Scale out the Auto Scaling Group",
                    "rationale": "Sustained high CPU indicates insufficient capacity "
                    "for current load.",
                    "action": "scale_asg",
                    "confidence": 0.7,
                    "references": [],
                }
            ]
        if "memory" in rc or "oom" in rc:
            return [
                {
                    "title": "Restart the ECS task and raise the memory reservation",
                    "rationale": "Out-of-memory conditions require both immediate "
                    "recovery and a capacity change.",
                    "action": "restart_ecs_task",
                    "confidence": 0.68,
                    "references": [],
                }
            ]
        return [
            {
                "title": "Escalate for manual investigation",
                "rationale": "The signals do not match a known automatable pattern; "
                "a human should investigate before any change is made.",
                "action": "manual_investigation",
                "confidence": 0.4,
                "references": [],
            }
        ]
