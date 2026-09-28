"""Load NSE instruments and resolve a plain-English phrase to candidate instruments."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "nse_instruments.csv"

# Words that describe the company form, not the company, so they never count as a match on their own.
NOISE = {
    "limited", "ltd", "the", "of", "and", "&", "india", "company", "corporation", "co",
    "industries", "services", "etf", "fund", "shares", "share", "stock", "stocks",
}


@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str
    kind: str          # EQUITY or ETF
    underlying: str    # index or asset an ETF tracks, blank for equities


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9&]+", text.lower())


@lru_cache(maxsize=1)
def load_instruments(path: str | None = None) -> tuple[Instrument, ...]:
    df = pd.read_csv(path or DATA_FILE).fillna("")
    df = df.drop_duplicates(subset=["symbol"])
    return tuple(
        Instrument(r.symbol.strip(), r.name.strip(), r.kind.strip(), str(r.underlying).strip())
        for r in df.itertuples(index=False)
    )


def resolve(phrase: str, want_etf: bool = False, instruments: tuple[Instrument, ...] | None = None) -> list[Instrument]:
    """Return every instrument a phrase like 'tata', 'reliance industries' or 'nifty etf' could mean.

    Rules, in order:
      1. An exact ticker match (e.g. 'TATASTEEL') wins outright.
      2. If the phrase names an ETF or an index/asset, match on what the ETF tracks.
      3. Otherwise every meaningful word in the phrase must appear, as a whole word,
         in the company name. More matches means a more ambiguous sentence.
    """
    instruments = instruments or load_instruments()
    words = [w for w in _words(phrase) if w not in NOISE]
    if not words:
        return []

    # 1. exact ticker, only when typed in capitals ("RELIANCE"), since many tickers are also ordinary words
    upper = set(re.findall(r"\b[A-Z0-9&]{2,}\b", phrase))
    exact = [i for i in instruments if i.symbol in upper]
    if exact:
        return exact

    # 2. ETFs by underlying (nifty 50, gold, bank ...)
    if want_etf or any(w in {"nifty", "gold", "silver", "sensex", "bank"} for w in words):
        query = " ".join(words)
        if query == "nifty":
            query = "nifty 50"
        etfs = [i for i in instruments if i.kind == "ETF" and query in i.underlying.lower()]
        # for an index, "nifty 50" should not also pull in "Nifty 50 Value 20" and similar variants
        exact = [i for i in etfs if i.underlying.lower() == query] if query.startswith("nifty") else []
        if exact or etfs:
            return exact or etfs

    # 3. whole-word match on company names
    def matches(inst: Instrument) -> bool:
        name_words = set(_words(inst.name))
        return all(w in name_words for w in words)

    found = [i for i in instruments if i.kind == "EQUITY" and matches(i)]
    # a name that is exactly the phrase ("tata steel" -> Tata Steel Limited) beats longer names
    # (only for multi-word phrases: "reliance" alone still means 8 companies)
    exact_name = [i for i in found if [w for w in _words(i.name) if w not in NOISE] == words] if len(words) > 1 else []
    return exact_name or found


def company_count(found: list[Instrument]) -> int:
    """Distinct companies, since one company can list more than one share class."""
    return len({i.name.lower() for i in found})
