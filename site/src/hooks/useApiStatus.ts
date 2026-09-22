import { useQuery } from '@tanstack/react-query'

import { fetchApiInfo, fetchHealth } from '@/lib/health'

/** Estado de conexion con el backend + version declarada por la API. */
export function useApiStatus() {
  const health = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    retry: false,
  })

  const info = useQuery({
    queryKey: ['api-info'],
    queryFn: fetchApiInfo,
    retry: false,
    enabled: health.isSuccess,
  })

  return { health, info }
}
