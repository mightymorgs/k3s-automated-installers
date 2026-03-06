import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import SsoToggleRow from './sso-toggle-row'
import { RegistryApp, SsoToggleListProps } from './types'

export default function SsoToggleList({
  selectedApps,
  ssoOverrides,
  onOverridesChange,
  ingressMode,
}: SsoToggleListProps) {
  const apps = useQuery({
    queryKey: ['apps'],
    queryFn: () => api.listApps(),
  })

  const [expandedApps, setExpandedApps] = useState<Set<string>>(new Set())

  if (ingressMode === 'nodeport') {
    return (
      <div>
        <h3 className="text-sm font-semibold text-gray-700 mb-3">SSO Protection</h3>
        <div className="bg-gray-50 border border-gray-200 rounded-md p-4">
          <p className="text-sm text-gray-600">
            SSO protection is not available in NodePort mode. Select Tailscale or
            Cloudflare ingress to enable SSO.
          </p>
        </div>
      </div>
    )
  }

  if (apps.isLoading) {
    return <p className="text-gray-500 text-sm">Loading SSO settings...</p>
  }

  if (apps.error) {
    return (
      <p className="text-red-600 text-sm">Failed to load app data: {(apps.error as Error).message}</p>
    )
  }

  const ssoApps: RegistryApp[] = (apps.data || []).filter(
    (app: RegistryApp) =>
      selectedApps.includes(app.id || app.name) && app.sso?.enabled
  )

  if (ssoApps.length === 0) {
    return (
      <div>
        <h3 className="text-sm font-semibold text-gray-700 mb-3">SSO Protection</h3>
        <p className="text-sm text-gray-500">No selected apps support SSO protection.</p>
      </div>
    )
  }

  const isSsoActive = (appId: string): boolean => {
    if (appId in ssoOverrides) {
      return ssoOverrides[appId]
    }
    return true
  }

  const protectedApps = ssoApps.filter((app) => isSsoActive(app.id || app.name))
  const directApps = ssoApps.filter((app) => !isSsoActive(app.id || app.name))

  const handleToggle = (appId: string) => {
    const currentlyActive = isSsoActive(appId)
    const next = { ...ssoOverrides }
    if (currentlyActive) {
      next[appId] = false
    } else {
      delete next[appId]
    }
    onOverridesChange(next)
  }

  const toggleExpanded = (appId: string) => {
    setExpandedApps((prev) => {
      const next = new Set(prev)
      if (next.has(appId)) {
        next.delete(appId)
      } else {
        next.add(appId)
      }
      return next
    })
  }

  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-700 mb-3">SSO Protection</h3>
      <div className="space-y-4">
        {protectedApps.length > 0 && (
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
              SSO Protected
            </p>
            <div className="space-y-1">
              {protectedApps.map((app) => (
                <SsoToggleRow
                  key={app.id || app.name}
                  app={app}
                  active={true}
                  expanded={expandedApps.has(app.id || app.name)}
                  onToggle={handleToggle}
                  onToggleExpanded={toggleExpanded}
                />
              ))}
            </div>
          </div>
        )}

        {directApps.length > 0 && (
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
              Direct Access
            </p>
            <div className="space-y-1">
              {directApps.map((app) => (
                <SsoToggleRow
                  key={app.id || app.name}
                  app={app}
                  active={false}
                  expanded={expandedApps.has(app.id || app.name)}
                  onToggle={handleToggle}
                  onToggleExpanded={toggleExpanded}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
