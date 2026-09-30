"""Settlement automatico de Bets TRIAL pendientes (`settle_due`).

    Bet(trial, pending) -> resolve_leg_result por leg -> SettlementService
        -> Settlement + Bet(settled)

Solo orquesta: no agrega resultados ni calcula payout (SettlementService), ni
decide el resultado de una leg (result_resolver). Una Bet se liquida solo si
TODAS sus legs son resolubles; si alguna es 'unresolved' queda intacta para un
intento posterior (no es error ni manual_review).

Se omiten las Bets que ya tienen Settlement: una Bet en manual_review sigue
con status 'pending' pero no puede liquidarse de nuevo.

Transaccion: unidad = una Bet. Cada Bet se commitea (o hace rollback) por
separado, asi un fallo tecnico no deshace settlements validos de otras Bets.
Los errores tecnicos se aislan y se reportan en `failed`; nunca se convierten
en unresolved/void/lost.

Concurrencia: si dos runners liquidan la misma Bet, el perdedor recibe
IntegrityError por UNIQUE(bet_id). Se hace rollback y solo si el Settlement ya
existe se trata como 'already_settled'; cualquier otro IntegrityError se
reporta como fallo.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Bet, Settlement
from app.db.repositories.bet_repository import BetRepository
from app.db.repositories.settlement_repository import SettlementRepository
from app.settlements.result_resolver import UNRESOLVED, resolve_leg_result
from app.settlements.settlement_service import BetAlreadySettledError, SettlementService

logger = logging.getLogger(__name__)

_MODE = "trial"
_OPEN_BET_STATUS = "pending"


@dataclass
class SettleDueResult:
    processed: int = 0
    settled: list[int] = field(default_factory=list)  # bet_ids liquidados por este runner
    unresolved: list[int] = field(default_factory=list)  # siguen pending
    already_settled: list[int] = field(default_factory=list)  # liquidados por otro proceso
    failed: list[tuple[int, str]] = field(default_factory=list)  # (bet_id, error tecnico)


class TrialSettlementService:
    def __init__(self, db: Session, settlement_service: SettlementService | None = None):
        self._db = db
        self._settlement_repository = SettlementRepository(db)
        self._settlement_service = settlement_service or SettlementService(
            BetRepository(db), self._settlement_repository
        )

    def settle_due(self, *, settled_at: datetime) -> SettleDueResult:
        result = SettleDueResult()
        for bet_id in self._open_bet_ids():
            result.processed += 1
            try:
                outcome = self._settle_one(bet_id, settled_at)
                self._db.commit()
            except Exception as exc:
                self._db.rollback()
                outcome = self._classify_failure(bet_id, exc)
                if outcome == "failed":
                    logger.exception("Fallo tecnico liquidando Bet %s", bet_id)
                    result.failed.append((bet_id, f"{type(exc).__name__}: {exc}"))
                    continue
            getattr(result, outcome).append(bet_id)
        return result

    def _open_bet_ids(self) -> list[int]:
        has_settlement = select(Settlement.id).where(Settlement.bet_id == Bet.id).exists()
        return list(
            self._db.scalars(
                select(Bet.id)
                .where(Bet.mode == _MODE, Bet.status == _OPEN_BET_STATUS, ~has_settlement)
                .order_by(Bet.id)
            )
        )

    def _settle_one(self, bet_id: int, settled_at: datetime) -> str:
        bet = self._db.get(Bet, bet_id)
        leg_results = {leg.leg_order: resolve_leg_result(leg.event, leg) for leg in bet.legs}
        if UNRESOLVED in leg_results.values():
            return "unresolved"
        self._settlement_service.settle_bet(bet_id, leg_results=leg_results, settled_at=settled_at)
        return "settled"

    def _classify_failure(self, bet_id: int, exc: Exception) -> str:
        """Tras el rollback: 'already_settled' solo si es una carrera de
        liquidacion (pre-check o UNIQUE) y el Settlement de verdad existe."""
        if isinstance(exc, (BetAlreadySettledError, IntegrityError)):
            if self._settlement_repository.get_by_bet(bet_id) is not None:
                return "already_settled"
        return "failed"
