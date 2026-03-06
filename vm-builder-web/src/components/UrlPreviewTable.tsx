import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

interface UrlPreviewTableProps {
  selectedApps: string[]
  ingressMode: string
  domain: string
  tailnet: string
  vmName: string
  ssoOverrides: Record<string, boolean>
  ingressAppOverrides?: Record<string, string>
}

/** Registry app shape (relevant ingress and SSO fields). */
interface RegistryApp {
  id: string
  name: string
  display_name?: string
  ingress?: { enabled: boolean; subdomain: string; service_port: number }
  sso?: { enabled: boolean }
}

/**
 * UrlPreviewTable -- live URL preview table.
 *
 * Shows one row per selected app that has ingress.enabled = true in the
 * registry. Columns: App, URL, SSO Status. URL generation varies by
 * ingress mode (NodePort, Tailscale, Cloudflare).
 */
export default function UrlPreviewTable({
  selectedApps,
  ingressMode,
  domain,
  tailnet,
  vmName,
  ssoOverrides,
  ingressAppOverrides,
}: UrlPreviewTableProps) {
  const apps = useQuery({
    queryKey: ['apps'],
    queryFn: () => api.listApps(),
  })

  if (apps.isLoading) {
    return <p className="text-gray-500 text-sm">Loading URL preview...</p>
  }

  if (apps.error) {
    return (
      <p className="text-red-600 text-sm">
        Failed to load app data: {(apps.error as Error).message}
      </p>
    )
  }

  // Filter to selected apps with ingress.enabled = true
  const ingressApps: RegistryApp[] = (apps.data || []).filter(
    (app: RegistryApp) =>
      selectedApps.includes(app.id || app.name) && app.ingress?.enabled
  )

  if (ingressApps.length === 0) {
    return null
  }

  const getEffectiveMode = (appId: string): string =>
    ingressAppOverrides?.[appId] || ingressMode

  /** Compute the URL for an app based on ingress mode. */
  const getUrl = (app: RegistryApp): string => {
    const subdomain = app.ingress?.subdomain || app.id || app.name
    const servicePort = app.ingress?.service_port || 80
    const effectiveMode = getEffectiveMode(app.id || app.name)

    switch (effectiveMode) {
      case 'nodeport':
        return `http://<node-ip>:${servicePort}`
      case 'tailscale':
        return tailnet && vmName
          ? `https://${subdomain}.${vmName}.${tailnet}`
          : `https://${subdomain}.<vm>.<tailnet>`
      case 'cloudflare':
        return domain
          ? `https://${subdomain}.${domain}`
          : `https://${subdomain}.<domain>`
      default:
        return `http://<node-ip>:${servicePort}`
    }
  }

  /** Determine effective SSO status for an app. */
  const isSsoProtected = (app: RegistryApp): boolean => {
    const appId = app.id || app.name
    const effectiveMode = getEffectiveMode(appId)
    if (effectiveMode === 'nodeport') return false
    if (appId in ssoOverrides) return ssoOverrides[appId]
    return !!app.sso?.enabled
  }

  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-700 mb-3">
        URL Preview
      </h3>
      <div className="rounded-md border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide px-3 py-2">
                App
              </th>
              <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide px-3 py-2">
                URL
              </th>
              <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide px-3 py-2">
                SSO Status
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {ingressApps.map((app) => {
              const appId = app.id || app.name
              const ssoActive = isSsoProtected(app)
              const url = getUrl(app)

              return (
                <tr key={appId} className="hover:bg-gray-50">
                  <td className="px-3 py-2 text-gray-900 font-medium">
                    {app.display_name || app.name || appId}
                  </td>
                  <td className="px-3 py-2 text-gray-600 font-mono text-xs">
                    {url}
                  </td>
                  <td className="px-3 py-2">
                    <SsoStatusBadge active={ssoActive} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// SSO Status badge with shield icon
// ---------------------------------------------------------------------------

function SsoStatusBadge({ active }: { active: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs font-medium ${
        active ? 'text-blue-700' : 'text-gray-500'
      }`}
    >
      {active ? (
        <svg
          className="w-3.5 h-3.5"
          viewBox="0 0 24 24"
          fill="currentColor"
        >
          <path d="M12 2L3 7v5c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V7l-9-5z" />
        </svg>
      ) : (
        <svg
          className="w-3.5 h-3.5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path d="M12 2L3 7v5c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V7l-9-5z" />
        </svg>
      )}
      {active ? 'Protected' : 'Direct'}
    </span>
  )
}
