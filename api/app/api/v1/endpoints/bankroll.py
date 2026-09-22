from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.db.repositories.bankroll_repository import BankrollRepository
from app.schemas.bankroll import BankrollStatus, BankrollTransactionRead

router = APIRouter(prefix="/bankroll", tags=["bankroll"])


@router.get("/status", response_model=BankrollStatus)
def bankroll_status(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> BankrollStatus:
    repo = BankrollRepository(db)
    return BankrollStatus(
        current_balance=repo.current_balance(settings.initial_bankroll),
        initial_bankroll=settings.initial_bankroll,
    )


@router.get("/transactions", response_model=list[BankrollTransactionRead])
def list_transactions(db: Session = Depends(get_db)) -> list[BankrollTransactionRead]:
    repo = BankrollRepository(db)
    return [BankrollTransactionRead.model_validate(t) for t in repo.list_transactions()]
