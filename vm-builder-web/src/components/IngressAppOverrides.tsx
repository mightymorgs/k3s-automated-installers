import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

interface RegistryApp {
  id: string
  name: string
  display_name?: string
  ingress?: { enabled: boolean; subdomain: string; service_port: number }
}

interface IngressAppOverridesProps {
  selectedApps: string[]
  clusterDefault: string
  appOverrides: Record<string, string>
  onAppOverridesChange: (overrides: Record<string, string>) => void
}

const MODE_LABELS: Record<string, string> = {
  nodeport: 'NodePort',
  tailscale: 'Tailscale',
  cloudflare: 'Cloudflare',
}

export default function IngressAppOverrides({
  selectedApps,
  clusterDefault,
  appOverrides,
  onAppOverridesChange,
}: IngressAppOverridesProps) {
  const apps = useQuery({
    queryKey: ['apps'],
    queryFn: () => api.listApps(),
  })

  if (apps.isLoading || apps.error) return null

  const ingressApps: RegistryApp[] = (apps.data || []).filter(
    (app: RegistryApp) =>
      selectedApps.includes(app.id || app.name) && app.ingress?.enabled
  )

  if (ingressApps.length === 0) return null

  const getEffectiveMode = (appId: string): string =>
    appOverrides[appId] || clusterDefault

  const handleModeChange = (appId: string, mode: string) => {
    const next = { ...appOverrides }
    if (mode === clusterDefault) {
      delete next[appId]
    } else {
      next[appId] = mode
    }
    onAppOverridesChange(next)
  }

  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-700 mb-3">
        Per-App Ingress Mode
      </h3>
      <p className="text-xs text-gray-500 mb-3">
        Override the cluster default ({MODE_LABELS[clusterDefault]}) for individual apps.
      </p>
      <div className="space-y-2">
        {ingressApps.map((app) => {
          const appId = app.id || app.name
          const effective = getEffectiveMode(appId)
          const isOverridden = appId in appOverrides

          return (
            <div
              key={appId}
              className={`flex items-center justify-between px-3 py-2 rounded-md border ${
                isOverridden ? 'border-blue-200 bg-blue-50' : 'border-gray-200 bg-white'
              }`}
            >
              <span className="text-sm text-gray-900">
                {app.display_name || appId}
              </span>
              <select
                value={effective}
                onChange={(e) => handleModeChange(appId, e.target.value)}
                className="text-sm border border-gray-300 rounded px-2 py-1 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
              >
                <option value={clusterDefault}>
                  Default ({MODE_LABELS[clusterDefault]})
                </option>
                {Object.entries(MODE_LABELS)
                  .filter(([key]) => key !== clusterDefault)
                  .map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
              </select>
            </div>
          )
        })}
      </div>
    </div>
  )
}
