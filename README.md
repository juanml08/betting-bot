# Betting Bot — monorepo

Monorepo con dos aplicaciones independientes:

```
api/    Backend FastAPI (pipeline de analisis, base de datos, API REST)
site/   Frontend React + TypeScript + Vite
```

Cada aplicacion se instala y ejecuta por separado; no comparten gestor de paquetes ni build.

## Backend (`api/`)

Documentacion completa del dominio, pipeline y arquitectura: [api/README.md](api/README.md).

```bash
cd api
poetry install
cp .env.example .env
poetry run alembic upgrade head
poetry run uvicorn app.main:app --reload   # http://localhost:8000
poetry run pytest
```

## Frontend (`site/`)

```bash
cd site
npm install
cp .env.example .env
npm run dev      # http://localhost:5173
npm run build    # tsc -b + vite build
```

## Comunicacion entre ambos

- Toda llamada al backend pasa por el cliente HTTP unico [site/src/lib/api.ts](site/src/lib/api.ts).
- La URL base se define en un solo sitio: `VITE_API_BASE_URL` (ver `site/.env.example`).
- Si `VITE_API_BASE_URL` esta vacia se usan rutas relativas. En desarrollo el dev
  server de Vite las reenvia al backend (`VITE_API_PROXY_TARGET`, por defecto
  `http://localhost:8000`), asi que no hace falta habilitar CORS en la API.

## Reglas de trabajo

Ver [reglas.md](reglas.md) antes de modificar el proyecto.
