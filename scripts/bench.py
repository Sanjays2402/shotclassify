"""Run the corpus through the heuristic+LLM pipeline and report accuracy."""
from __future__ import annotations

import csv
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shotclassify_common import Category
from shotclassify_common.pipeline import process_image

CORPUS = ROOT / "fixtures" / "synth"
REPORT = ROOT / "fixtures" / "bench" / "report.json"
REPORT_CSV = ROOT / "fixtures" / "bench" / "report.csv"


def main() -> None:
    if not CORPUS.exists():
        print("no corpus; run scripts/make_corpus.py first")
        return
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    correct = 0
    total = 0
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    rows: list[dict] = []
    started = time.perf_counter()
    for category_dir in sorted(CORPUS.iterdir()):
        if not category_dir.is_dir():
            continue
        expected = category_dir.name
        for img in sorted(category_dir.glob("*.png")):
            total += 1
            try:
                r = process_image(str(img), save=False)
                got = r.classification.primary.value
            except Exception as exc:
                got = "error"
                rows.append({"file": str(img), "expected": expected, "got": got, "error": str(exc)})
                continue
            confusion[expected][got] += 1
            rows.append(
                {
                    "file": str(img.relative_to(ROOT)),
                    "expected": expected,
                    "got": got,
                    "confidence": r.classification.confidence_of(Category(got)),
                    "elapsed_ms": r.elapsed_ms,
                }
            )
            if got == expected:
                correct += 1
    elapsed = round(time.perf_counter() - started, 2)
    accuracy = round(correct / total, 4) if total else 0.0
    REPORT.write_text(
        json.dumps(
            {
                "total": total,
                "correct": correct,
                "accuracy": accuracy,
                "elapsed_s": elapsed,
                "confusion": {k: dict(v) for k, v in confusion.items()},
            },
            indent=2,
        )
    )
    with REPORT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "expected", "got", "confidence", "elapsed_ms", "error"])
        w.writeheader()
        w.writerows(rows)
    print(f"accuracy={accuracy} ({correct}/{total}) in {elapsed}s -> {REPORT}")


if __name__ == "__main__":
    main()
