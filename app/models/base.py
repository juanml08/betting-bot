"""Registro simple de modelos de probabilidad disponibles.

Anadir un nuevo modelo (p.ej. uno especifico de futbol basado en Poisson, o
un modelo de ML entrenado) consiste en implementar app.domain.interfaces.ProbabilityModel
y registrarlo aqui con un nombre unico. El resto del pipeline solo conoce el
Protocol, nunca la implementacion concreta.
"""

from app.domain.interfaces import ProbabilityModel

_REGISTRY: dict[str, ProbabilityModel] = {}


def register_model(model: ProbabilityModel) -> None:
    _REGISTRY[model.name] = model


def get_model(name: str) -> ProbabilityModel:
    if name not in _REGISTRY:
        raise KeyError(f"No hay ningun modelo de probabilidad registrado con el nombre '{name}'")
    return _REGISTRY[name]


def list_models() -> list[str]:
    return list(_REGISTRY.keys())
