import { api } from '@/lib/api'

/** Respuesta de `GET /health` del backend. */
export interface HealthResponse {
  status: string
}

/**
 * Subconjunto del esquema OpenAPI que nos interesa. El backend no expone un
 * endpoint de version propio; FastAPI ya publica la version de la app en
 * `GET /openapi.json` (`info.version`), asi que la leemos de ahi en vez de
 * inventar un endpoint nuevo.
 */
interface OpenApiDocument {
  info: { title: string; version: string }
}

export function fetchHealth(): Promise<HealthResponse> {
  return api.get<HealthResponse>('/health')
}

export async function fetchApiInfo(): Promise<OpenApiDocument['info']> {
  const doc = await api.get<OpenApiDocument>('/openapi.json')
  return doc.info
}
