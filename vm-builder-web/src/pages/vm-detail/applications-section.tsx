import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, ConfigPreviewResult, ConfigApplyResult } from '../../api/client'
import AppSelector from '../../components/AppSelector'
import ConfigApplyOutput from '../../components/ConfigApplyOutput'
import ConfigDiffModal from '../../components/ConfigDiffModal'
import ConfigEditor from '../../components/ConfigEditor'

interface ApplicationsSectionProps {
  vmName: string
  editMode: boolean
  installedAppsLoading: boolean
  installedAppsData: any[] | undefined
  currentApps: string[]
  hypervisorName?: string
  onAppChange: (apps: string[]) => void
  onOpenInstallPanel: () => void
  onUninstall: (appId: string) => void
  onReinstall: (appId: string) => void
  onConfigure: (appId: string) => void
}

type AppStatus = 'installed' | 'ready' | 'install_failed' | 'config_failed' | string

function getActions(status: AppStatus) {
  switch (status) {
    case 'installed':
      return ['configure', 'reinstall', 'remove'] as const
    case 'ready':
      return ['edit-config', 'reinstall', 'remove'] as const
    case 'install_failed':
      return ['reinstall', 'remove'] as const
    case 'config_failed':
      return ['configure', 'remove'] as const
    default:
      return ['remove'] as const
  }
}

const ACTION_LABELS: Record<string, { label: string; className: string }> = {
  configure: {
    label: 'Configure',
    className: 'text-yellow-600 hover:text-yellow-800',
  },
  'edit-config': {
    label: 'Edit Config',
    className: 'text-blue-600 hover:text-blue-800',
  },
  reinstall: {
    label: 'Reinstall',
    className: 'text-blue-600 hover:text-blue-800',
  },
  remove: {
    label: 'Remove',
    className: 'text-red-500 hover:text-red-700',
  },
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    pending: 'bg-gray-100 text-gray-700',
    installing: 'bg-blue-100 text-blue-700',
    installed: 'bg-blue-100 text-blue-700',
    configuring: 'bg-yellow-100 text-yellow-700',
    ready: 'bg-green-100 text-green-700',
    install_failed: 'bg-red-100 text-red-700',
    config_failed: 'bg-red-100 text-red-700',
  }
  return (
    <span
      className={`text-xs px-2 py-0.5 rounded-full font-medium ${styles[status] || 'bg-gray-100 text-gray-700'}`}
    >
      {status.replace('_', ' ')}
    </span>
  )
}

export default function ApplicationsSection({
  vmName,
  editMode,
  installedAppsLoading,
  installedAppsData,
  currentApps,
  hypervisorName,
  onAppChange,
  onOpenInstallPanel,
  onUninstall,
  onReinstall,
  onConfigure,
}: ApplicationsSectionProps) {
  const [expandedApp, setExpandedApp] = useState<string | null>(null)
  const [previewData, setPreviewData] = useState<ConfigPreviewResult | null>(null)
  const [applyResult, setApplyResult] = useState<ConfigApplyResult | null>(null)
  const queryClient = useQueryClient()

  const previewMutation = useMutation({
    mutationFn: (appId: string) => api.previewConfigChanges(vmName, appId),
    onSuccess: (data) => setPreviewData(data),
  })

  const applyMutation = useMutation({
    mutationFn: (appId: string) => api.applyConfigLive(vmName, appId),
    onSuccess: (data) => {
      setPreviewData(null)
      setApplyResult(data)
      queryClient.invalidateQueries({ queryKey: ['app-config', vmName] })
      queryClient.invalidateQueries({ queryKey: ['installed-apps', vmName] })
    },
  })

  if (editMode) {
    return (
      <div className="bg-white border rounded-lg overflow-hidden">
        <div className="bg-gray-50 border-b px-4 py-2">
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
            Applications
          </h2>
        </div>
        <div className="p-4">
          <AppSelector selected={currentApps} onChange={onAppChange} />
        </div>
      </div>
    )
  }

  const handleAction = (action: string, app: any) => {
    const appId = app.app_id
    const displayName = app.display_name || appId

    switch (action) {
      case 'configure':
      case 'edit-config':
        setExpandedApp(expandedApp === appId ? null : appId)
        break
      case 'reinstall':
        if (confirm(`Reinstall ${displayName}? This will re-run the install playbook.`)) {
          onReinstall(appId)
        }
        break
      case 'remove':
        if (confirm(`Remove ${displayName} from inventory? K8s resources will NOT be deleted.`)) {
          onUninstall(appId)
        }
        break
    }
  }

  return (
    <div className="bg-white border rounded-lg overflow-hidden">
      <div className="bg-gray-50 border-b px-4 py-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Applications</h2>
        <button
          onClick={onOpenInstallPanel}
          className="text-xs text-blue-600 hover:text-blue-800 font-medium px-2 py-1 rounded hover:bg-blue-50"
        >
          + Add Application
        </button>
      </div>
      <div className="px-4 py-3">
        {installedAppsLoading && <p className="text-sm text-gray-500">Loading apps...</p>}
        {installedAppsData && installedAppsData.length === 0 && (
          <p className="text-sm text-gray-400 italic">No applications installed</p>
        )}
        {installedAppsData && installedAppsData.length > 0 && (
          <div className="space-y-1">
            {installedAppsData.map((app: any) => {
              const actions = getActions(app.status)
              const isExpanded = expandedApp === app.app_id

              return (
                <div key={app.app_id}>
                  <div className="flex items-center justify-between text-sm py-1.5">
                    <div>
                      <span className="font-medium">{app.display_name || app.app_id}</span>
                      {app.category && (
                        <span className="ml-2 text-xs bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded">
                          {app.category}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <StatusBadge status={app.status} />
                      {actions.map((action) => {
                        const config = ACTION_LABELS[action]
                        if (!config) return null
                        return (
                          <button
                            key={action}
                            onClick={() => handleAction(action, app)}
                            className={`text-xs ${config.className}`}
                          >
                            {config.label}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                  {isExpanded && (
                    <div className="ml-4 mb-3 pl-3 border-l-2 border-blue-200 py-2">
                      <ConfigEditor
                        vmName={vmName}
                        appId={app.app_id}
                        displayName={app.display_name || app.app_id}
                        hypervisorName={hypervisorName}
                      />
                      <div className="mt-3 flex items-center gap-2">
                        <button
                          onClick={() => previewMutation.mutate(app.app_id)}
                          disabled={previewMutation.isPending}
                          className="px-3 py-1.5 text-xs text-white bg-blue-600 rounded hover:bg-blue-700 disabled:opacity-50"
                        >
                          {previewMutation.isPending ? 'Loading...' : 'Preview Changes'}
                        </button>
                        {(app.status === 'installed' || app.status === 'config_failed') && (
                          <button
                            onClick={() => onConfigure(app.app_id)}
                            className="px-3 py-1.5 text-xs text-white bg-yellow-600 rounded hover:bg-yellow-700"
                          >
                            Apply via Workflow
                          </button>
                        )}
                      </div>
                      {previewMutation.error && (
                        <p className="mt-2 text-xs text-red-500">
                          Preview failed: {(previewMutation.error as Error).message}
                        </p>
                      )}
                      {applyResult && applyResult.app_id === app.app_id && (
                        <ConfigApplyOutput
                          result={applyResult}
                          onClose={() => setApplyResult(null)}
                        />
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {previewData && (
        <ConfigDiffModal
          preview={previewData}
          onApply={() => applyMutation.mutate(previewData.app_id)}
          onClose={() => setPreviewData(null)}
          isApplying={applyMutation.isPending}
        />
      )}
    </div>
  )
}
