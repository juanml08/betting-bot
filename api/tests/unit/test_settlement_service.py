from datetime import datetime, timezone

import pytest

from app.db.models import Event
from app.db.repositories.bet_repository import BetRepository
from app.db.repositories.settlement_repository import SettlementRepository
from app.settlements.settlement_service import (
    BetAlreadySettledError,
    BetNotFoundError,
    SettlementService,
)


def _make_event(db_session, external_id="EV1") -> Event:
    event = Event(
        external_id=external_id,
        sport="soccer",
        league="Test League",
        competitor_home="Home FC",
        competitor_away="Away FC",
        start_time=datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc),
        status="scheduled",
        source="sample",
        result=None,
    )
    db_session.add(event)
    db_session.flush()
    return event


def _leg(event_id: int, odds_taken: float = 1.9, **overrides) -> dict:
    leg = dict(
        event_id=event_id,
        market_type="1x2",
        selection="home",
        bookmaker="SampleBook",
        odds_taken=odds_taken,
    )
    leg.update(overrides)
    return leg


@pytest.fixture()
def bet_repo(db_session) -> BetRepository:
    return BetRepository(db_session)


@pytest.fixture()
def service(db_session, bet_repo) -> SettlementService:
    return SettlementService(bet_repo, SettlementRepository(db_session))


def _make_simple_bet(db_session, bet_repo, *, odds_taken=2.0, stake=50.0):
    event = _make_event(db_session)
    bet = bet_repo.create(
        bet_type="simple",
        mode="real",
        stake=stake,
        bankroll_at_time=1000.0,
        placed_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
        legs=[_leg(event.id, odds_taken=odds_taken)],
    )
    db_session.commit()
    return bet


def _make_compound_bet(db_session, bet_repo, *, odds=(1.8, 1.7), stake=20.0):
    events = [_make_event(db_session, f"EV{i}") for i in range(len(odds))]
    legs = [_leg(e.id, odds_taken=o, selection=f"sel{i}") for i, (e, o) in enumerate(zip(events, odds))]
    bet = bet_repo.create(
        bet_type="compound",
        mode="real",
        stake=stake,
        bankroll_at_time=1000.0,
        placed_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
        legs=legs,
    )
    db_session.commit()
    return bet


_SETTLED_AT = datetime(2026, 1, 6, tzinfo=timezone.utc)


def test_all_legs_won_settles_as_won(db_session, bet_repo, service):
    bet = _make_compound_bet(db_session, bet_repo, odds=(1.8, 1.7), stake=20.0)

    settlement = service.settle_bet(
        bet.id, leg_results={1: "won", 2: "won"}, settled_at=_SETTLED_AT
    )
    db_session.commit()

    assert settlement.status == "won"
    assert float(settlement.payout) == round(20.0 * 1.8 * 1.7, 2)
    assert float(settlement.profit_loss) == round(20.0 * 1.8 * 1.7 - 20.0, 2)


def test_one_leg_lost_settles_as_lost(db_session, bet_repo, service):
    bet = _make_compound_bet(db_session, bet_repo, odds=(1.8, 1.7), stake=20.0)

    settlement = service.settle_bet(
        bet.id, leg_results={1: "won", 2: "lost"}, settled_at=_SETTLED_AT
    )
    db_session.commit()

    assert settlement.status == "lost"
    assert settlement.payout is None
    assert float(settlement.profit_loss) == -20.0


def test_lost_plus_void_settles_as_lost(db_session, bet_repo, service):
    bet = _make_compound_bet(db_session, bet_repo, odds=(1.8, 1.7), stake=20.0)

    settlement = service.settle_bet(
        bet.id, leg_results={1: "lost", 2: "void"}, settled_at=_SETTLED_AT
    )
    db_session.commit()

    assert settlement.status == "lost"
    assert float(settlement.profit_loss) == -20.0


def test_all_legs_void_settles_as_void(db_session, bet_repo, service):
    bet = _make_compound_bet(db_session, bet_repo, odds=(1.8, 1.7), stake=20.0)

    settlement = service.settle_bet(
        bet.id, leg_results={1: "void", 2: "void"}, settled_at=_SETTLED_AT
    )
    db_session.commit()

    assert settlement.status == "void"
    assert float(settlement.payout) == 20.0
    assert float(settlement.profit_loss) == 0.0


def test_won_plus_void_settles_as_manual_review(db_session, bet_repo, service):
    bet = _make_compound_bet(db_session, bet_repo, odds=(1.8, 1.7), stake=20.0)

    settlement = service.settle_bet(
        bet.id, leg_results={1: "won", 2: "void"}, settled_at=_SETTLED_AT
    )
    db_session.commit()

    assert settlement.status == "manual_review"
    assert settlement.payout is None
    assert settlement.profit_loss is None


def test_simple_won_profit_loss(db_session, bet_repo, service):
    bet = _make_simple_bet(db_session, bet_repo, odds_taken=2.0, stake=50.0)

    settlement = service.settle_bet(bet.id, leg_results={1: "won"}, settled_at=_SETTLED_AT)
    db_session.commit()

    assert float(settlement.payout) == 100.0
    assert float(settlement.profit_loss) == 50.0


def test_simple_lost_profit_loss(db_session, bet_repo, service):
    bet = _make_simple_bet(db_session, bet_repo, odds_taken=2.0, stake=50.0)

    settlement = service.settle_bet(bet.id, leg_results={1: "lost"}, settled_at=_SETTLED_AT)
    db_session.commit()

    assert settlement.payout is None
    assert float(settlement.profit_loss) == -50.0


def test_simple_void_profit_loss_is_zero(db_session, bet_repo, service):
    bet = _make_simple_bet(db_session, bet_repo, odds_taken=2.0, stake=50.0)

    settlement = service.settle_bet(bet.id, leg_results={1: "void"}, settled_at=_SETTLED_AT)
    db_session.commit()

    assert float(settlement.payout) == 50.0
    assert float(settlement.profit_loss) == 0.0


def test_bet_transitions_to_settled_on_final_status(db_session, bet_repo, service):
    bet = _make_simple_bet(db_session, bet_repo)

    service.settle_bet(bet.id, leg_results={1: "won"}, settled_at=_SETTLED_AT)
    db_session.commit()

    reloaded = bet_repo.get(bet.id)
    assert reloaded.status == "settled"


def test_bet_stays_pending_on_manual_review(db_session, bet_repo, service):
    bet = _make_compound_bet(db_session, bet_repo, odds=(1.8, 1.7))

    service.settle_bet(bet.id, leg_results={1: "won", 2: "void"}, settled_at=_SETTLED_AT)
    db_session.commit()

    reloaded = bet_repo.get(bet.id)
    assert reloaded.status == "pending"


def test_only_one_settlement_per_bet(db_session, bet_repo, service):
    bet = _make_simple_bet(db_session, bet_repo)

    service.settle_bet(bet.id, leg_results={1: "won"}, settled_at=_SETTLED_AT)
    db_session.commit()

    with pytest.raises(BetAlreadySettledError):
        service.settle_bet(bet.id, leg_results={1: "lost"}, settled_at=_SETTLED_AT)


def test_second_settlement_after_manual_review_is_also_rejected(db_session, bet_repo, service):
    bet = _make_compound_bet(db_session, bet_repo, odds=(1.8, 1.7))

    service.settle_bet(bet.id, leg_results={1: "won", 2: "void"}, settled_at=_SETTLED_AT)
    db_session.commit()

    with pytest.raises(BetAlreadySettledError):
        service.settle_bet(bet.id, leg_results={1: "won", 2: "won"}, settled_at=_SETTLED_AT)


def test_settle_nonexistent_bet_raises(db_session, service):
    with pytest.raises(BetNotFoundError):
        service.settle_bet(999999, leg_results={1: "won"}, settled_at=_SETTLED_AT)


def test_leg_results_must_match_bet_legs_exactly(db_session, bet_repo, service):
    bet = _make_simple_bet(db_session, bet_repo)

    with pytest.raises(ValueError):
        service.settle_bet(bet.id, leg_results={1: "won", 2: "won"}, settled_at=_SETTLED_AT)


def test_leg_result_value_must_be_valid(db_session, bet_repo, service):
    bet = _make_simple_bet(db_session, bet_repo)

    with pytest.raises(ValueError):
        service.settle_bet(bet.id, leg_results={1: "pending"}, settled_at=_SETTLED_AT)


def test_leg_results_update_bet_leg_result_field(db_session, bet_repo, service):
    bet = _make_compound_bet(db_session, bet_repo, odds=(1.8, 1.7))

    service.settle_bet(bet.id, leg_results={1: "won", 2: "lost"}, settled_at=_SETTLED_AT)
    db_session.commit()

    reloaded = bet_repo.get(bet.id)
    results = {leg.leg_order: leg.result for leg in reloaded.legs}
    assert results == {1: "won", 2: "lost"}
