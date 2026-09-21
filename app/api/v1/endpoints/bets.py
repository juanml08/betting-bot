from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.db.repositories.bankroll_repository import BankrollRepository
from app.db.repositories.bet_repository import BetRepository
from app.schemas.bet import BetCreate, BetRead, BetSettle

router = APIRouter(prefix="/bets", tags=["bets"])


@router.get("", response_model=list[BetRead])
def list_bets(status: str | None = None, db: Session = Depends(get_db)) -> list[BetRead]:
    bets = BetRepository(db).list_bets(status=status)
    return [BetRead.model_validate(b) for b in bets]


@router.post("", response_model=BetRead, status_code=201)
def register_bet(
    payload: BetCreate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BetRead:
    """Registra una apuesta que el usuario YA realizo manualmente fuera del sistema.

    Este endpoint no envia ni ejecuta ninguna apuesta: solo deja constancia
    de la decision humana para poder medir el resultado despues.
    """
    bankroll_repo = BankrollRepository(db)
    current_balance = bankroll_repo.current_balance(settings.initial_bankroll)

    bet_repo = BetRepository(db)
    bet = bet_repo.create(
        event_id=payload.event_id,
        market_type=payload.market_type,
        selection=payload.selection,
        odds_taken=payload.odds_taken,
        stake=payload.stake,
        bankroll_at_time=current_balance,
        placed_at=datetime.now(timezone.utc),
        opportunity_id=payload.opportunity_id,
        notes=payload.notes,
    )

    bankroll_repo.record(
        occurred_on=bet.placed_at.date(),
        amount=-payload.stake,
        reason="bet_placed",
        balance_after=current_balance - payload.stake,
        related_bet_id=bet.id,
    )

    db.commit()
    db.refresh(bet)
    return BetRead.model_validate(bet)


@router.post("/{bet_id}/settle", response_model=BetRead)
def settle_bet(
    bet_id: int,
    payload: BetSettle,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BetRead:
    """Registra el resultado de una apuesta ya decidido fuera del sistema (won/lost/void/pushed)."""
    bet_repo = BetRepository(db)
    bet = bet_repo.get(bet_id)
    if bet is None:
        raise HTTPException(status_code=404, detail="Apuesta no encontrada")
    if bet.status != "pending":
        raise HTTPException(status_code=409, detail="Esta apuesta ya fue liquidada")

    settled_at = datetime.now(timezone.utc)
    bet_repo.settle(bet_id, status=payload.status, settled_at=settled_at)

    if payload.status == "won":
        payout = float(bet.stake) * float(bet.odds_taken)
        change = payout - float(bet.stake)
    elif payload.status in ("lost",):
        change = 0.0  # el stake ya se desconto de la banca al registrar la apuesta
    else:  # void / pushed: se devuelve el stake
        change = float(bet.stake)

    if change != 0.0:
        bankroll_repo = BankrollRepository(db)
        current_balance = bankroll_repo.current_balance(settings.initial_bankroll)
        bankroll_repo.record(
            occurred_on=settled_at.date(),
            amount=change,
            reason=f"bet_{payload.status}",
            balance_after=current_balance + change,
            related_bet_id=bet.id,
        )

    db.commit()
    db.refresh(bet)
    return BetRead.model_validate(bet)
