import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, AppConfigField } from '../api/client'
import ConfigField from './app-selector/config-field'

interface ConfigEditorProps {
  vmName: string
  appId: string
  displayName?: string
  hypervisorName?: string
}

export default function ConfigEditor({ vmName, appId, hypervisorName }: ConfigEditorProps) {
  const queryClient = useQueryClient()
  const [showAll, setShowAll] = useState(false)

  const configQuery = useQuery({
    queryKey: ['app-config', vmName, appId],
    queryFn: () => api.getAppConfig(vmName, appId),
  })

  const updateMutation = useMutation({
    mutationFn: ({ field, value }: { field: string; value: any }) =>
      api.updateAppConfig(vmName, appId, field, value),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['app-config', vmName, appId] })
      queryClient.invalidateQueries({ queryKey: ['installed-apps', vmName] })
    },
  })

  const resetMutation = useMutation({
    mutationFn: (field: string) => api.resetAppConfig(vmName, appId, field),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['app-config', vmName, appId] })
      queryClient.invalidateQueries({ queryKey: ['installed-apps', vmName] })
    },
  })

  if (configQuery.isLoading) {
    return <p className="text-xs text-gray-400">Loading config...</p>
  }

  if (configQuery.error) {
    return (
      <p className="text-xs text-red-500">
        Failed to load config: {(configQuery.error as Error).message}
      </p>
    )
  }

  if (!configQuery.data) return null

  const fields = configQuery.data.fields ?? {}
  const allEntries = Object.entries(fields)
  const overrideEntries = allEntries.filter(([, f]) => f.is_override)
  const displayEntries = showAll ? allEntries : overrideEntries

  if (allEntries.length === 0) {
    return <p className="text-xs text-gray-400 italic">No configurable fields</p>
  }

  return (
    <div className="space-y-3">
      {overrideEntries.length === 0 && !showAll && (
        <p className="text-xs text-gray-400 italic">No overrides set (using defaults)</p>
      )}

      {displayEntries.map(([fieldName, fieldInfo]: [string, AppConfigField]) => (
        <div key={fieldName} className="flex items-start gap-2">
          <div className="flex-1">
            <ConfigField
              appId={appId}
              fieldName={fieldName}
              fieldDef={fieldInfo.field_def}
              value={fieldInfo.value?.toString() ?? ''}
              onChange={(_appId, field, value) => {
                updateMutation.mutate({ field, value })
              }}
              hypervisorName={hypervisorName}
            />
            {fieldInfo.is_override && fieldInfo.value !== fieldInfo.default && (
              <p className="text-xs text-gray-400 mt-0.5">
                Default: {fieldInfo.default?.toString() ?? 'none'}
              </p>
            )}
          </div>
          {fieldInfo.is_override && (
            <button
              onClick={() => resetMutation.mutate(fieldName)}
              disabled={resetMutation.isPending}
              className="mt-5 text-xs text-gray-400 hover:text-red-500 shrink-0"
              title="Reset to default"
            >
              Reset
            </button>
          )}
        </div>
      ))}

      {allEntries.length > overrideEntries.length && (
        <button
          onClick={() => setShowAll(!showAll)}
          className="text-xs text-blue-600 hover:text-blue-800"
        >
          {showAll
            ? `Show overrides only (${overrideEntries.length})`
            : `Show all fields (${allEntries.length})`}
        </button>
      )}

      {updateMutation.isSuccess && updateMutation.data?.workflow_triggered && (
        <p className="text-xs text-green-600">
          Config saved. Live update workflow triggered — rollout in progress.
        </p>
      )}

      {updateMutation.isSuccess && updateMutation.data?.workflow_triggered === false && (
        <p className="text-xs text-yellow-600">
          Config saved to BWS. Workflow trigger failed — apply manually via Preview Changes.
        </p>
      )}

      {(updateMutation.error || resetMutation.error) && (
        <p className="text-xs text-red-500">
          {((updateMutation.error || resetMutation.error) as Error).message}
        </p>
      )}
    </div>
  )
}
