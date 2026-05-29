"""Generate synthetic sample screenshots for dogfooding/tests.

Outputs PNGs under samples/. Pure PIL: no personal data.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "samples"
OUT.mkdir(parents=True, exist_ok=True)


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


def _draw(lines: list[str], path: Path, width: int = 720, padding: int = 24, size: int = 20) -> None:
    font = _font(size)
    line_h = size + 8
    height = padding * 2 + line_h * len(lines)
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    y = padding
    for line in lines:
        d.text((padding, y), line, fill="black", font=font)
        y += line_h
    img.save(path)


def make_receipt() -> Path:
    p = OUT / "fake-receipt.png"
    _draw(
        [
            "BLUE BOTTLE COFFEE",
            "1 Ferry Building",
            "San Francisco CA 94111",
            "2026-04-12  09:14",
            "----------------------------",
            "Latte               6.00",
            "Croissant           3.50",
            "Espresso            3.00",
            "----------------------------",
            "Subtotal           12.50",
            "Tax                 1.06",
            "Total             $13.56",
            "VISA *4242  APPROVED",
            "Thank you!",
        ],
        p,
    )
    return p


def make_error() -> Path:
    p = OUT / "fake-error.png"
    _draw(
        [
            "Traceback (most recent call last):",
            '  File "/srv/app/server.py", line 42, in handle',
            "    user = users[user_id]",
            "KeyError: 'u_404'",
            "",
            "During handling of the above exception, another exception occurred:",
            "",
            "  File \"/srv/app/server.py\", line 51, in handle",
            "    raise HTTPException(500)",
            "fastapi.exceptions.HTTPException: 500",
        ],
        p,
        size=18,
    )
    return p


def make_code() -> Path:
    p = OUT / "fake-code.png"
    _draw(
        [
            "def fib(n: int) -> int:",
            "    a, b = 0, 1",
            "    for _ in range(n):",
            "        a, b = b, a + b",
            "    return a",
            "",
            "if __name__ == '__main__':",
            "    print([fib(i) for i in range(10)])",
        ],
        p,
        size=20,
    )
    return p


def make_chat() -> Path:
    p = OUT / "fake-chat.png"
    _draw(
        [
            "Slack  #general",
            "",
            "Alice: deploy looks green",
            "Bob: confirmed, p95 is 120ms",
            "Alice: nice. closing the ticket.",
            "Bob: thx",
        ],
        p,
    )
    return p


def make_all() -> list[Path]:
    return [make_receipt(), make_error(), make_code(), make_chat()]


if __name__ == "__main__":
    for path in make_all():
        print(path)
