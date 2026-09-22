from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.logging import configure_logging

configure_logging()

app = FastAPI(
    title="Betting Bot",
    description=(
        "Analiza eventos deportivos y detecta oportunidades de apuesta con valor esperado "
        "positivo. No ejecuta apuestas: la decision y ejecucion son siempre manuales."
    ),
    version="0.1.0",
)

app.include_router(api_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
