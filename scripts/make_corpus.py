"""Generate a benchmark corpus of synthetic screenshots.

Produces N varied images per category under fixtures/synth/<category>/.
All content is fictional. Used for offline calibration and CI smoke tests.
"""
from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "fixtures" / "synth"
random.seed(42)


def _font(size: int = 18) -> ImageFont.ImageFont:
    for cand in (
        "/System/Library/Fonts/Supplemental/Menlo.ttc",
        "/System/Library/Fonts/Menlo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ):
        if Path(cand).exists():
            try:
                return ImageFont.truetype(cand, size)
            except Exception:  # pragma: no cover
                pass
    return ImageFont.load_default()


def _render(lines: list[str], path: Path, width: int = 720, size: int = 18) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    font = _font(size)
    line_h = size + 6
    h = 24 + line_h * len(lines) + 24
    img = Image.new("RGB", (width, h), "white")
    d = ImageDraw.Draw(img)
    y = 24
    for line in lines:
        d.text((24, y), line, fill="black", font=font)
        y += line_h
    img.save(path)


VENDORS = ["Blue Bottle", "Sightglass", "Ritual Coffee", "Verve", "Philz", "Stumptown"]
ITEMS = [("Latte", 6.0), ("Espresso", 3.5), ("Cortado", 4.5), ("Drip", 3.0), ("Croissant", 3.75), ("Bagel", 4.0)]


def gen_receipts(n: int = 30) -> int:
    count = 0
    for i in range(n):
        vendor = random.choice(VENDORS)
        items = random.sample(ITEMS, k=random.randint(1, 4))
        subtotal = round(sum(p for _, p in items), 2)
        tax = round(subtotal * 0.085, 2)
        total = round(subtotal + tax, 2)
        date = f"2026-0{random.randint(1,9)}-{random.randint(10,28):02d}"
        lines = [vendor.upper(), f"  {random.randint(100,999)} Market St", "  San Francisco CA", date, "-" * 32]
        for desc, price in items:
            lines.append(f"{desc:<22} {price:>6.2f}")
        lines += ["-" * 32, f"Subtotal {' ':<14}{subtotal:>6.2f}", f"Tax {' ':<19}{tax:>6.2f}", f"Total {' ':<17}${total:>6.2f}", "Thank you!"]
        _render(lines, OUT / "receipt" / f"receipt-{i:03d}.png")
        count += 1
    return count


CODE_SAMPLES = [
    ("python", ["def fib(n):", "    a, b = 0, 1", "    for _ in range(n):", "        a, b = b, a + b", "    return a"]),
    ("javascript", ["const sum = (a, b) => a + b;", "console.log(sum(2, 3));", "function shout(s){return s.toUpperCase();}"]),
    ("go", ["package main", 'import "fmt"', "func main() {", "    fmt.Println(\"hi\")", "}"]),
    ("rust", ["fn main() {", "    let mut v = vec![1,2,3];", "    v.push(4);", "    println!(\"{:?}\", v);", "}"]),
    ("sql", ["SELECT id, name FROM users", "WHERE active = true", "ORDER BY created_at DESC LIMIT 10;"]),
    ("shell", ["#!/usr/bin/env bash", "set -euo pipefail", "for f in *.png; do", "  echo \"$f\"", "done"]),
]


def gen_code(n: int = 24) -> int:
    count = 0
    for i in range(n):
        _, body = random.choice(CODE_SAMPLES)
        _render(body, OUT / "code_snippet" / f"code-{i:03d}.png", size=20)
        count += 1
    return count


ERROR_SAMPLES = [
    [
        "Traceback (most recent call last):",
        '  File "app.py", line 32, in handler',
        "    user = USERS[uid]",
        "KeyError: 'u_404'",
    ],
    [
        "TypeError: Cannot read properties of undefined (reading 'id')",
        "    at Object.<anonymous> (/srv/index.js:42:13)",
        "    at process.processTicksAndRejections (node:internal/process/task_queues:96:5)",
    ],
    [
        "Exception in thread \"main\" java.lang.NullPointerException",
        "        at com.example.App.run(App.java:24)",
        "        at com.example.App.main(App.java:12)",
    ],
    [
        "django.db.utils.OperationalError: could not connect to server: Connection refused",
        '    Is the server running on host "localhost" (127.0.0.1) and accepting',
        '    TCP/IP connections on port 5432?',
    ],
]


def gen_errors(n: int = 24) -> int:
    count = 0
    for i in range(n):
        body = random.choice(ERROR_SAMPLES)
        _render(body, OUT / "error_stacktrace" / f"error-{i:03d}.png", size=16)
        count += 1
    return count


CHATS = [
    ["#general (Slack)", "alice: deploy is green", "bob: p95 at 120ms", "alice: closing the ticket"],
    ["iMessage", "Mom: are you home for dinner?", "Me: yes :)", "Mom: bring milk"],
    ["WhatsApp", "Sam: surfing tomorrow?", "Pat: tide is at 6am", "Sam: lets go"],
]


def gen_chats(n: int = 15) -> int:
    count = 0
    for i in range(n):
        _render(random.choice(CHATS), OUT / "chat_screenshot" / f"chat-{i:03d}.png")
        count += 1
    return count


DOCS = [
    ["Quarterly Report", "Revenue grew 14% YoY driven by", "expansion in EMEA and a new SMB tier.", "Margins held at 62% gross."],
    ["RFC 0042: Action Routing", "Status: Draft", "We propose a YAML-driven router with", "configurable dry-run thresholds per category."],
]


def gen_docs(n: int = 10) -> int:
    count = 0
    for i in range(n):
        _render(random.choice(DOCS), OUT / "document" / f"doc-{i:03d}.png")
        count += 1
    return count


def main() -> dict[str, int]:
    return {
        "receipt": gen_receipts(),
        "code_snippet": gen_code(),
        "error_stacktrace": gen_errors(),
        "chat_screenshot": gen_chats(),
        "document": gen_docs(),
    }


if __name__ == "__main__":
    print(main())
