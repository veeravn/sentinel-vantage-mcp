"""Grounding check: flag numbers in an agent answer that no tool result supports, and
interpretive or advisory phrasing the tools never produced."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

_NUMBER = re.compile(r"(?<![\w.])[-+]?\$?\d[\d,]*(?:\.\d+)?")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+Z?)?")
_MONTH_DAY = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?\b",
    re.I,
)
_LIST_MARKER = re.compile(r"^\s*(?:[-*]\s*)?\d{1,2}[.)]\s", re.M)
_VERSIONED_TOKEN = re.compile(r"\b[A-Za-z][\w]*[-_]v?\d+[\w]*\b|\b\d+[a-zA-Z]\b")

_SPECULATIVE = [
    r"\btypically\b",
    r"\busually\b",
    r"\boften (?:signals?|indicates?|means?|suggests?|reflects?)\b",
    r"\binstitutional\b",
    r"\bcapitulation\b",
    r"\bsmart money\b",
    r"\b(?:likely|probably) (?:due to|because|driven by|reflects?)\b",
    r"\bsuggests? (?:that )?(?:investors|traders|buyers|sellers)\b",
    r"\bshort[- ]squeeze\b",
    r"\bprice target\b",
    r"\bwill (?:rise|fall|continue|outperform|underperform|rally|drop)\b",
    r"\bI (?:recommend|suggest) (?:buying|selling|you)\b",
    r"\b(?:buy|sell) (?:signal|recommendation)\b",
]


@dataclass(frozen=True)
class GroundingReport:
    ungrounded_numbers: list[str] = field(default_factory=list)
    speculative_phrases: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.ungrounded_numbers or self.speculative_phrases)

    def feedback(self) -> str:
        parts = []
        if self.ungrounded_numbers:
            parts.append(
                "numbers not found in any tool result: " + ", ".join(self.ungrounded_numbers)
            )
        if self.speculative_phrases:
            parts.append(
                "interpretation or advice not supported by tool results: "
                + ", ".join(f"'{p}'" for p in self.speculative_phrases)
            )
        return (
            "Your answer failed a grounding check — " + "; ".join(parts) + ". Rewrite it using "
            "only facts, numbers and reason codes present in the tool results, without "
            "speculation, predictions, or advice. You may call tools if you need more data."
        )


def _to_float(token: str) -> float | None:
    try:
        return float(token.replace(",", "").replace("$", "").lstrip("+"))
    except ValueError:
        return None


def _decimals(token: str) -> int:
    return len(token.split(".")[1]) if "." in token else 0


def _source_numbers(texts: Iterable[str]) -> list[float]:
    out: list[float] = []
    for text in texts:
        for m in _NUMBER.findall(text):
            if (v := _to_float(m)) is not None:
                out.append(abs(v))
    return out


def _matches(value: float, decimals: int, source: list[float]) -> bool:
    tol = 10.0**-decimals
    # Direct, percent-of-fraction (4.7% vs 0.047), and fraction-as-percent (100% vs 1.0).
    variants = ((value, tol), (value / 100.0, tol / 100.0), (value * 100.0, tol * 100.0))
    return any(abs(v - src) <= t for v, t in variants for src in source)


def _answer_numbers(answer: str) -> list[str]:
    text = _ISO_DATE.sub(" ", answer)
    text = _MONTH_DAY.sub(" ", text)
    text = _LIST_MARKER.sub("\n", text)
    text = _VERSIONED_TOKEN.sub(" ", text)
    tokens = []
    for m in _NUMBER.finditer(text):
        tok = m.group(0)
        value = _to_float(tok)
        if value is None:
            continue
        tail = text[m.end() : m.end() + 1]
        is_plain_int = "." not in tok and "$" not in tok and tail != "%"
        if is_plain_int and (abs(value) <= 20 or 1900 <= abs(value) <= 2100):
            continue
        tokens.append(tok)
    return tokens


def check_grounding(answer: str, tool_outputs: Iterable[str]) -> GroundingReport:
    outputs = list(tool_outputs)
    source = _source_numbers(outputs)
    haystack = "\n".join(outputs).lower()

    ungrounded: list[str] = []
    for tok in _answer_numbers(answer):
        value = abs(_to_float(tok) or 0.0)
        if not _matches(value, _decimals(tok), source) and tok not in ungrounded:
            ungrounded.append(tok)

    speculative: list[str] = []
    for pattern in _SPECULATIVE:
        m = re.search(pattern, answer, re.I)
        if m and m.group(0).lower() not in haystack:
            speculative.append(m.group(0))
    return GroundingReport(ungrounded, speculative)
