"""Streamlit demo: set a mandate, type what you would tell an AI agent, and see what the gate does."""
from datetime import date, timedelta

import streamlit as st

from mandate_gate import ALLOW, BLOCK, HOLD, Mandate, MandateGate, ProposedOrder, parse, resolve
from mandate_gate.instruments import company_count

st.set_page_config(page_title="Mandate Gate", layout="wide")
st.title("Mandate Gate")
st.caption("A broker-side check for AI trading agents: the user sets the rules once, and every agent order is checked "
           "against them before it goes to the exchange. Prototype on NSE's equity and ETF lists; no real orders are placed.")

# ---------- the mandate ----------
with st.sidebar:
    st.header("Agent Mandate")
    segs = {"EQ_DELIVERY": "Equity delivery", "INTRADAY": "Intraday", "FNO": "F&O", "MCX": "Commodities (MCX)"}
    allowed = {k for k, label in segs.items() if st.toggle(label, value=(k == "EQ_DELIVERY"))}
    max_order = st.number_input("Max per order (Rs)", 1_000, 1_000_000, 10_000, step=1_000)
    max_day = st.number_input("Max per day (Rs)", 1_000, 5_000_000, 25_000, step=1_000)
    max_count = st.number_input("Orders per day", 1, 100, 10)
    hold_vague = st.toggle("Hold vague orders", value=True)
    holdings_only = st.toggle("Only stocks I hold", value=False)
    holdings = st.text_input("My holdings (tickers)", "RELIANCE, TATASTEEL")
    valid_days = st.slider("Valid for (days)", 1, 30, 7)
    revoked = st.toggle("Revoke all agents", value=False)
    if st.button("Reset today's counters"):
        st.session_state.pop("gate", None)

mandate = Mandate(
    allowed_segments=allowed, max_order_value=max_order, max_day_value=max_day, max_orders_per_day=int(max_count),
    holdings_only=holdings_only, holdings={h.strip().upper() for h in holdings.split(",") if h.strip()},
    hold_ambiguous=hold_vague, valid_until=date.today() + timedelta(days=valid_days), revoked=revoked,
)
gate = st.session_state.setdefault("gate", MandateGate(mandate))
gate.mandate = mandate

# ---------- what the user said and what the agent wants to send ----------
examples = ["buy some tata", "put 10k in gold", "sell half my reliance", "hedge my portfolio with nifty puts",
            "exit everything", "buy 5 shares of tata steel"]
left, right = st.columns([1.1, 1])
with left:
    st.subheader("1. What the user told the agent")
    pick = st.selectbox("Try an example", ["(type your own)"] + examples)
    sentence = st.text_input("Sentence", "" if pick == "(type your own)" else pick, placeholder="e.g. buy 10 shares of infosys")
    intent = parse(sentence) if sentence else None
    found = resolve(intent.instrument_phrase, intent.wants_etf) if intent and intent.instrument_phrase else []
    if intent:
        st.write(f"**Read as:** side `{intent.side}`, segment `{intent.segment}`, "
                 f"size `{intent.quantity or intent.amount_rs or intent.fraction or 'not given'}`, "
                 f"instrument words `{intent.instrument_phrase or '-'}`")
        if found:
            st.write(f"**Matches on NSE:** {len(found)} listing(s), {company_count(found)} compan{'y' if company_count(found) == 1 else 'ies'}")
            st.dataframe([{"symbol": f.symbol, "name": f.name, "type": f.kind} for f in found[:15]], hide_index=True, width="stretch")

with right:
    st.subheader("2. What the agent wants to send")
    side = st.selectbox("Side", ["BUY", "SELL", "EXIT_ALL"], index={"SELL": 1, "EXIT_ALL": 2}.get(intent.side if intent else "", 0))
    symbol = st.text_input("Ticker the agent chose", found[0].symbol if found else "")
    qty = st.number_input("Quantity", 0, 100_000, intent.quantity if intent and intent.quantity else 1)
    price = st.number_input("Limit price per unit (Rs)", 0.0, 1_000_000.0, 140.0)
    seg = st.selectbox("Segment the agent used", list(segs), format_func=segs.get)
    agent = st.text_input("Agent", "Claude (Upstox Skill)")
    go = st.button("Send through the gate", type="primary", disabled=not sentence)

if go:
    d = gate.check(sentence, ProposedOrder(symbol or None, side, int(qty), float(price), seg, agent))
    colour = {ALLOW: "green", HOLD: "orange", BLOCK: "red"}[d.verdict]
    st.markdown(f"## :{colour}[{d.verdict}]")
    for r in d.reasons:
        st.write(f"- {r}")
    with st.expander("Intent Receipt (stored with the order)"):
        st.json(d.receipt)

st.divider()
st.subheader("Today's agent activity")
st.write(f"Orders: {gate.state.orders} of {mandate.max_orders_per_day}  |  Buying: Rs {gate.state.value:,.0f} of Rs {mandate.max_day_value:,.0f}")
if gate.log:
    st.dataframe([{"time": r["time"][11:], "agent": r["agent"], "user said": r["user_said"], "verdict": r["verdict"],
                   "why": r["reasons"][0]} for r in reversed(gate.log)], hide_index=True, width="stretch")
