"""Read what a user actually asked for, independently of what the agent decided to send."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

FNO = re.compile(r"\b(calls?|puts|put option|options?|ce|pe|futures?|fut|lots?|strike|expiry|hedge|straddle|strangle)\b")
MCX = re.compile(r"\b(mcx|crude|natural gas|natgas|commodit(y|ies))\b")
INTRADAY = re.compile(r"\b(intraday|mis|square off by|same day)\b")
EXIT_ALL = re.compile(r"\b(exit|sell|close|square off)\s+(everything|all( my)?( positions| holdings)?|my whole portfolio)\b")
LOOP = re.compile(r"\b(keep (buying|selling)|every time|whenever|each time|repeatedly|until)\b")
SELL = re.compile(r"\b(sell|exit|book( profit)?|dump|get out of)\b")
BUY = re.compile(r"\b(buy|purchase|add|invest|put|get me)\b")

QTY = re.compile(r"\b(\d+)\s*(shares?|units?|qty|quantity|lots?)?\b")
AMOUNT = re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|l|cr|crore)?\b|\b([\d,]+(?:\.\d+)?)\s*(k|lakh|cr|crore)\b")
FRACTION = re.compile(r"\b(half|all|entire|full|quarter|third)\b")

# words that describe the order, not the instrument
FILLER = {
    "buy", "sell", "purchase", "add", "invest", "put", "get", "me", "some", "my", "a", "an", "the", "in",
    "into", "of", "for", "worth", "rs", "inr", "shares", "share", "units", "unit", "qty", "stock", "stocks",
    "please", "now", "today", "half", "all", "entire", "full", "quarter", "third", "position", "holding",
    "holdings", "at", "market", "limit", "price", "k", "lakh", "cr", "crore", "exit", "book", "profit",
    "dump", "out", "to", "and", "if", "it", "drops", "more", "keep", "buying", "selling", "more", "etf",
    "fund", "on", "with", "portfolio", "just", "few", "little", "bit",
}
MULT = {"k": 1_000, "lakh": 100_000, "l": 100_000, "cr": 10_000_000, "crore": 10_000_000}


@dataclass
class Intent:
    sentence: str
    side: str | None = None              # BUY, SELL, EXIT_ALL
    segment: str = "EQ_DELIVERY"         # EQ_DELIVERY, INTRADAY, FNO, MCX
    quantity: int | None = None
    amount_rs: float | None = None
    fraction: str | None = None          # "half", "all" ...
    wants_etf: bool = False
    repeating: bool = False
    instrument_phrase: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def size_given(self) -> bool:
        return any(v is not None for v in (self.quantity, self.amount_rs, self.fraction))


def parse(sentence: str) -> Intent:
    s = sentence.lower().strip()
    it = Intent(sentence=sentence)

    if EXIT_ALL.search(s):
        it.side = "EXIT_ALL"
    elif SELL.search(s):
        it.side = "SELL"
    elif BUY.search(s):
        it.side = "BUY"

    if MCX.search(s):
        it.segment = "MCX"
    elif FNO.search(s):
        it.segment = "FNO"
    elif INTRADAY.search(s):
        it.segment = "INTRADAY"

    it.repeating = bool(LOOP.search(s))
    it.wants_etf = "etf" in s

    m = AMOUNT.search(s)
    if m:
        num = m.group(1) or m.group(3)
        unit = m.group(2) or m.group(4)
        it.amount_rs = float(num.replace(",", "")) * MULT.get(unit or "", 1)
    else:
        q = QTY.search(s)
        # a bare number counts as a quantity only if it is not a percentage
        if q and not re.search(rf"\b{q.group(1)}\s*%", s):
            it.quantity = int(q.group(1))

    f = FRACTION.search(s)
    if f and it.side != "EXIT_ALL":
        it.fraction = f.group(1)

    words = re.findall(r"[A-Za-z0-9&]+", sentence.strip())
    it.instrument_phrase = " ".join(
        w for w in words if w.lower() not in FILLER and not FNO.fullmatch(w.lower())
        and not re.fullmatch(r"\d+(k|l|cr|lakh|crore)?", w.lower())
    )
    return it
