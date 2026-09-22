import { Activity, CheckCircle2, Loader2, XCircle } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useApiStatus } from '@/hooks/useApiStatus'
import { API_BASE_URL } from '@/lib/api'

export function HomePage() {
  const { health, info } = useApiStatus()

  return (
    <main className="min-h-svh bg-background text-foreground flex items-center justify-center p-6">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-2xl">
            <Activity className="size-6" />
            Betting Bot
          </CardTitle>
          <CardDescription>
            Analisis de eventos deportivos para detectar oportunidades con valor esperado positivo.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Conexion con el backend</span>
            <ConnectionBadge
              isPending={health.isPending}
              isError={health.isError}
              status={health.data?.status}
            />
          </div>

          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Version del API</span>
            <span className="font-mono">
              {info.isPending && health.isSuccess ? '...' : (info.data?.version ?? 'desconocida')}
            </span>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">URL base del API</span>
            <span className="font-mono">{API_BASE_URL || '(mismo origen)'}</span>
          </div>
        </CardContent>
      </Card>
    </main>
  )
}

interface ConnectionBadgeProps {
  isPending: boolean
  isError: boolean
  status?: string
}

function ConnectionBadge({ isPending, isError, status }: ConnectionBadgeProps) {
  if (isPending) {
    return (
      <Badge variant="secondary">
        <Loader2 className="size-3 animate-spin" />
        Comprobando
      </Badge>
    )
  }

  if (isError) {
    return (
      <Badge variant="destructive">
        <XCircle className="size-3" />
        Sin conexion
      </Badge>
    )
  }

  return (
    <Badge>
      <CheckCircle2 className="size-3" />
      {status ?? 'ok'}
    </Badge>
  )
}
