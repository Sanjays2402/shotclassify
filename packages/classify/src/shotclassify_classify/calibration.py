"""Confidence calibration helpers."""
from __future__ import annotations

from shotclassify_common import Category, Classification


def above_threshold(
    classification: Classification,
    thresholds: dict[Category, float],
    default: float = 0.5,
) -> bool:
    score = classification.confidence_of(classification.primary)
    target = thresholds.get(classification.primary, default)
    return score >= target


def renormalise(classification: Classification) -> Classification:
    total = sum(c.score for c in classification.confidences) or 1.0
    return Classification(
        primary=classification.primary,
        confidences=[
            type(c)(category=c.category, score=round(c.score / total, 6))
            for c in classification.confidences
        ],
        rationale=classification.rationale,
    )
