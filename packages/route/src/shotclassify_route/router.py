"""Action router.

Rules YAML format:

defaults:
  dry_run: true
rules:
  - category: receipt
    min_confidence: 0.7
    action: save_to_dir
    target: ~/Documents/Receipts
  - category: code_snippet
    min_confidence: 0.6
    action: copy_to_clipboard
  - category: error_stacktrace
    min_confidence: 0.65
    action: open_url_template
    target: "https://github.com/issues/new?title={title}&body={body}"
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from shotclassify_common import (
    Category,
    Classification,
    ExtractedFields,
    RouteAction,
    RouteDecision,
    get_logger,
    get_settings,
)

log = get_logger(__name__)


@dataclass
class Rule:
    category: Category
    action: RouteAction
    target: str | None = None
    min_confidence: float = 0.0


@dataclass
class ActionRouter:
    rules: list[Rule]
    dry_run: bool = True
    slack_webhook: str = ""

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ActionRouter":
        p = Path(path)
        if not p.exists():
            return cls(rules=[], dry_run=True)
        data = yaml.safe_load(p.read_text()) or {}
        defaults = data.get("defaults", {}) or {}
        rules: list[Rule] = []
        for r in data.get("rules", []) or []:
            try:
                rules.append(
                    Rule(
                        category=Category(r["category"]),
                        action=RouteAction(r["action"]),
                        target=r.get("target"),
                        min_confidence=float(r.get("min_confidence", 0.0)),
                    )
                )
            except Exception as exc:
                log.warning("route_rule_skipped", error=str(exc), rule=r)
        return cls(
            rules=rules,
            dry_run=bool(defaults.get("dry_run", True)),
            slack_webhook=str(defaults.get("slack_webhook", "")),
        )

    @classmethod
    def from_settings(cls) -> "ActionRouter":
        s = get_settings()
        router = cls.from_yaml(s.route_rules_path)
        router.dry_run = s.route_dry_run if router.dry_run is None else router.dry_run or s.route_dry_run
        if s.route_slack_webhook:
            router.slack_webhook = s.route_slack_webhook
        return router

    def decide(
        self,
        classification: Classification,
        fields: ExtractedFields,
        image_path: str | Path | None = None,
    ) -> RouteDecision:
        for rule in self.rules:
            if rule.category != classification.primary:
                continue
            score = classification.confidence_of(rule.category)
            if score < rule.min_confidence:
                return RouteDecision(
                    action=RouteAction.none,
                    dry_run=self.dry_run,
                    reason=f"Confidence {score:.2f} below threshold {rule.min_confidence:.2f}.",
                )
            return self._execute(rule, fields, image_path)
        return RouteDecision(
            action=RouteAction.none,
            dry_run=self.dry_run,
            reason="No rule matched.",
        )

    def _execute(
        self, rule: Rule, fields: ExtractedFields, image_path: str | Path | None
    ) -> RouteDecision:
        decision = RouteDecision(
            action=rule.action,
            target=rule.target,
            executed=False,
            dry_run=self.dry_run,
            reason="Matched rule.",
        )
        if self.dry_run:
            decision.detail = f"[dry-run] would {rule.action.value} -> {rule.target}"
            return decision
        try:
            if rule.action == RouteAction.save_to_dir and rule.target and image_path:
                target = Path(os.path.expanduser(rule.target))
                target.mkdir(parents=True, exist_ok=True)
                dest = target / Path(image_path).name
                shutil.copy2(image_path, dest)
                decision.executed = True
                decision.detail = f"Saved to {dest}"
            elif rule.action == RouteAction.copy_to_clipboard:
                payload = fields.code.code if fields.code else json.dumps(
                    fields.model_dump(exclude_none=True)
                )
                _copy_clipboard(payload)
                decision.executed = True
                decision.detail = f"Copied {len(payload)} chars to clipboard."
            elif rule.action == RouteAction.post_to_slack_webhook and self.slack_webhook:
                _post_slack(self.slack_webhook, fields)
                decision.executed = True
                decision.detail = "Posted to Slack webhook."
            elif rule.action == RouteAction.open_url_template and rule.target:
                url = _format_template(rule.target, fields)
                decision.executed = True
                decision.detail = f"Open: {url}"
            else:
                decision.detail = "No-op (action precondition not met)."
        except Exception as exc:
            decision.detail = f"Action failed: {exc}"
        return decision


def _copy_clipboard(text: str) -> None:
    try:
        proc = subprocess.run(
            ["pbcopy"], input=text.encode("utf-8"), check=False, timeout=5
        )
        if proc.returncode == 0:
            return
    except Exception:
        pass
    try:
        subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=text.encode("utf-8"),
            check=False,
            timeout=5,
        )
    except Exception:
        pass


def _post_slack(url: str, fields: ExtractedFields) -> None:
    body = json.dumps({"text": f"ShotClassify: {fields.model_dump(exclude_none=True)}"})
    req = urllib.request.Request(
        url, data=body.encode("utf-8"), headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req, timeout=5).read()  # noqa: S310


def _format_template(template: str, fields: ExtractedFields) -> str:
    ctx: dict[str, Any] = {}
    if fields.error:
        ctx["title"] = urllib.parse.quote(
            f"{fields.error.exception or 'Error'}: {fields.error.message or ''}"
        )
        ctx["body"] = urllib.parse.quote(
            f"Framework: {fields.error.framework}\nFile: {fields.error.file}:{fields.error.line}\n"
            f"Likely cause: {fields.error.likely_cause}"
        )
    return template.format_map({**{"title": "", "body": ""}, **ctx})


def route_decision(
    classification: Classification,
    fields: ExtractedFields,
    image_path: str | Path | None = None,
) -> RouteDecision:
    return ActionRouter.from_settings().decide(classification, fields, image_path)
