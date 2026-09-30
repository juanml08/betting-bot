from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_opportunity_service
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.db.repositories.bankroll_repository import BankrollRepository
from app.db.repositories.opportunity_repository import OpportunityRepository
from app.opportunities.opportunity_lifecycle_service import (
    OpportunityLifecycleService,
    UnknownEventError,
)
from app.opportunities.opportunity_service import OpportunityService
from app.schemas.opportunity import OpportunityRead

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.get("", response_model=list[OpportunityRead])
def list_opportunities(status: str | None = None, db: Session = Depends(get_db)) -> list[OpportunityRead]:
    opportunities = OpportunityRepository(db).list_candidates(status=status)
    return [OpportunityRead.model_validate(o) for o in opportunities]


@router.post("/generate", response_model=list[OpportunityRead])
def generate_opportunities(
    db: Session = Depends(get_db),
    service: OpportunityService = Depends(get_opportunity_service),
    settings: Settings = Depends(get_settings),
) -> list[OpportunityRead]:
    """Corre el pipeline (datos -> ... -> oportunidad) y aplica el ciclo de vida.

    No apuesta nada: solo genera, versiona y guarda oportunidades para revision
    manual. Devuelve la version vigente de cada candidata de la pasada.
    """
    bankroll_repo = BankrollRepository(db)
    current_balance = bankroll_repo.current_balance(settings.initial_bankroll)

    observation = service.generate_observation(current_bankroll=current_balance)

    try:
        result = OpportunityLifecycleService(db).apply(observation)
    except UnknownEventError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                f"El evento {sorted(exc.external_ids)[0]} no esta en la base de "
                "datos. Ejecuta scripts/seed_sample_data.py antes de generar oportunidades."
            ),
        )

    return [OpportunityRead.model_validate(o) for o in result.current_candidates]
