"""Chat screenshot extractor."""
from __future__ import annotations

import re

from shotclassify_common import ChatFields, OCRResult

_PLATFORMS = {
    "slack": ["slack", "#general", "@channel"],
    "discord": ["discord"],
    "imessage": ["imessage", "delivered", "read"],
    "whatsapp": ["whatsapp"],
    "telegram": ["telegram"],
    "twitter": ["x.com", "twitter", "retweet"],
}


def _guess_platform(text: str) -> str | None:
    low = text.lower()
    for name, needles in _PLATFORMS.items():
        if any(n in low for n in needles):
            return name
    return None


def enrich_chat(existing: ChatFields | None, ocr: OCRResult) -> ChatFields:
    text = ocr.text or ""
    platform = (existing.platform if existing and existing.platform else None) or _guess_platform(text)
    participants = list(existing.participants) if existing else []
    if not participants:
        # crude: lines starting with NAME:
        for line in text.splitlines():
            m = re.match(r"^([A-Z][A-Za-z0-9 _\-]{1,24}):\s+\S", line)
            if m:
                name = m.group(1).strip()
                if name not in participants and len(participants) < 6:
                    participants.append(name)
    messages = list(existing.messages) if existing else []
    if not messages:
        for line in text.splitlines():
            m = re.match(r"^([A-Z][A-Za-z0-9 _\-]{1,24}):\s+(.+)$", line)
            if m:
                messages.append({"sender": m.group(1).strip(), "text": m.group(2).strip()})
            if len(messages) >= 30:
                break
    return ChatFields(platform=platform, participants=participants, messages=messages)
