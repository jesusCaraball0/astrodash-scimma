"""Load a monthly WISeREP scrape (metadata.csv + spectra/) for evaluation."""

from __future__ import annotations

import csv
import hashlib
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from astrodash.domain.models.spectrum import Spectrum
from astrodash.infrastructure.ml.leaderboard.taxonomy import canonicalize

_FLOAT_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


@dataclass(frozen=True)
class ChallengeSpectrum:
    iau: str
    filename: str
    wiserep_type: str
    canonical_type: str
    redshift: Optional[float]
    spectrum: Spectrum


def parse_ascii_spectrum(path: Path) -> Optional[tuple[list[float], list[float]]]:
    waves: list[float] = []
    fluxes: list[float] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";", "*", "//")):
            continue
        parts = re.split(r"[\s,]+", line)
        if len(parts) < 2:
            continue
        try:
            waves.append(float(parts[0]))
            fluxes.append(float(parts[1]))
        except ValueError:
            continue
    if len(waves) < 2:
        return None
    return waves, fluxes


def spectrum_identity_key(wave: list[float], flux: list[float]) -> bytes:
    """Identity for residual-0 duplicates (exact wavelength and flux samples)."""
    packed = struct.pack("<" + "d" * len(wave), *wave) + struct.pack(
        "<" + "d" * len(flux), *flux
    )
    return hashlib.sha1(packed).digest()


def drop_duplicate_spectra(rows: list[ChallengeSpectrum]) -> list[ChallengeSpectrum]:
    """Keep one spectrum per object, and drop residual-0 content copies.

    WISeREP often has many uploads of the same SN in one month. Those share a
    type label, so leaving them in the challenge lets one IAU dominate accuracy.
    Exact flux copies are also dropped even when the IAU names differ.
    The first row in IAU/filename order is kept.
    """
    ordered = sorted(rows, key=lambda row: (row.iau.lower(), row.filename.lower()))
    kept: list[ChallengeSpectrum] = []
    seen_iau: set[str] = set()
    seen_identity: set[bytes] = set()
    for row in ordered:
        iau_key = row.iau.lower()
        if iau_key and iau_key in seen_iau:
            continue
        ident = spectrum_identity_key(row.spectrum.x, row.spectrum.y)
        if ident in seen_identity:
            continue
        if iau_key:
            seen_iau.add(iau_key)
        seen_identity.add(ident)
        kept.append(row)
    return kept


def parse_redshift(value: object) -> Optional[float]:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text or text.lower() in {"nan", "none", "null", "-", "n/a", "na"}:
        return None
    match = _FLOAT_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def load_challenge(data_dir: Path) -> list[ChallengeSpectrum]:
    """Return scored-eligible spectra (parseable file + canonical type)."""
    metadata_path = data_dir / "metadata.csv"
    spectra_dir = data_dir / "spectra"
    if not metadata_path.is_file():
        raise FileNotFoundError(f"No metadata.csv in {data_dir}")

    rows: list[ChallengeSpectrum] = []
    with metadata_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            filename = (raw.get("filename") or "").strip()
            if not filename:
                continue
            canonical = canonicalize(raw.get("type"))
            if canonical is None:
                continue
            parsed = parse_ascii_spectrum(spectra_dir / filename)
            if parsed is None:
                continue
            waves, fluxes = parsed
            redshift = parse_redshift(raw.get("redshift"))
            spectrum = Spectrum(
                x=waves,
                y=fluxes,
                redshift=redshift,
                file_name=filename,
                meta={
                    "iau": (raw.get("iau") or "").strip(),
                    "wiserep_type": (raw.get("type") or "").strip(),
                },
            )
            rows.append(
                ChallengeSpectrum(
                    iau=(raw.get("iau") or "").strip(),
                    filename=filename,
                    wiserep_type=(raw.get("type") or "").strip(),
                    canonical_type=canonical,
                    redshift=redshift,
                    spectrum=spectrum,
                )
            )
    return drop_duplicate_spectra(rows)
