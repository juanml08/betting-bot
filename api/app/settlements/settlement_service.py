"""Liquida un Bet: recibe el resultado de cada una de sus BetLeg, agrega un
status final de Settlement segun las reglas de negocio, calcula
payout/profit_loss y persiste todo de forma atomica junto con el `result` de
cada leg.

Reglas de agregacion (ver auditoria de TRIAL / instrucciones de la fase):

    alguna leg = lost                          -> lost   (el lost domina)
    ninguna lost, todas = won                  -> won
    ninguna lost, todas = void                 -> void
    ninguna lost, mezcla de won y void         -> manual_review

`manual_review` dejar deliberadamente sin resolver el payout/profit_loss: la
resolucion economica de una combinada con legs void y won mezclados es una
decision manual, no se infiere automaticamente aqui.

Idempotencia: Settlement.bet_id es UNIQUE tanto a nivel de aplicacion (este
servicio) como de base de datos. Un Bet que ya tiene un Settlement (aunque
sea 'manual_review') no puede volver a liquidarse en esta fase: no existe
todavia un flujo para "resolver" un manual_review sin crear un segundo
Settlement, asi que una segunda liquidacion se rechaza sin efecto.
"""

from datetime import datetime

from app.db.models import Bet, Settlement
from app.db.repositories.bet_repository import BetRepository
from app.db.repositories.settlement_repository import SettlementRepository

_LEG_RESULTS = ("won", "lost", "void")
_FINAL_SETTLEMENT_STATUSES = ("won", "lost", "void")


class BetNotFoundError(Exception):
    pass


class BetAlreadySettledError(Exception):
    pass


class SettlementService:
    def __init__(self, bet_repository: BetRepository, settlement_repository: SettlementRepository):
        self._bet_repository = bet_repository
        self._settlement_repository = settlement_repository

    def settle_bet(
        self,
        bet_id: int,
        *,
        leg_results: dict[int, str],
        settled_at: datetime,
        notes: str | None = None,
    ) -> Settlement:
        bet = self._bet_repository.get(bet_id)
        if bet is None:
            raise BetNotFoundError(f"Bet {bet_id} no encontrado")

        if self._settlement_repository.get_by_bet(bet_id) is not None:
            raise BetAlreadySettledError(f"Bet {bet_id} ya tiene un Settlement")

        legs = sorted(bet.legs, key=lambda leg: leg.leg_order)
        self._validate_leg_results(legs, leg_results)

        for leg in legs:
            leg.result = leg_results[leg.leg_order]

        results = [leg_results[leg.leg_order] for leg in legs]
        status = self._aggregate_status(results)
        payout, profit_loss = self._compute_payout(status, bet, legs)

        settlement = self._settlement_repository.create(
            bet_id=bet_id,
            settled_at=settled_at,
            status=status,
            payout=payout,
            profit_loss=profit_loss,
            notes=notes,
        )

        if status in _FINAL_SETTLEMENT_STATUSES:
            bet.status = "settled"

        return settlement

    @staticmethod
    def _validate_leg_results(legs: list, leg_results: dict[int, str]) -> None:
        expected_orders = {leg.leg_order for leg in legs}
        if set(leg_results.keys()) != expected_orders:
            raise ValueError(
                "Los resultados deben cubrir exactamente los leg_order del Bet: "
                f"esperado {sorted(expected_orders)}, recibido {sorted(leg_results.keys())}"
            )
        for result in leg_results.values():
            if result not in _LEG_RESULTS:
                raise ValueError(f"result de leg invalido: {result!r} (esperado won/lost/void)")

    @staticmethod
    def _aggregate_status(results: list[str]) -> str:
        if any(result == "lost" for result in results):
            return "lost"
        if all(result == "won" for result in results):
            return "won"
        if all(result == "void" for result in results):
            return "void"
        return "manual_review"

    @staticmethod
    def _compute_payout(status: str, bet: Bet, legs: list) -> tuple[float | None, float | None]:
        stake = float(bet.stake)

        if status == "won":
            combined_odds = 1.0
            for leg in legs:
                combined_odds *= float(leg.odds_taken)
            payout = round(stake * combined_odds, 2)
            return payout, round(payout - stake, 2)

        if status == "lost":
            return None, -stake

        if status == "void":
            return stake, 0.0

        # manual_review: la resolucion economica queda pendiente de revision manual.
        return None, None
