# Betting Bot

Sistema para **analizar eventos deportivos y detectar oportunidades de apuesta con valor esperado (EV) positivo**.

Este proyecto **no predice ganadores** ni asegura que "esta apuesta va a ganar". Su trabajo es comparar una probabilidad estimada internamente contra la probabilidad implícita de una cuota de mercado, calcular si hay *edge* (valor), aplicar filtros y gestión de riesgo, y presentar **oportunidades candidatas** para que un humano decida.

## Principios de diseño

- **Las apuestas siempre son manuales.** El sistema nunca se conecta a una casa de apuestas para ejecutar apuestas. Solo lee cuotas (de un proveedor pluggable) y registra, vía API, lo que el usuario ya apostó por su cuenta.
- **Nada se asume rentable.** Toda estrategia (modelo de probabilidad + filtros + gestión de riesgo) debe poder evaluarse con backtesting sobre datos históricos antes de confiar en ella.
- **Cada etapa del pipeline es sustituible.** Los proveedores de datos/cuotas y los modelos de probabilidad se definen como `Protocol` en `app/domain/interfaces.py`; se puede reemplazar cualquier etapa (por ejemplo, pasar del modelo Elo genérico a un modelo Poisson específico de fútbol, o de datos de muestra a una API real) sin tocar el resto del sistema.

## Pipeline

```
DATOS DEPORTIVOS (DataProvider)
  -> PROCESAMIENTO (app/processing)
  -> ESTADISTICAS / FEATURES (app/features)
  -> MODELO O ESTRATEGIA (ProbabilityModel, app/models)
  -> PROBABILIDAD ESTIMADA
  -> CUOTA (OddsProvider, app/odds)
  -> PROBABILIDAD IMPLICITA (app/odds/implied_probability.py)
  -> VALUE / EDGE (app/valuation)
  -> FILTROS (app/filters)
  -> GESTION DE RIESGO (app/risk)
  -> PRONOSTICO / OPORTUNIDAD (app/opportunities -> tabla `opportunities`)
  -> DECISION MANUAL (el usuario, fuera del sistema)
  -> REGISTRO DE APUESTA (POST /api/v1/bets, tabla `bets`)
  -> RESULTADO (POST /api/v1/bets/{id}/settle)
  -> METRICAS (backtesting/metrics.py)
  -> EVALUACION DE LA ESTRATEGIA (backtesting/engine.py + tabla `backtest_runs`)
```

Ahora mismo, el sistema incluye **implementaciones de ejemplo** de cada etapa conectable (proveedor de datos/cuotas basado en CSV de muestra, modelo Elo genérico multi-deporte). Son un punto de partida funcional, no el resultado final: para producción hace falta conectar una fuente de datos/cuotas real y, probablemente, un modelo de probabilidad más sofisticado por deporte.

## Estructura del proyecto

```
app/
  core/            configuracion, conexion a base de datos, logging
  domain/          objetos de dominio puros + Protocols de cada etapa
  ingestion/       DataProvider (proveedor de ejemplo por CSV)
  processing/      limpieza/normalizacion de eventos
  features/        construccion de features (ratings Elo, sin look-ahead)
  models/          modelos de probabilidad (baseline: rating generico tipo Elo)
  odds/            OddsProvider (proveedor de ejemplo) + probabilidad implicita
  valuation/       calculo de edge / expected value / Kelly
  filters/         filtros minimos de calidad de una oportunidad
  risk/            Kelly fraccional + gestion de banca
  opportunities/   orquestacion end-to-end del pipeline
  db/              modelos ORM (SQLAlchemy) + repositorios
  schemas/         esquemas Pydantic de la API
  api/             endpoints FastAPI
backtesting/       motor de backtesting + metricas de evaluacion de estrategia
tests/             unitarios, integracion y fixtures de datos de muestra
scripts/           seed de datos de muestra y ejecucion de backtest por CLI
alembic/           migraciones de base de datos
```

## Cómo sustituir una etapa

Ejemplo: para conectar una API real de cuotas en vez del CSV de muestra, se crea una clase que implemente `OddsProvider` (`get_odds(event_external_id) -> list[OddsQuote]`) en `app/odds/providers/`, y se inyecta en `app/api/deps.py` (`get_opportunity_service`) en vez de `SampleOddsProvider`. Nada más del pipeline necesita cambiar.

Lo mismo aplica a `DataProvider` (datos de eventos) y `ProbabilityModel` (modelo de probabilidad, registrable en `app/models/base.py`).

## Requisitos

- Python 3.11+
- [Poetry](https://python-poetry.org/)
- Docker (para levantar MySQL fácilmente) o una instancia MySQL propia

## Puesta en marcha

```bash
# 1. Instalar dependencias
poetry install

# 2. Configurar variables de entorno
cp .env.example .env

# 3. Levantar MySQL
docker-compose up -d mysql

# 4. Aplicar migraciones
poetry run alembic upgrade head

# 5. Cargar datos de muestra (eventos + cuotas de ejemplo, multi-deporte)
poetry run python scripts/seed_sample_data.py

# 6. Levantar la API
poetry run uvicorn app.main:app --reload
```

La documentación interactiva queda en `http://localhost:8000/docs`.

## Flujo de uso típico

1. `POST /api/v1/opportunities/generate` corre el pipeline completo sobre los eventos "scheduled" y guarda las oportunidades candidatas (no apuesta nada).
2. `GET /api/v1/opportunities` para revisar las oportunidades y decidir manualmente si apostar.
3. Si decides apostar (en tu casa de apuestas, fuera del sistema), lo registras con `POST /api/v1/bets`.
4. Cuando el evento termina, liquidas el resultado con `POST /api/v1/bets/{id}/settle`.
5. `GET /api/v1/bankroll/status` para ver el estado de la banca en cualquier momento.

## Backtesting

```bash
poetry run python scripts/run_backtest.py
```

O vía API: `POST /api/v1/backtest/run` con un rango de fechas, que persiste el resultado en `backtest_runs` para poder comparar estrategias a lo largo del tiempo.

El motor de backtesting solo usa, para cada evento evaluado, historia estrictamente anterior a su fecha de inicio (sin look-ahead bias), y calcula ROI, win rate, Brier score (calibración de probabilidad) y máximo drawdown. Estas métricas son la base objetiva para aceptar o descartar una estrategia — un ROI positivo en una muestra pequeña de datos de ejemplo no es evidencia de nada por sí solo.

## Tests

```bash
poetry run pytest
```

## Disclaimer

Este sistema es una herramienta de análisis y apoyo a la decisión. No garantiza beneficios, no ejecuta apuestas automáticamente y no debe interpretarse como asesoramiento financiero. Apostar conlleva riesgo de pérdida de capital.
