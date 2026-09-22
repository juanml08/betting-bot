/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** URL base de la API FastAPI. Vacia = misma origen (proxy de Vite en dev). */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
