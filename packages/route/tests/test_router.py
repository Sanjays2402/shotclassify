from pathlib import Path

from shotclassify_common import (
    Category,
    Classification,
    CodeFields,
    Confidence,
    ErrorFields,
    ExtractedFields,
    RouteAction,
)
from shotclassify_route.router import ActionRouter


def _cls(primary, score):
    return Classification(
        primary=primary,
        confidences=[Confidence(category=primary, score=score)],
    )


def test_router_loads_example(tmp_path):
    rules = Path("packages/route/rules.example.yaml")
    r = ActionRouter.from_yaml(rules)
    assert len(r.rules) >= 8
    assert r.dry_run is True


def test_router_threshold_skip():
    r = ActionRouter.from_yaml("packages/route/rules.example.yaml")
    cls = _cls(Category.receipt, 0.3)
    decision = r.decide(cls, ExtractedFields())
    assert decision.action == RouteAction.none
    assert "below threshold" in decision.reason


def test_router_dry_run_match():
    r = ActionRouter.from_yaml("packages/route/rules.example.yaml")
    cls = _cls(Category.code_snippet, 0.9)
    fields = ExtractedFields(code=CodeFields(code="print(1)", language="python", line_count=1))
    decision = r.decide(cls, fields)
    assert decision.action == RouteAction.copy_to_clipboard
    assert decision.dry_run is True
    assert decision.executed is False


def test_router_url_template_renders():
    r = ActionRouter.from_yaml("packages/route/rules.example.yaml")
    r.dry_run = False
    cls = _cls(Category.error_stacktrace, 0.9)
    fields = ExtractedFields(
        error=ErrorFields(
            framework="python",
            exception="KeyError",
            message="'nope'",
            likely_cause="Missing key.",
            file="app.py",
            line=8,
        )
    )
    decision = r.decide(cls, fields)
    assert decision.action == RouteAction.open_url_template
    assert "KeyError" in (decision.detail or "")
