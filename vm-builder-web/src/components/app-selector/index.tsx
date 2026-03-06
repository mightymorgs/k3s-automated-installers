import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import AppCard from './app-card'
import { groupAppsByCategory } from './group-apps'
import { useResolvedSelection } from './use-resolved-selection'
import { AppConfig, AppSelectorProps, RegistryApp } from './types'

export default function AppSelector({
  selected,
  onChange,
  appConfigs,
  onConfigChange,
  disabledApps = [],
  hypervisorName = '',
  selectedMounts = [],
}: AppSelectorProps) {
  const apps = useQuery({ queryKey: ['apps'], queryFn: () => api.listApps() })

  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [configs, setConfigs] = useState<Record<string, AppConfig>>(appConfigs || {})

  const { autoDeps, userSelected, setUserSelected } = useResolvedSelection({
    selected,
    onChange,
  })

  useEffect(() => {
    onConfigChange?.(configs)
  }, [configs, onConfigChange])

  const toggleApp = (appId: string) => {
    if (userSelected.includes(appId)) {
      setUserSelected(userSelected.filter((app) => app !== appId))
      setExpanded((prev) => {
        const next = new Set(prev)
        next.delete(appId)
        return next
      })
      return
    }
    setUserSelected([...userSelected, appId])
  }

  const toggleExpanded = (appId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(appId)) {
        next.delete(appId)
      } else {
        next.add(appId)
      }
      return next
    })
  }

  const updateConfig = (appId: string, field: string, value: string) => {
    setConfigs((prev) => ({
      ...prev,
      [appId]: { ...prev[appId], [field]: value },
    }))
  }

  if (apps.isLoading) {
    return <p className="text-gray-500">Loading apps...</p>
  }

  if (apps.error) {
    return <p className="text-red-600">Failed to load apps: {(apps.error as Error).message}</p>
  }

  const grouped = groupAppsByCategory((apps.data || []) as RegistryApp[])
  const categories = Object.keys(grouped).sort()

  return (
    <div className="space-y-6">
      {categories.map((category) => (
        <div key={category}>
          <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">
            {category}
          </h3>
          <div className="space-y-2">
            {grouped[category].map((app) => {
              const appId = app.id || app.name || ''
              const isAutoDep = appId in autoDeps
              const isDisabled = disabledApps.includes(appId)
              const isChecked = userSelected.includes(appId) || isAutoDep

              return (
                <AppCard
                  key={appId}
                  app={app}
                  category={category}
                  isAutoDep={isAutoDep}
                  isDisabled={isDisabled}
                  isChecked={isChecked}
                  isExpanded={expanded.has(appId)}
                  autoDepReason={autoDeps[appId]}
                  config={configs[appId]}
                  hypervisorName={hypervisorName}
                  selectedMounts={selectedMounts}
                  onToggleApp={toggleApp}
                  onToggleExpanded={toggleExpanded}
                  onUpdateConfig={updateConfig}
                />
              )
            })}
          </div>
        </div>
      ))}

      {selected.length > 0 && (
        <p className="text-sm text-gray-600">
          {selected.length} app{selected.length !== 1 ? 's' : ''} selected
          {Object.keys(autoDeps).length > 0 &&
            ` (${Object.keys(autoDeps).length} auto-added as dependencies)`}
        </p>
      )}
    </div>
  )
}
