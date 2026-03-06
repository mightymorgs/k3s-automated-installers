import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

/**
 * IngressStatusTable -- post-deploy ingress status table.
 *
 * Displays one row per installed app that has ingress.enabled in the
 * registry. Columns: App, URL (clickable for Tailscale/Cloudflare),
 * SSO Status, Certificate Expiry.
 *
 * URL generation follows the same logic as UrlPreviewTable but uses
 * actual inventory data (mode, domain, tailnet).
 */

/** Registry app shape (relevant ingress and SSO fields). */
interface RegistryApp {
  id: string
  name: string
  display_name?: string
  ingress?: { enabled: boolean; subdomain: string; service_port: number }
  sso?: { enabled: boolean; bypass_paths?: string[] }
}

interface IngressStatusTableProps {
  inventory: any // Full inventory object
  apps: any[] // App registry data
}

export default function IngressStatusTable({
  inventory,
  apps,
}: IngressStatusTableProps) {
  const ingress = inventory?.ingress || {}
  const mode: string = ingress.mode || 'nodeport'
  const domain: string = ingress.domain || ''
  const ssoOverrides: Record<string, boolean> = ingress.sso_overrides || {}
  const vmHostname: string = inventory?.identity?.hostname || ''
  const selectedApps: string[] = inventory?.apps?.selected_apps || []

  // Fetch tailnet from BWS via API (inventory only has the pointer key)
  const tailnetQuery = useQuery({
    queryKey: ['tailnet'],
    queryFn: () => api.getTailnet(),
    enabled: mode === 'tailscale',
    retry: false,
  })
  const tailnet: string = tailnetQuery.data?.tailnet || ''

  // Filter to selected apps with ingress.enabled = true in the registry
  const ingressApps: RegistryApp[] = (apps || []).filter(
    (app: RegistryApp) =>
      selectedApps.includes(app.id || app.name) && app.ingress?.enabled
  )

  if (ingressApps.length === 0) {
    return null
  }

  /** Compute the URL for an app based on ingress mode. */
  const getUrl = (app: RegistryApp): string => {
    const subdomain = app.ingress?.subdomain || app.id || app.name
    const servicePort = app.ingress?.service_port || 80

    switch (mode) {
      case 'nodeport':
        return `http://<node-ip>:${servicePort}`
      case 'tailscale':
        return tailnet && vmHostname
          ? `https://${subdomain}.${vmHostname}.${tailnet}`
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
    if (mode === 'nodeport') return false
    const appId = app.id || app.name
    if (appId in ssoOverrides) return ssoOverrides[appId]
    return !!app.sso?.enabled
  }

  /** Determine certificate expiry text based on ingress mode. */
  const getCertExpiry = (): string => {
    switch (mode) {
      case 'nodeport':
        return '-'
      case 'tailscale':
        return 'Auto-managed'
      case 'cloudflare':
        return 'Origin cert: 10yr'
      default:
        return '-'
    }
  }

  /** Whether URLs should be rendered as clickable links. */
  const isClickable = mode === 'tailscale' || mode === 'cloudflare'
  const certExpiry = getCertExpiry()

  return (
    <div className="bg-white border rounded-lg overflow-hidden">
      <div className="bg-gray-50 border-b px-4 py-2">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
          Ingress Status
        </h2>
      </div>
      <div className="px-4 py-3">
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
                <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide px-3 py-2">
                  Certificate Expiry
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {ingressApps.map((app) => {
                const appId = app.id || app.name
                const url = getUrl(app)
                const ssoActive = isSsoProtected(app)

                return (
                  <tr key={appId} className="hover:bg-gray-50">
                    <td className="px-3 py-2 text-gray-900 font-medium">
                      {app.display_name || app.name || appId}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">
                      {isClickable ? (
                        <a
                          href={url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-600 hover:text-blue-800 underline inline-flex items-center gap-1"
                        >
                          {url}
                          <ExternalLinkIcon />
                        </a>
                      ) : (
                        <span className="text-gray-600">{url}</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <SsoStatusBadge active={ssoActive} />
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-500">
                      {certExpiry}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// External link SVG icon
// ---------------------------------------------------------------------------

function ExternalLinkIcon() {
  return (
    <svg
      className="w-3 h-3 inline-block ml-1"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
    >
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3" />
    </svg>
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
