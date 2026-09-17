"""Map WISeREP and model type strings onto the five leaderboard classes.

The website_final models (1D CNN, latent) are trained on this label set.
Transformer uses short aliases of the same five classes. DASH predicts a
finer type list that is folded into the same five for scoring.
"""

from __future__ import annotations

import re
from typing import Mapping, Optional

CANONICAL_CLASSES = ("SN Ia", "SN Ib/c", "SN II", "SN IIn", "SLSN-I")

_NON_ALNUM = re.compile(r"[^A-Z0-9]+")


def _token(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().upper()
    if text.startswith("SUPERNOVA"):
        text = text[len("SUPERNOVA") :].strip()
    if text.startswith("SN ") or text.startswith("SN-"):
        text = text[3:].strip()
    elif text.startswith("SNE"):
        text = text[3:].strip()
    return _NON_ALNUM.sub("", text)


def canonicalize(raw: object) -> Optional[str]:
    """Return a canonical class, or ``None`` when the type is out of taxonomy."""
    token = _token(raw)
    if not token or token in {"SN", "UNKNOWN", "OTHER", "NA"}:
        return None

    if token.startswith("SLSN"):
        rest = token[4:]
        if rest.startswith("II") or rest.startswith("2"):
            return None
        return "SLSN-I"

    if token.startswith("IIN"):
        return "SN IIn"

    if token.startswith("IA"):
        return "SN Ia"

    if token.startswith("IB") or token.startswith("IC"):
        return "SN Ib/c"

    if token.startswith("II"):
        return "SN II"

    return None


def class_index(name: str) -> int:
    return CANONICAL_CLASSES.index(name)


def remap_probabilities(raw: Mapping[str, float]) -> dict[str, float]:
    """Sum alias probabilities onto canonical classes and L1-normalize."""
    summed = {name: 0.0 for name in CANONICAL_CLASSES}
    for key, value in raw.items():
        mapped = canonicalize(key)
        if mapped is None:
            continue
        summed[mapped] += float(value)
    total = sum(summed.values())
    if total <= 0:
        return summed
    return {name: summed[name] / total for name in CANONICAL_CLASSES}
