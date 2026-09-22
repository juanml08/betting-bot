/**
 * Cliente HTTP unico para hablar con la API FastAPI.
 *
 * Toda llamada al backend debe pasar por aqui: la URL base se define en un solo
 * sitio (variable de entorno `VITE_API_BASE_URL`) para no duplicarla por el
 * codigo. Si la variable esta vacia se usan rutas relativas, que en desarrollo
 * resuelve el proxy de Vite (ver `vite.config.ts`) y en produccion resuelve el
 * servidor que sirva el frontend junto a la API.
 */

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '')

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function buildUrl(path: string): string {
  return `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(buildUrl(path), {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })

  if (!response.ok) {
    throw new ApiError(response.status, `${init?.method ?? 'GET'} ${path} -> ${response.status}`)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string, init?: RequestInit) => request<T>(path, { ...init, method: 'GET' }),
  post: <T>(path: string, body?: unknown, init?: RequestInit) =>
    request<T>(path, { ...init, method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
}
