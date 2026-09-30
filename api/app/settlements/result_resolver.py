"""Resuelve el resultado de una BetLeg a partir de su Event. Funcion pura:
no accede a la BD, no crea Settlement y no modifica el Bet. La agregacion de
legs y el payout siguen siendo responsabilidad de SettlementService.

    Event.status   Event.result           -> resultado de la leg
    -------------  ---------------------  ------------------------------
    cancelled      (cualquiera / NULL)    -> void
    scheduled/live (cualquiera)           -> unresolved
    finished       NULL / desconocido     -> unresolved (NO es void/lost)
    finished       home_win/away_win/draw -> won / lost

Mercados soportados: '1x2' y 'match_winner' comparten la misma semantica de
ganador del partido; un empate NO es void: toda seleccion distinta de 'draw'
pierde. Una seleccion puede expresarse como home/away/draw o con el nombre del
equipo (competitor_home / competitor_away). Mercado o seleccion desconocidos
-> unresolved (no se inventa un resultado).

Los valores de Event.result son los mismos que usa el backtest
(backtesting.engine._RESULT_TO_SELECTION); se reutiliza esa tabla.
"""

from backtesting.engine import _RESULT_TO_SELECTION

from app.db.models import BetLeg, Event

WON = "won"
LOST = "lost"
VOID = "void"
UNRESOLVED = "unresolved"

_MATCH_WINNER_MARKETS = ("1x2", "match_winner")
_SELECTIONS = ("home", "away", "draw")


def resolve_leg_result(event: Event, leg: BetLeg) -> str:
    if event.status == "cancelled":
        return VOID
    if event.status != "finished":
        return UNRESOLVED
    if leg.market_type not in _MATCH_WINNER_MARKETS:
        return UNRESOLVED

    winning = _RESULT_TO_SELECTION.get(event.result or "")
    if winning is None:
        return UNRESOLVED

    selection = _normalize_selection(event, leg.selection)
    if selection is None:
        return UNRESOLVED
    return WON if selection == winning else LOST


def _normalize_selection(event: Event, selection: str) -> str | None:
    if selection in _SELECTIONS:
        return selection
    if selection == event.competitor_home:
        return "home"
    if selection == event.competitor_away:
        return "away"
    return None
