"""Static checks for the PrometheusRule template shipped with the Helm chart.

Renders the chart with the rule both disabled (default) and enabled, then
asserts that the expected alerts and operator-friendly structure are in
place. Skipped when ``helm`` is not on PATH so dev shells without the
binary still pass.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

CHART_DIR = Path(__file__).resolve().parent.parent / "infra" / "helm" / "shotclassify"

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None or yaml is None,
    reason="helm binary or PyYAML not available",
)


def _render(extra: dict | None = None) -> list[dict]:
    cmd = ["helm", "template", "release", str(CHART_DIR)]  # noqa: S603, S607
    for k, v in (extra or {}).items():
        cmd += ["--set", f"{k}={v}"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)  # noqa: S603
    return [d for d in yaml.safe_load_all(out.stdout) if d]


def _rules(extra: dict | None = None) -> list[dict]:
    return [d for d in _render(extra) if d.get("kind") == "PrometheusRule"]


def test_prometheus_rule_disabled_by_default() -> None:
    assert _rules() == [], "PrometheusRule must be opt-in via metrics.prometheusRule.enabled"


def test_prometheus_rule_renders_when_enabled() -> None:
    rules = _rules({"metrics.prometheusRule.enabled": "true"})
    assert len(rules) == 1, "expected exactly one PrometheusRule"
    rule = rules[0]
    assert rule["apiVersion"] == "monitoring.coreos.com/v1"
    assert rule["metadata"]["name"].endswith("-api")
    groups = rule["spec"]["groups"]
    assert {g["name"] for g in groups} == {
        "shotclassify-api.availability",
        "shotclassify-api.latency",
        "shotclassify-api.saturation",
    }


def test_prometheus_rule_alerts_cover_required_signals() -> None:
    rules = _rules({"metrics.prometheusRule.enabled": "true"})
    alerts = {
        alert["alert"]: alert
        for group in rules[0]["spec"]["groups"]
        for alert in group["rules"]
    }
    expected = {
        "ShotclassifyApiDown",
        "ShotclassifyApiHighErrorRate",
        "ShotclassifyApiHighExceptionRate",
        "ShotclassifyApiHighLatencyP95",
        "ShotclassifyApiInFlightSaturation",
    }
    assert expected.issubset(alerts.keys()), alerts.keys()
    for name, alert in alerts.items():
        assert alert.get("for"), f"{name} missing 'for' window"
        labels = alert.get("labels", {})
        assert labels.get("severity") in {"critical", "warning"}, name
        annotations = alert.get("annotations", {})
        assert annotations.get("summary"), f"{name} missing summary"
        assert annotations.get("runbook_url"), f"{name} missing runbook_url"


def test_prometheus_rule_uses_exported_metric_names() -> None:
    rules = _rules({"metrics.prometheusRule.enabled": "true"})
    text = yaml.safe_dump(rules[0])
    # The middleware exports exactly these series; alerts must reference them
    # so renames in app code surface here.
    for series in (
        "shotclassify_http_requests_total",
        "shotclassify_http_request_duration_seconds_bucket",
        "shotclassify_http_exceptions_total",
        "shotclassify_http_requests_in_flight",
    ):
        assert series in text, f"alert rules missing {series}"


def test_prometheus_rule_extra_labels_merged() -> None:
    rules = _rules(
        {
            "metrics.prometheusRule.enabled": "true",
            "metrics.prometheusRule.labels.release": "kube-prometheus-stack",
        }
    )
    labels = rules[0]["metadata"]["labels"]
    assert labels.get("release") == "kube-prometheus-stack"
