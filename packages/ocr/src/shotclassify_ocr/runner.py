"""Tesseract runner with language detection."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from shotclassify_common import OCRResult, get_settings

from .preprocess import preprocess_for_ocr

try:
    import pytesseract  # type: ignore
except Exception:  # pragma: no cover
    pytesseract = None  # type: ignore

try:
    from langdetect import DetectorFactory, detect  # type: ignore

    DetectorFactory.seed = 0
except Exception:  # pragma: no cover
    detect = None  # type: ignore


@dataclass
class OCRRunner:
    lang: str = "eng"
    psm: int = 6
    deskew: bool = True

    @classmethod
    def from_settings(cls) -> "OCRRunner":
        s = get_settings()
        return cls(lang=s.ocr_lang, psm=s.ocr_psm, deskew=s.ocr_deskew)

    def run(self, image_path: str | Path) -> OCRResult:
        image = Image.open(str(image_path))
        processed, angle = preprocess_for_ocr(image, do_deskew=self.deskew)
        text = ""
        mean_conf = 0.0
        if pytesseract is not None:
            config = f"--psm {self.psm}"
            try:
                text = pytesseract.image_to_string(processed, lang=self.lang, config=config)
                data = pytesseract.image_to_data(
                    processed,
                    lang=self.lang,
                    config=config,
                    output_type=pytesseract.Output.DICT,
                )
                confs = [int(c) for c in data.get("conf", []) if str(c).lstrip("-").isdigit()]
                if confs:
                    mean_conf = float(sum(c for c in confs if c >= 0)) / max(
                        1, len([c for c in confs if c >= 0])
                    ) / 100.0
            except Exception:
                text = ""
        text = text.strip()
        language = "und"
        if detect is not None and text and len(text) > 20:
            try:
                language = detect(text)
            except Exception:
                language = "und"
        return OCRResult(
            text=text,
            language=language,
            word_count=len(text.split()),
            mean_confidence=mean_conf,
            deskew_angle=angle,
            preprocessed=True,
        )


def run_ocr(image_path: str | Path) -> OCRResult:
    return OCRRunner.from_settings().run(image_path)
