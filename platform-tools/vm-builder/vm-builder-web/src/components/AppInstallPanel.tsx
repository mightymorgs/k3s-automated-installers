import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import AppSelector from './AppSelector'

interface AppConfig {
  [fieldName: string]: string | number | boolean
}

/**
 * Slide-over panel for installing apps on a running VM.
 *
 * Flow:
 * 1. User selects apps via AppSelector (already-installed apps are grayed out).
 * 2. User configures per-app variables.
 * 3. User clicks "Install" -> triggers POST /api/v1/vms/{vmName}/apps.
 * 4. Panel switches to progress view showing per-app status.
 * 5. User closes panel after completion.
 */
export default function AppInstallPanel({
  vmName,
  installedApps,
  isOpen,
  onClose,
}: {
  vmName: string
  installedApps: string[]
  isOpen: boolean
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [selectedApps, setSelectedApps] = useState<string[]>([])
  const [appConfigs, setAppConfigs] = useState<Record<string, AppConfig>>({})

  const installMutation = useMutation({
    mutationFn: () =>
      api.installApps(vmName, {
        apps: selectedApps.filter((a) => !installedApps.includes(a)),
        app_configs: appConfigs,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vm', vmName] })
      queryClient.invalidateQueries({ queryKey: ['installed-apps', vmName] })
    },
  })

  const handleInstall = () => {
    const newApps = selectedApps.filter((a) => !installedApps.includes(a))
    if (newApps.length === 0) return
    installMutation.mutate()
  }

  const handleClose = () => {
    setSelectedApps([])
    setAppConfigs({})
    installMutation.reset()
    onClose()
  }

  const newAppsCount = selectedApps.filter(
    (a) => !installedApps.includes(a)
  ).length

  if (!isOpen) return null

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/30 z-40 transition-opacity"
        onClick={handleClose}
      />

      {/* Panel */}
      <div className="fixed inset-y-0 right-0 w-full max-w-xl bg-white shadow-xl z-50 flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h2 className="text-lg font-semibold">Add Application</h2>
          <button
            onClick={handleClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
          >
            &times;
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {!installMutation.data && !installMutation.isPending ? (
            /* Selection view */
            <div>
              <p className="text-sm text-gray-600 mb-4">
                Select applications to install on{' '}
                <span className="font-mono text-xs bg-gray-100 px-1 py-0.5 rounded">
                  {vmName}
                </span>
                . Already installed apps are grayed out.
              </p>
              <AppSelector
                selected={selectedApps}
                onChange={setSelectedApps}
                appConfigs={appConfigs}
                onConfigChange={setAppConfigs}
                disabledApps={installedApps}
              />
            </div>
          ) : (
            /* Progress view */
            <div className="space-y-4">
              {installMutation.isPending && (
                <div className="flex items-center gap-2 text-blue-600">
                  <svg
                    className="animate-spin h-4 w-4"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                  >
                    <circle
                      cx="12"
                      cy="12"
                      r="10"
                      strokeWidth="4"
                      className="opacity-25"
                    />
                    <path
                      d="M4 12a8 8 0 018-8"
                      strokeWidth="4"
                      className="opacity-75"
                    />
                  </svg>
                  <span className="text-sm">Installing applications...</span>
                </div>
              )}

              {installMutation.data && (
                <>
                  <p className="text-sm font-medium text-gray-700">
                    Installation {installMutation.data.statuses.every(
                      (s: any) => s.status === 'ready'
                    )
                      ? 'complete'
                      : 'finished with errors'}
                  </p>
                  {installMutation.data.statuses.map((s: any) => (
                    <div
                      key={s.app_id}
                      className="flex items-center justify-between border rounded-md px-4 py-3"
                    >
                      <span className="text-sm font-medium">{s.app_id}</span>
                      <div className="flex items-center gap-2">
                        <StatusBadge status={s.status} />
                        {s.workflow_run_url && (
                          <a
                            href={s.workflow_run_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs text-blue-600 hover:underline"
                          >
                            View run
                          </a>
                        )}
                      </div>
                    </div>
                  ))}
                  {installMutation.data.statuses.some(
                    (s: any) => s.error
                  ) && (
                    <div className="bg-red-50 border border-red-200 rounded-md p-3">
                      <p className="text-xs font-medium text-red-700 mb-1">
                        Errors:
                      </p>
                      {installMutation.data.statuses
                        .filter((s: any) => s.error)
                        .map((s: any) => (
                          <p key={s.app_id} className="text-xs text-red-600">
                            {s.app_id}: {s.error}
                          </p>
                        ))}
                    </div>
                  )}
                </>
              )}

              {installMutation.error && (
                <div className="bg-red-50 border border-red-200 rounded-md p-4">
                  <p className="text-sm text-red-700">
                    Failed: {(installMutation.error as Error).message}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t px-6 py-4 flex justify-end gap-3">
          <button
            onClick={handleClose}
            className="px-4 py-2 text-sm text-gray-700 border rounded-md hover:bg-gray-50"
          >
            {installMutation.data ? 'Close' : 'Cancel'}
          </button>
          {!installMutation.data && !installMutation.isPending && (
            <button
              onClick={handleInstall}
              disabled={newAppsCount === 0}
              className="px-4 py-2 text-sm text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Install {newAppsCount > 0 ? `(${newAppsCount} app${newAppsCount !== 1 ? 's' : ''})` : ''}
            </button>
          )}
        </div>
      </div>
    </>
  )
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
