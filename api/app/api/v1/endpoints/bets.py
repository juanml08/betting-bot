from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.bets.bet_service import BetService
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.db.repositories.bankroll_repository import BankrollRepository
from app.db.repositories.bet_repository import BetRepository
from app.db.repositories.recommendation_repository import RecommendationRepository
from app.db.repositories.settlement_repository import SettlementRepository
from app.schemas.bet import BetCreate, BetRead, BetSettle
from app.settlements.settlement_service import BetAlreadySettledError, BetNotFoundError, SettlementService

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
    """Registra una apuesta ya colocada: manual (mode='real', el usuario ya
    aposto fuera del sistema) o, en el futuro, generada por TRIAL con dinero
    ficticio (mode='trial'). Este endpoint no envia ni ejecuta ninguna
    apuesta: solo deja constancia.

    El movimiento de bankroll (-stake) solo se aplica para mode='real': el
    ledger de bankroll ficticio de TRIAL todavia no existe (fase futura), asi
    que un Bet mode='trial' no debe mezclarse con la banca real.
    """
    bet_service = BetService(BetRepository(db), RecommendationRepository(db))

    try:
        bet = bet_service.create_bet(
            bet_type=payload.bet_type,
            mode=payload.mode,
            stake=payload.stake,
            bankroll_at_time=BankrollRepository(db).current_balance(settings.initial_bankroll),
            placed_at=datetime.now(timezone.utc),
            legs=[leg.model_dump() for leg in payload.legs],
            recommendation_id=payload.recommendation_id,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="La Recommendation indicada ya tiene un Bet asociado",
        ) from exc

    if payload.mode == "real":
        bankroll_repo = BankrollRepository(db)
        current_balance = bankroll_repo.current_balance(settings.initial_bankroll)
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
    """Liquida un Bet a partir del resultado de cada una de sus BetLeg.

    El movimiento de bankroll solo se aplica para mode='real' (mismo motivo
    que en el registro: el ledger ficticio de TRIAL es una fase futura).
    """
    settlement_service = SettlementService(BetRepository(db), SettlementRepository(db))
    leg_results = {leg.leg_order: leg.result for leg in payload.leg_results}

    try:
        settlement = settlement_service.settle_bet(
            bet_id,
            leg_results=leg_results,
            settled_at=datetime.now(timezone.utc),
            notes=payload.notes,
        )
    except BetNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Apuesta no encontrada") from exc
    except BetAlreadySettledError as exc:
        raise HTTPException(status_code=409, detail="Esta apuesta ya fue liquidada") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    bet = BetRepository(db).get(bet_id)

    if bet.mode == "real":
        bankroll_repo = BankrollRepository(db)
        current_balance = bankroll_repo.current_balance(settings.initial_bankroll)
        change = None
        if settlement.status == "won":
            change = float(settlement.payout)
            reason = "bet_won"
        elif settlement.status == "void":
            change = float(settlement.payout)
            reason = "bet_void"
        # lost y manual_review no generan movimiento de bankroll en esta fase.

        if change is not None:
            bankroll_repo.record(
                occurred_on=settlement.settled_at.date(),
                amount=change,
                reason=reason,
                balance_after=current_balance + change,
                related_bet_id=bet.id,
            )

    db.commit()
    db.refresh(bet)
    return BetRead.model_validate(bet)
