from datetime import date, timedelta

import pytest

from mandate_gate import ALLOW, BLOCK, HOLD, Mandate, MandateGate, ProposedOrder, parse, resolve
from mandate_gate.instruments import company_count


def gate(**kw):
    return MandateGate(Mandate(**kw))


# ---------- the numbers quoted in the case study ----------
def test_tata_matches_13_companies():
    assert company_count(resolve("tata")) == 13

def test_15_etfs_track_nifty_50():
    assert len(resolve("nifty", want_etf=True)) == 15

def test_13_gold_etfs():
    assert len(resolve("gold")) == 13

def test_exact_name_beats_longer_names():
    assert [i.symbol for i in resolve("tata steel")] == ["TATASTEEL"]

def test_exact_ticker_wins():
    assert [i.symbol for i in resolve("TATAPOWER")] == ["TATAPOWER"]


# ---------- parsing what the user said ----------
@pytest.mark.parametrize("sentence,amount", [("put 10k in gold", 10_000), ("invest rs 2,500 in itc", 2_500), ("buy 1.5 lakh of hdfc bank", 150_000)])
def test_amounts(sentence, amount):
    assert parse(sentence).amount_rs == amount

def test_percentage_is_not_a_quantity():
    assert parse("keep buying if it drops 2% more").quantity is None

def test_put_as_verb_is_not_an_option():
    assert parse("put 10k in gold").segment == "EQ_DELIVERY"

def test_puts_as_options_is_fno():
    assert parse("hedge my portfolio with nifty puts").segment == "FNO"

def test_exit_all():
    assert parse("exit everything").side == "EXIT_ALL"

def test_amount_words_are_not_instrument_words():
    assert parse("put 10k in gold").instrument_phrase == "gold"

def test_fraction():
    assert parse("sell half my reliance").fraction == "half"


# ---------- the six case-study scenarios ----------
def test_vague_company_and_default_quantity_hold():
    d = gate().check("buy some tata", ProposedOrder("TATASTEEL", "BUY", 1, 140))
    assert d.verdict == HOLD and len(d.reasons) == 2

def test_vague_gold_holds():
    assert gate().check("put 10k in gold", ProposedOrder("GOLDBEES", "BUY", 180, 55)).verdict == HOLD

def test_clear_sell_within_cap_allows():
    # "reliance" alone matches 8 companies, but the user only holds one of them
    assert gate(holdings={"RELIANCE"}).check("sell half my reliance", ProposedOrder("RELIANCE", "SELL", 3, 1400)).verdict == ALLOW

def test_sell_without_known_holdings_holds():
    assert gate().check("sell half my reliance", ProposedOrder("RELIANCE", "SELL", 3, 1400)).verdict == HOLD

def test_reliance_alone_is_8_companies():
    assert company_count(resolve("reliance")) == 8

def test_fno_blocked_by_scope():
    assert gate().check("hedge my portfolio with nifty puts", ProposedOrder(None, "BUY", 75, 120, segment="FNO")).verdict == BLOCK

def test_fno_blocked_even_if_agent_labels_it_delivery():
    # the agent says delivery, but the user's words say options: the sentence wins
    assert gate().check("buy 1 lot of nifty calls", ProposedOrder("NIFTY", "BUY", 75, 120)).verdict == BLOCK

def test_exit_all_holds():
    assert gate().check("exit everything", ProposedOrder(None, "EXIT_ALL", 0, 0)).verdict == HOLD


# ---------- limits, universe, time box ----------
def test_agent_picked_wrong_stock():
    d = gate().check("buy 5 shares of tata steel", ProposedOrder("TATAPOWER", "BUY", 5, 400))
    assert d.verdict == HOLD and "does not point to" in d.reasons[0]

def test_per_order_cap_blocks_buy():
    assert gate().check("buy 100 shares of tata steel", ProposedOrder("TATASTEEL", "BUY", 100, 140)).verdict == BLOCK

def test_big_sell_holds_not_blocks():
    assert gate().check("sell 100 shares of tata steel", ProposedOrder("TATASTEEL", "SELL", 100, 140)).verdict == HOLD

def test_loop_stopped_by_daily_value_cap():
    g = gate()
    verdicts = [g.check("keep buying 40 shares of tata steel if it drops 2% more", ProposedOrder("TATASTEEL", "BUY", 40, 140)).verdict for _ in range(5)]
    assert verdicts == [ALLOW] * 4 + [BLOCK]

def test_loop_stopped_by_order_count():
    g = gate(max_orders_per_day=3)
    verdicts = [g.check("buy 1 share of tata steel", ProposedOrder("TATASTEEL", "BUY", 1, 140)).verdict for _ in range(4)]
    assert verdicts == [ALLOW] * 3 + [BLOCK]

def test_counters_reset_next_day():
    g = gate(max_orders_per_day=1)
    g.check("buy 1 share of tata steel", ProposedOrder("TATASTEEL", "BUY", 1, 140), today=date.today())
    d = g.check("buy 1 share of tata steel", ProposedOrder("TATASTEEL", "BUY", 1, 140), today=date.today() + timedelta(days=1))
    assert d.verdict == ALLOW

def test_holdings_only():
    assert gate(holdings_only=True, holdings={"RELIANCE"}).check("buy 5 shares of tata steel", ProposedOrder("TATASTEEL", "BUY", 5, 140)).verdict == BLOCK

def test_expired_mandate_blocks():
    g = gate(valid_until=date.today() - timedelta(days=1))
    assert g.check("buy 5 shares of tata steel", ProposedOrder("TATASTEEL", "BUY", 5, 140)).verdict == BLOCK

def test_revoked_blocks():
    assert gate(revoked=True).check("buy 5 shares of tata steel", ProposedOrder("TATASTEEL", "BUY", 5, 140)).verdict == BLOCK

def test_user_can_switch_off_ambiguity_hold():
    assert gate(hold_ambiguous=False).check("buy some tata", ProposedOrder("TATASTEEL", "BUY", 1, 140)).verdict == ALLOW

def test_receipt_keeps_the_sentence():
    d = gate().check("buy some tata", ProposedOrder("TATASTEEL", "BUY", 1, 140, agent="Claude"))
    assert d.receipt["user_said"] == "buy some tata" and d.receipt["agent"] == "Claude"
