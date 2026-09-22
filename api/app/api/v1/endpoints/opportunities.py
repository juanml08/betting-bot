from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_opportunity_service
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.db.repositories.bankroll_repository import BankrollRepository
from app.db.repositories.event_repository import EventRepository
from app.db.repositories.opportunity_repository import OpportunityRepository
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
    """Corre el pipeline (datos -> ... -> oportunidad) y persiste las candidatas.

    No apuesta nada: solo genera y guarda oportunidades para revision manual.
    """
    bankroll_repo = BankrollRepository(db)
    current_balance = bankroll_repo.current_balance(settings.initial_bankroll)

    candidates = service.generate_opportunities(current_bankroll=current_balance)

    event_repo = EventRepository(db)
    opportunity_repo = OpportunityRepository(db)
    saved = []
    for candidate in candidates:
        event = event_repo.get_by_external_id(candidate.opportunity.event_external_id)
        if event is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"El evento {candidate.opportunity.event_external_id} no esta en la base de "
                    "datos. Ejecuta scripts/seed_sample_data.py antes de generar oportunidades."
                ),
            )
        saved.append(opportunity_repo.save_candidate(candidate, event_id=event.id))

    db.commit()
    return [OpportunityRead.model_validate(o) for o in saved]
