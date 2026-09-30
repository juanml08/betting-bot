"""Decision Engine: decide entre 'simple', 'compound' o 'no_bet'.

Solo analiza y decide: no persiste, no cambia el status de ninguna
Opportunity, no calcula stake (el stake sigue siendo responsabilidad de
RiskManager) y no depende de estado global. Devuelve un DecisionResult que
la capa de orquestacion pasa a RecommendationService sin recalcular nada.

Regla de decision (Fase 5.3):
- Elegibles: Opportunity con status == 'candidate'. Las metricas se recalculan
  desde estimated_probability y odds_value (no se usan expected_value,
  kelly_fraction_suggested ni suggested_stake persistidos).
- Una Opportunity con p fuera de (0, 1), odds <= 1 o valores no finitos es
  invalida: se excluye y se registra en metadata (no lanza excepcion).
- Una propuesta tiene valor si EV = p * o - 1 > 0 (sin thresholds extra).
- Simple vs compound se comparan por G*, el crecimiento logaritmico esperado
  bajo Kelly completo (ver app.valuation.growth). Compound gana solo si
  G*_compound > G*_simple; en empate gana simple. EV no decide.
- Probabilidad conjunta = producto de probabilidades y cuota combinada =
  producto de cuotas: hipotesis de independencia entre legs, NO una verdad
  estadistica (queda registrada en metadata).

Compounds: 2 o 3 legs, sin repetir Opportunity ni event_id, busqueda
exhaustiva sobre las legs que sobreviven a:
1. Poda por dominancia dentro de cada event_id (una dominada no puede ser
   mejor que su dominante ni como simple ni como leg de compound).
2. Limite tecnico `max_legs` (default 100): proteccion contra explosion
   combinatoria, NO una regla de negocio ni preferencia por simple/compound.
   Si se excede, se conservan las max_legs con mayor G* individual (desempate
   por menor id). Este truncamiento NO es lossless: puede cambiar la mejor
   compound. Queda registrado en metadata["technical_limit"].
"""

import math
from dataclasses import dataclass, field
from itertools import combinations
from typing import Sequence

from app.db.models import Opportunity
from app.valuation.growth import expected_value, kelly_full, log_growth

_VALID_MODES = ("real", "trial")
_ELIGIBLE_STATUS = "candidate"
_COMPOUND_MIN_LEGS = 2
_COMPOUND_MAX_LEGS = 3
# Limite tecnico de seguridad contra explosion combinatoria; no es una regla de
# negocio ni una preferencia sobre Simple/Compound.
_DEFAULT_MAX_LEGS = 100
_TIE_DECIMALS = 12  # el ruido de coma flotante no debe decidir empates
_PROBABILITY_METHOD = "independence_assumption"
_CRITERION = "log_growth_full_kelly"


@dataclass(frozen=True)
class DecisionResult:
    mode: str
    bet_type: str  # 'simple' | 'compound' | 'no_bet'
    opportunity_ids: list[int]  # seleccionadas, en orden de leg
    discarded_opportunity_ids: list[int]  # candidatas no seleccionadas
    explanation: str
    decision_metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class _Leg:
    opportunity_id: int
    event_id: int
    probability: float
    odds: float
    expected_value: float
    kelly_full: float
    growth: float


@dataclass(frozen=True)
class _Proposal:
    opportunity_ids: tuple[int, ...]
    event_ids: tuple[int, ...]
    probability: float
    odds: float
    expected_value: float
    kelly_full: float
    growth: float


def _key(value: float) -> float:
    return round(value, _TIE_DECIMALS)


class DecisionEngine:
    def __init__(self, max_legs: int = _DEFAULT_MAX_LEGS):
        if max_legs < 1:
            raise ValueError("max_legs debe ser >= 1")
        self._max_legs = max_legs

    def decide(self, opportunities: Sequence[Opportunity], mode: str) -> DecisionResult:
        if mode not in _VALID_MODES:
            raise ValueError(f"mode invalido: {mode!r} (esperado 'real' o 'trial')")

        ids = [o.id for o in opportunities]
        if any(i is None for i in ids):
            raise ValueError("Todas las Opportunity deben tener id (estar persistidas)")
        if len(set(ids)) != len(ids):
            raise ValueError("No se puede repetir la misma Opportunity")

        candidates = sorted((o for o in opportunities if o.status == _ELIGIBLE_STATUS), key=lambda o: o.id)
        candidate_ids = [o.id for o in candidates]

        invalid_ids: list[int] = []
        legs: list[_Leg] = []
        for o in candidates:
            leg = self._build_leg(o)
            if leg is None:
                invalid_ids.append(o.id)
            else:
                legs.append(leg)

        positive = [leg for leg in legs if leg.expected_value > 0]
        pruned = self._prune_dominated(positive)
        legs_after_pruning = len(pruned)
        dropped = max(0, legs_after_pruning - self._max_legs)
        if dropped:
            pruned = sorted(pruned, key=lambda leg: (-_key(leg.growth), leg.opportunity_id))[: self._max_legs]
        pruned.sort(key=lambda leg: leg.opportunity_id)

        best_simple = self._best_simple(pruned)
        best_compound, best_compound_by_ev, evaluated = self._best_compounds(pruned)

        tie = False
        if best_simple is None:
            selected, selected_reason = "no_bet", "no_positive_expected_value"
        elif best_compound is None:
            selected, selected_reason = "simple", "no_compound_available"
        else:
            tie = _key(best_compound.growth) == _key(best_simple.growth)
            if _key(best_compound.growth) > _key(best_simple.growth):
                selected, selected_reason = "compound", "compound_growth_higher"
            elif tie:
                selected, selected_reason = "simple", "tie_favors_simple"
            else:
                selected, selected_reason = "simple", "simple_growth_higher"

        if selected == "simple":
            selected_ids = list(best_simple.opportunity_ids)
        elif selected == "compound":
            selected_ids = list(best_compound.opportunity_ids)
        else:
            selected_ids = []

        metadata = {
            "selected": selected,
            "selected_reason": selected_reason,
            "comparison": {
                "criterion": _CRITERION,
                "simple_growth": best_simple.growth if best_simple else None,
                "compound_growth": best_compound.growth if best_compound else None,
                "tie": tie,
                "tie_breaker": "simple" if tie else None,
            },
            "simple": self._simple_metadata(best_simple),
            "compound": self._compound_metadata(best_compound),
            "counts": {
                "candidate": len(candidates),
                "invalid": len(invalid_ids),
                "positive_value": len(positive),
                "event_count": len({leg.event_id for leg in positive}),
                "legs_after_pruning": legs_after_pruning,
                "combinations_evaluated": evaluated,
            },
            "invalid_ids": invalid_ids,
            "technical_limit": {
                "max_legs": self._max_legs,
                "hit": dropped > 0,
                "dropped": dropped,
            },
            # Solo diagnostico: no influye en la decision.
            "diagnostics": {
                "ev_only_selection": self._ev_only_selection(pruned, best_compound_by_ev),
                "independent_simples_growth_sum": (
                    sum(leg.growth for leg in pruned if leg.opportunity_id in best_compound.opportunity_ids)
                    if best_compound
                    else None
                ),
            },
        }

        return DecisionResult(
            mode=mode,
            bet_type=selected,
            opportunity_ids=selected_ids,
            discarded_opportunity_ids=[i for i in candidate_ids if i not in selected_ids],
            explanation=self._explain(selected, best_simple, best_compound),
            decision_metadata=metadata,
        )

    @staticmethod
    def _build_leg(o: Opportunity) -> _Leg | None:
        try:
            p = float(o.estimated_probability)
            odds = float(o.odds_value)
        except (TypeError, ValueError):
            return None
        if not (math.isfinite(p) and math.isfinite(odds) and 0.0 < p < 1.0 and odds > 1.0):
            return None
        return _Leg(
            opportunity_id=o.id,
            event_id=o.event_id,
            probability=p,
            odds=odds,
            expected_value=expected_value(p, odds),
            kelly_full=kelly_full(p, odds),
            growth=log_growth(p, odds),
        )

    @staticmethod
    def _prune_dominated(legs: list[_Leg]) -> list[_Leg]:
        """X se elimina si otra leg Y de su evento tiene p y cuota >= (una
        estricta); con empate exacto se conserva la de menor id."""
        kept = []
        for x in legs:
            dominated = any(
                y.event_id == x.event_id
                and y.opportunity_id != x.opportunity_id
                and y.probability >= x.probability
                and y.odds >= x.odds
                and (
                    y.probability > x.probability
                    or y.odds > x.odds
                    or y.opportunity_id < x.opportunity_id
                )
                for y in legs
            )
            if not dominated:
                kept.append(x)
        return kept

    @staticmethod
    def _best_simple(legs: list[_Leg]) -> _Proposal | None:
        if not legs:
            return None
        best = min(
            legs,
            key=lambda leg: (-_key(leg.growth), -_key(leg.expected_value), leg.opportunity_id),
        )
        return _Proposal(
            opportunity_ids=(best.opportunity_id,),
            event_ids=(best.event_id,),
            probability=best.probability,
            odds=best.odds,
            expected_value=best.expected_value,
            kelly_full=best.kelly_full,
            growth=best.growth,
        )

    @staticmethod
    def _best_compounds(legs: list[_Leg]) -> tuple[_Proposal | None, _Proposal | None, int]:
        """(mejor por G*, mejor por EV [solo diagnostico], combinaciones evaluadas)."""
        best = best_key = best_ev = best_ev_key = None
        evaluated = 0
        for size in range(_COMPOUND_MIN_LEGS, _COMPOUND_MAX_LEGS + 1):
            for combo in combinations(legs, size):  # legs ya ordenadas por id
                if len({leg.event_id for leg in combo}) != size:
                    continue
                evaluated += 1
                p = 1.0
                odds = 1.0
                for leg in combo:
                    p *= leg.probability
                    odds *= leg.odds
                ev = expected_value(p, odds)
                if ev <= 0:
                    continue
                ids = tuple(leg.opportunity_id for leg in combo)
                proposal = _Proposal(
                    opportunity_ids=ids,
                    event_ids=tuple(leg.event_id for leg in combo),
                    probability=p,
                    odds=odds,
                    expected_value=ev,
                    kelly_full=kelly_full(p, odds),
                    growth=log_growth(p, odds),
                )
                key = (-_key(proposal.growth), size, ids)
                if best_key is None or key < best_key:
                    best, best_key = proposal, key
                ev_key = (-_key(ev), size, ids)
                if best_ev_key is None or ev_key < best_ev_key:
                    best_ev, best_ev_key = proposal, ev_key
        return best, best_ev, evaluated

    @staticmethod
    def _ev_only_selection(legs: list[_Leg], best_compound_by_ev: _Proposal | None) -> dict:
        """Que habria elegido el criterio anterior (solo EV). Diagnostico."""
        if not legs:
            return {"selected": "no_bet", "opportunity_ids": []}
        simple = min(legs, key=lambda leg: (-_key(leg.expected_value), leg.opportunity_id))
        if best_compound_by_ev and _key(best_compound_by_ev.expected_value) > _key(simple.expected_value):
            return {"selected": "compound", "opportunity_ids": list(best_compound_by_ev.opportunity_ids)}
        return {"selected": "simple", "opportunity_ids": [simple.opportunity_id]}

    @staticmethod
    def _simple_metadata(p: _Proposal | None) -> dict | None:
        if p is None:
            return None
        return {
            "opportunity_id": p.opportunity_ids[0],
            "event_id": p.event_ids[0],
            "probability": p.probability,
            "odds": p.odds,
            "expected_value": p.expected_value,
            "kelly_full": p.kelly_full,
            "growth": p.growth,
        }

    @staticmethod
    def _compound_metadata(p: _Proposal | None) -> dict | None:
        if p is None:
            return None
        return {
            "opportunity_ids": list(p.opportunity_ids),
            "number_of_legs": len(p.opportunity_ids),
            "probability": p.probability,
            "odds": p.odds,
            "expected_value": p.expected_value,
            "kelly_full": p.kelly_full,
            "growth": p.growth,
            "probability_method": _PROBABILITY_METHOD,
        }

    @staticmethod
    def _explain(selected: str, simple: _Proposal | None, compound: _Proposal | None) -> str:
        if selected == "no_bet":
            return "No se encontró ninguna oportunidad con valor esperado positivo."
        if selected == "compound":
            return (
                f"Se seleccionó la compound porque su crecimiento logarítmico esperado "
                f"(G*={compound.growth:.5f}) es superior al de la mejor apuesta simple "
                f"(G*={simple.growth:.5f}), bajo la hipótesis de independencia entre las legs."
            )
        if compound is None:
            return (
                f"Se seleccionó la apuesta simple (G*={simple.growth:.5f}) porque no hay "
                f"ninguna combinación con valor esperado positivo disponible."
            )
        return (
            f"Se seleccionó la apuesta simple porque su crecimiento logarítmico esperado "
            f"(G*={simple.growth:.5f}) es superior o igual al de la mejor combinación "
            f"disponible (G*={compound.growth:.5f})."
        )
