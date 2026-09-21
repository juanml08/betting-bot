from app.core.config import Settings, get_settings
from app.domain.interfaces import OpportunityFilter, RiskManager
from app.filters.opportunity_filters import OpportunityFilterConfig, ThresholdOpportunityFilter
from app.ingestion.providers.sample_data_provider import SampleDataProvider
from app.models.generic_rating_model import GenericRatingModel
from app.odds.providers.sample_odds_provider import SampleOddsProvider
from app.opportunities.opportunity_service import OpportunityService
from app.risk.bankroll import FractionalKellyRiskManager, RiskConfig


def get_opportunity_filter(settings: Settings | None = None) -> OpportunityFilter:
    settings = settings or get_settings()
    return ThresholdOpportunityFilter(
        OpportunityFilterConfig(
            min_edge=settings.min_edge,
            min_expected_value=settings.min_expected_value,
            min_odds=settings.min_odds,
            max_odds=settings.max_odds,
        )
    )


def get_risk_manager(settings: Settings | None = None) -> RiskManager:
    settings = settings or get_settings()
    return FractionalKellyRiskManager(
        RiskConfig(
            kelly_fraction=settings.kelly_fraction,
            max_stake_pct_per_bet=settings.max_stake_pct_per_bet,
        )
    )


def get_opportunity_service() -> OpportunityService:
    settings = get_settings()
    return OpportunityService(
        data_provider=SampleDataProvider(),
        odds_provider=SampleOddsProvider(),
        probability_model=GenericRatingModel(),
        opportunity_filter=get_opportunity_filter(settings),
        risk_manager=get_risk_manager(settings),
    )
