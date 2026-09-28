"""The broker-side gate: check every agent order against the user's mandate before it reaches the exchange."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

from .instruments import Instrument, company_count, resolve
from .parser import Intent, parse

ALLOW, HOLD, BLOCK = "ALLOW", "HOLD", "BLOCK"
SEGMENT_NAMES = {"EQ_DELIVERY": "equity delivery", "INTRADAY": "intraday", "FNO": "F&O", "MCX": "commodities (MCX)"}


@dataclass
class Mandate:
    """Rules the user sets once in the app. Defaults are deliberately conservative."""
    allowed_segments: set[str] = field(default_factory=lambda: {"EQ_DELIVERY"})
    max_order_value: float = 10_000
    max_day_value: float = 25_000
    max_orders_per_day: int = 10
    holdings_only: bool = False
    holdings: set[str] = field(default_factory=set)
    hold_ambiguous: bool = True
    valid_until: date = field(default_factory=lambda: date.today() + timedelta(days=7))
    revoked: bool = False


@dataclass
class ProposedOrder:
    """What the agent wants to send, as structured fields."""
    symbol: str | None
    side: str               # BUY, SELL, EXIT_ALL
    quantity: int
    price: float            # limit price per unit
    segment: str = "EQ_DELIVERY"
    agent: str = "unknown agent"

    @property
    def value(self) -> float:
        return self.quantity * self.price


@dataclass
class DayState:
    day: date = field(default_factory=date.today)
    orders: int = 0
    value: float = 0.0


@dataclass
class Decision:
    verdict: str
    reasons: list[str]
    candidates: list[str]
    receipt: dict


class MandateGate:
    def __init__(self, mandate: Mandate, instruments: tuple[Instrument, ...] | None = None):
        self.mandate = mandate
        self.instruments = instruments
        self.state = DayState()
        self.log: list[dict] = []

    def check(self, sentence: str, order: ProposedOrder, today: date | None = None) -> Decision:
        today = today or date.today()
        if self.state.day != today:
            self.state = DayState(day=today)

        m, intent = self.mandate, parse(sentence)
        segment = intent.segment if intent.segment != "EQ_DELIVERY" else order.segment
        candidates: list[Instrument] = []
        reasons: list[str] = []
        verdict = ALLOW

        def fail(v: str, why: str) -> None:
            nonlocal verdict
            reasons.append(why)
            if v == BLOCK or verdict == ALLOW:
                verdict = v

        # 1. is the mandate live at all?
        if m.revoked:
            fail(BLOCK, "The user has revoked all agent access.")
        elif today > m.valid_until:
            fail(BLOCK, f"The mandate expired on {m.valid_until:%d %b %Y}.")

        # 2. segment scope, judged from the sentence as well as the order
        if segment not in m.allowed_segments:
            fail(BLOCK, f"{SEGMENT_NAMES.get(segment, segment)} is outside this mandate's scope.")

        # 3. irreversible, portfolio-wide actions always need the user
        if intent.side == "EXIT_ALL" or order.side == "EXIT_ALL":
            fail(HOLD, "Exit-all is irreversible, so it needs a tap in the app.")

        # 4. did the sentence clearly name one instrument, and is it the one the agent chose?
        if verdict != BLOCK and order.side != "EXIT_ALL" and segment == "EQ_DELIVERY":
            candidates = resolve(intent.instrument_phrase, intent.wants_etf, self.instruments) if intent.instrument_phrase else []
            # "sell my reliance" can only mean something the user owns
            if order.side == "SELL" and m.holdings:
                owned = [c for c in candidates if c.symbol in m.holdings]
                candidates = owned or candidates
            symbols = [c.symbol for c in candidates]
            if not candidates:
                fail(HOLD, f"Could not match \"{intent.instrument_phrase or sentence}\" to any NSE instrument.")
            elif order.symbol not in symbols:
                fail(HOLD, f"The agent chose {order.symbol}, which the sentence does not point to.")
            elif len(candidates) > 1 and m.hold_ambiguous:
                n = company_count(candidates)
                if all(c.kind == "ETF" for c in candidates):
                    what = f"{len(candidates)} ETFs"
                else:
                    what = f"{n} companies" if n > 1 else f"{len(candidates)} listings"
                fail(HOLD, f"\"{intent.instrument_phrase}\" matches {what}, so the user should pick.")

        # 5. was the size stated, or did the agent fill in a default?
        if verdict != BLOCK and order.side != "EXIT_ALL" and not intent.size_given and m.hold_ambiguous:
            fail(HOLD, f"No quantity or amount in the sentence; the agent assumed {order.quantity}.")

        # 6. universe
        if m.holdings_only and order.side == "BUY" and order.symbol not in m.holdings:
            fail(BLOCK, f"{order.symbol} is not in the user's holdings, and the mandate allows holdings only.")

        # 7. money and count limits
        if order.side == "BUY" and order.value > m.max_order_value:
            fail(BLOCK, f"Order value Rs {order.value:,.0f} is above the Rs {m.max_order_value:,.0f} per-order cap.")
        elif order.side == "SELL" and order.value > m.max_order_value:
            fail(HOLD, f"Sell value Rs {order.value:,.0f} is above the per-order cap, so the user confirms.")
        if self.state.orders + 1 > m.max_orders_per_day:
            fail(BLOCK, f"Daily limit of {m.max_orders_per_day} agent orders reached.")
        if order.side == "BUY" and self.state.value + order.value > m.max_day_value:
            fail(BLOCK, f"This order would take today's agent buying past the Rs {m.max_day_value:,.0f} daily cap.")

        if intent.repeating:
            reasons.append("Repeating instruction noticed: daily caps will stop the loop.")

        if verdict == ALLOW:
            self.state.orders += 1
            self.state.value += order.value if order.side == "BUY" else 0
            if not reasons or reasons == ["Repeating instruction noticed: daily caps will stop the loop."]:
                reasons.insert(0, "Within scope, clearly specified, and under every limit.")

        receipt = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "agent": order.agent,
            "user_said": sentence,
            "read_as": {k: v for k, v in asdict(intent).items() if k not in ("sentence", "notes")},
            "agent_sent": asdict(order) | {"value": order.value},
            "verdict": verdict,
            "reasons": reasons,
            "matches": [f"{c.symbol} ({c.name})" for c in candidates[:15]],
            "match_count": len(candidates),
            "company_count": company_count(candidates),
        }
        self.log.append(receipt)
        return Decision(verdict, reasons, [c.symbol for c in candidates], receipt)
