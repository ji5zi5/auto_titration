"""Local chemical constant lookup helpers for titration calculations.

The primary data source is the IUPAC Digitized pKa Dataset CSV stored under
``data/chemistry_constants/iupac``.  This module intentionally performs local
CSV lookup only; network-backed fallbacks should be explicit and separately
mocked so data collection never depends on the internet.
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IUPAC_CSV_PATH = REPO_ROOT / "data" / "chemistry_constants" / "iupac" / "iupac_high-confidence_v2_3.csv"


@dataclass(frozen=True)
class ParsedPkaValue:
    """Numeric pKa value parsed from IUPAC text with optional bound qualifier."""

    raw: str
    value: float
    qualifier: str = ""


@dataclass(frozen=True)
class PkaCandidate:
    """One pKa candidate row with source and ranking metadata."""

    unique_id: str
    name: str
    nickname: str
    smiles: str
    inchi: str
    pka_type: str
    pka_value: float
    pka_qualifier: str
    raw_pka_value: str
    temperature_c: float | None
    raw_temperature: str
    assessment: str
    source: str
    acidity_label: str
    cosolvent: str
    remarks: str
    method: str
    reference: str
    match_type: str
    score: float

    @property
    def has_bound_value(self) -> bool:
        return bool(self.pka_qualifier)

    @property
    def source_label(self) -> str:
        parts = [part for part in [self.source, self.reference, self.assessment] if part]
        return " / ".join(parts)

    def as_dict(self) -> dict[str, object]:
        """Return a JSON/CSV-friendly representation."""

        return {
            "unique_id": self.unique_id,
            "name": self.name,
            "nickname": self.nickname,
            "smiles": self.smiles,
            "inchi": self.inchi,
            "pka_type": self.pka_type,
            "pka_value": self.pka_value,
            "pka_qualifier": self.pka_qualifier,
            "raw_pka_value": self.raw_pka_value,
            "temperature_c": self.temperature_c,
            "raw_temperature": self.raw_temperature,
            "assessment": self.assessment,
            "source": self.source,
            "acidity_label": self.acidity_label,
            "cosolvent": self.cosolvent,
            "remarks": self.remarks,
            "method": self.method,
            "reference": self.reference,
            "match_type": self.match_type,
            "score": self.score,
        }


@dataclass(frozen=True)
class ConstantsLookupResult:
    """Result of a local constants lookup."""

    query: str
    candidates: list[PkaCandidate]
    warning: str = ""
    fallback: str = "manual_confirmation"

    @property
    def requires_manual_confirmation(self) -> bool:
        return not self.candidates

    @property
    def ambiguous(self) -> bool:
        return len(self.candidates) > 1

    def best(self) -> PkaCandidate | None:
        return self.candidates[0] if self.candidates else None


class IupacPkaDatabase:
    """In-memory local search over the IUPAC high-confidence pKa CSV."""

    def __init__(self, rows: Iterable[dict[str, str]], *, source_path: str | Path = DEFAULT_IUPAC_CSV_PATH) -> None:
        self.source_path = Path(source_path)
        self.rows = [dict(row) for row in rows]

    @classmethod
    def load(cls, path: str | Path = DEFAULT_IUPAC_CSV_PATH) -> "IupacPkaDatabase":
        path = Path(path)
        with path.open(newline="", encoding="utf-8-sig") as fh:
            return cls(csv.DictReader(fh), source_path=path)

    def lookup(self, query: str, *, limit: int = 20) -> ConstantsLookupResult:
        """Search pKa candidates by exact/substring name, nickname, SMILES, or InChI."""

        normalized_query = _normalize(query)
        if not normalized_query:
            return ConstantsLookupResult(query=query, candidates=[], warning="Empty constants lookup query")

        candidates: list[PkaCandidate] = []
        for row in self.rows:
            match_type = _match_type(row, query, normalized_query)
            if not match_type:
                continue
            candidate = _candidate_from_row(row, match_type=match_type)
            if candidate is not None:
                candidates.append(candidate)

        candidates.sort(key=_sort_key)
        if limit > 0:
            candidates = candidates[:limit]
        if not candidates:
            return ConstantsLookupResult(
                query=query,
                candidates=[],
                warning="No IUPAC pKa candidate found; PubChem/manual confirmation is required.",
            )
        warning = ""
        if len(candidates) > 1:
            warning = "Multiple IUPAC pKa candidates found; user confirmation is recommended."
        return ConstantsLookupResult(query=query, candidates=candidates, warning=warning)

    def lookup_best(self, query: str) -> PkaCandidate | None:
        """Return the highest-ranked candidate, if any."""

        return self.lookup(query, limit=1).best()


def lookup_iupac_pka(query: str, *, path: str | Path = DEFAULT_IUPAC_CSV_PATH, limit: int = 20) -> ConstantsLookupResult:
    """Convenience one-shot local lookup."""

    return IupacPkaDatabase.load(path).lookup(query, limit=limit)


def parse_pka_value(raw: str | float | int | None) -> ParsedPkaValue:
    """Parse IUPAC pKa text such as ``4.76`` or ``<1.6``.

    Raises ``ValueError`` when no numeric value can be recovered.
    """

    text = "" if raw is None else str(raw).strip()
    match = re.search(r"([<>~≈]?)[\s]*([-+]?\d+(?:\.\d+)?)", text)
    if not match:
        raise ValueError(f"cannot parse pKa value: {raw!r}")
    qualifier = match.group(1)
    if qualifier in {"~", "≈"}:
        qualifier = "~"
    return ParsedPkaValue(raw=text, value=float(match.group(2)), qualifier=qualifier)


def _candidate_from_row(row: dict[str, str], *, match_type: str) -> PkaCandidate | None:
    try:
        parsed = parse_pka_value(row.get("pka_value"))
    except ValueError:
        return None
    temperature = _parse_temperature(row.get("T") or row.get("original_T"))
    base_score = _match_score(match_type)
    score = base_score + _quality_score(row, temperature, parsed)
    return PkaCandidate(
        unique_id=row.get("unique_ID") or row.get("unique_ID#") or "",
        name=row.get("original_IUPAC_names", ""),
        nickname=row.get("original_IUPAC_nicknames", ""),
        smiles=row.get("SMILES", ""),
        inchi=row.get("InChI", ""),
        pka_type=row.get("pka_type", ""),
        pka_value=parsed.value,
        pka_qualifier=parsed.qualifier,
        raw_pka_value=parsed.raw,
        temperature_c=temperature,
        raw_temperature=row.get("T") or row.get("original_T", ""),
        assessment=row.get("assessment", ""),
        source=row.get("source", ""),
        acidity_label=row.get("acidity_label", ""),
        cosolvent=row.get("cosolvent", ""),
        remarks=row.get("remarks", ""),
        method=row.get("method", ""),
        reference=row.get("ref", ""),
        match_type=match_type,
        score=score,
    )


def _match_type(row: dict[str, str], original_query: str, normalized_query: str) -> str:
    name = _normalize(row.get("original_IUPAC_names"))
    nickname = _normalize(row.get("original_IUPAC_nicknames"))
    smiles = (row.get("SMILES") or "").strip()
    inchi = (row.get("InChI") or "").strip()
    query_text = original_query.strip()

    if name and normalized_query == name:
        return "exact_name"
    if nickname and normalized_query == nickname:
        return "exact_nickname"
    if smiles and query_text == smiles:
        return "exact_smiles"
    if inchi and query_text == inchi:
        return "exact_inchi"
    if name and normalized_query in name:
        return "name_contains"
    if nickname and normalized_query in nickname:
        return "nickname_contains"
    if smiles and query_text and query_text in smiles:
        return "smiles_contains"
    if inchi and query_text and query_text in inchi:
        return "inchi_contains"
    return ""


def _normalize(value: object) -> str:
    text = "" if value is None else str(value).casefold().strip()
    return re.sub(r"\s+", " ", text)


def _match_score(match_type: str) -> float:
    return {
        "exact_name": 100.0,
        "exact_nickname": 96.0,
        "exact_smiles": 94.0,
        "exact_inchi": 94.0,
        "name_contains": 55.0,
        "nickname_contains": 52.0,
        "smiles_contains": 45.0,
        "inchi_contains": 45.0,
    }.get(match_type, 0.0)


def _quality_score(row: dict[str, str], temperature: float | None, parsed: ParsedPkaValue) -> float:
    score = 0.0
    assessment = _normalize(row.get("assessment"))
    if assessment == "reliable":
        score += 12.0
    elif assessment == "approximate":
        score += 4.0
    elif assessment == "uncertain":
        score -= 6.0

    if temperature is not None:
        score += max(0.0, 8.0 - abs(temperature - 25.0))

    cosolvent = _normalize(row.get("cosolvent"))
    if not cosolvent:
        score += 4.0
    else:
        score -= 8.0

    if parsed.qualifier:
        score -= 3.0

    pka_type = _normalize(row.get("pka_type"))
    if pka_type in {"pka1", "pka"}:
        score += 24.0
    elif pka_type.startswith("pkah"):
        score -= 4.0
    elif pka_type:
        score -= 6.0

    if _looks_deuterated_or_non_aqueous_isotope(row):
        score -= 30.0

    pressure_text = _normalize(" ".join([row.get("pressure", ""), row.get("remarks", "")]))
    if re.search(r"(?:\bp\s*=\s*)?(?:[2-9]\d{2,}|\d{4,})\s*\(?(?:bar|atm)\)?", pressure_text):
        score -= 12.0
    if re.search(r"\bi\s*=\s*(?:0\.[1-9]\d*|[1-9]\d*(?:\.\d+)?)", _normalize(row.get("remarks"))):
        score -= 18.0
    return score


def _looks_deuterated_or_non_aqueous_isotope(row: dict[str, str]) -> bool:
    text = _normalize(
        " ".join(
            [
                row.get("pka_type", ""),
                row.get("remarks", ""),
                row.get("entry_remarks", ""),
                row.get("ref_remarks", ""),
                row.get("cosolvent", ""),
            ]
        )
    )
    isotope_markers = ("d2o", "deuter", "(0-d", "-d", " d3", "-d3", "0d")
    return any(marker in text for marker in isotope_markers)


def _sort_key(candidate: PkaCandidate) -> tuple[float, str]:
    return (-candidate.score, candidate.unique_id)


def _parse_temperature(raw: str | None) -> float | None:
    text = "" if raw is None else str(raw).strip()
    if not text:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    value = float(match.group(0))
    if not math.isfinite(value):
        return None
    return value
