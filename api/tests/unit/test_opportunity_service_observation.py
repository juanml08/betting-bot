"""OpportunityService.generate_observation: ademas de las candidatas reporta los
slots evaluados que no califican y los eventos evaluados."""

from datetime import datetime, timezone

from app.filters.opportunity_filters import OpportunityFilterConfig, ThresholdOpportunityFilter
from app.domain.models import OddsQuote
from app.ingestion.providers.sample_data_provider import SampleDataProvider
from app.models.generic_rating_model import GenericRatingModel
from app.odds.providers.sample_odds_provider import SampleOddsProvider
from app.opportunities.opportunity_service import OpportunityService
from app.opportunities.slot import SlotKey, normalize_slot_text
from app.risk.bankroll import FractionalKellyRiskManager, RiskConfig

CLOCK = datetime(2026, 1, 20, 9, 0, tzinfo=timezone.utc)
CAPTURED = datetime(2026, 1, 26, 17, 0)


def _service(*, permissive: bool, odds_provider=None) -> OpportunityService:
    config = (
        OpportunityFilterConfig(min_edge=-1.0, min_expected_value=-1.0, min_odds=1.0, max_odds=100.0)
        if permissive
        else OpportunityFilterConfig(min_edge=10.0, min_expected_value=10.0, min_odds=1.0, max_odds=100.0)
    )
    return OpportunityService(
        data_provider=SampleDataProvider(),
        odds_provider=odds_provider or SampleOddsProvider(),
        probability_model=GenericRatingModel(),
        opportunity_filter=ThresholdOpportunityFilter(config),
        risk_manager=FractionalKellyRiskManager(RiskConfig(kelly_fraction=0.25, max_stake_pct_per_bet=0.05)),
        clock=lambda: CLOCK,
    )


class _OddsProvider:
    def __init__(self, quotes_by_event):
        self._quotes = quotes_by_event

    def get_odds(self, event_external_id):
        return self._quotes.get(event_external_id, [])


def _quote(selection, bookmaker, odds, *, market="1x2", at=CAPTURED, event="S7"):
    return OddsQuote(event, market, selection, bookmaker, odds, at)


def test_candidates_carry_the_provider_captured_at():
    observation = _service(permissive=True).generate_observation(1000.0)

    assert observation.candidates
    assert all(c.captured_at is not None for c in observation.candidates)
    s7 = [c for c in observation.candidates if c.opportunity.event_external_id == "S7"]
    assert {c.captured_at for c in s7} == {CAPTURED}


def test_slots_that_do_not_qualify_are_reported_instead_of_dropped():
    observation = _service(permissive=False).generate_observation(1000.0)

    assert observation.candidates == []
    keys = {(s.key.event_ref, s.key.market_type, s.key.selection, s.key.bookmaker) for s in observation.non_qualifying}
    assert ("S7", "1x2", "home", "samplebook") in keys
    assert all(s.captured_at is not None for s in observation.non_qualifying)


def test_candidates_and_non_qualifying_partition_the_observed_slots():
    permissive = _service(permissive=True).generate_observation(1000.0)
    strict = _service(permissive=False).generate_observation(1000.0)

    all_slots = {
        SlotKey.of(c.opportunity.event_external_id, c.opportunity.market_type,
                   c.opportunity.selection, c.opportunity.bookmaker)
        for c in permissive.candidates
    }
    assert all_slots == {s.key for s in strict.non_qualifying}
    assert not (all_slots & {s.key for s in permissive.non_qualifying})


def test_every_scheduled_event_is_reported_as_evaluated_with_its_observation_time():
    observation = _service(permissive=True).generate_observation(1000.0)

    assert set(observation.evaluated_events) == {"S7", "B7", "T7"}
    assert observation.evaluated_events["S7"] == CAPTURED


def test_event_without_quotes_is_evaluated_at_the_clock_time():
    observation = _service(permissive=True, odds_provider=_OddsProvider({})).generate_observation(1000.0)

    assert observation.candidates == [] and observation.non_qualifying == []
    assert observation.evaluated_events == {"S7": CLOCK, "B7": CLOCK, "T7": CLOCK}


def test_bookmaker_spelling_variants_form_a_single_market():
    provider = _OddsProvider(
        {
            "S7": [
                _quote("home", " Bet365 ", 1.65),
                _quote("draw", "bet365", 3.75),
                _quote("away", "BET365", 5.0),
            ]
        }
    )

    observation = _service(permissive=True, odds_provider=provider).generate_observation(1000.0)

    s7 = [c for c in observation.candidates if c.opportunity.event_external_id == "S7"]
    assert sorted(c.opportunity.selection for c in s7) == ["away", "draw", "home"]
    assert {normalize_slot_text(c.opportunity.bookmaker) for c in s7} == {"bet365"}


def test_generate_opportunities_still_returns_only_the_candidates():
    service = _service(permissive=True)

    assert [c.opportunity for c in service.generate_opportunities(1000.0)] == [
        c.opportunity for c in service.generate_observation(1000.0).candidates
    ]
