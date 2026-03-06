import { InventoryMount } from '../../api/client'
import ConfigField from './config-field'
import { AppConfig, RegistryApp } from './types'

interface AppCardProps {
  app: RegistryApp
  category: string
  isAutoDep: boolean
  isDisabled: boolean
  isChecked: boolean
  isExpanded: boolean
  autoDepReason?: string
  config: AppConfig | undefined
  hypervisorName?: string
  selectedMounts?: InventoryMount[]
  onToggleApp: (appId: string) => void
  onToggleExpanded: (appId: string) => void
  onUpdateConfig: (appId: string, field: string, value: string) => void
}

export default function AppCard({
  app,
  category,
  isAutoDep,
  isDisabled,
  isChecked,
  isExpanded,
  autoDepReason,
  config,
  hypervisorName,
  selectedMounts,
  onToggleApp,
  onToggleExpanded,
  onUpdateConfig,
}: AppCardProps) {
  const appId = app.id || app.name || ''
  const variables = app.variables || {}
  const hasVariables = Object.keys(variables).length > 0

  return (
    <div
      className={`rounded-md border transition-colors ${
        isDisabled
          ? 'bg-gray-100 border-gray-200 opacity-60'
          : isChecked
            ? isAutoDep
              ? 'bg-gray-50 border-gray-300'
              : 'bg-blue-50 border-blue-300'
            : 'bg-white border-gray-200 hover:border-blue-200'
      }`}
    >
      <div className="flex items-start gap-3 p-3">
        <input
          type="checkbox"
          checked={isChecked || isDisabled}
          disabled={isAutoDep || isDisabled}
          onChange={() => onToggleApp(appId)}
          className="mt-0.5"
        />
        <div className={`flex-1 ${isAutoDep ? 'opacity-60' : ''}`}>
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">
              {app.display_name || app.name || appId}
            </span>
            <span className="text-xs bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded">
              {category}
            </span>
            {isChecked && hasVariables && (
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault()
                  onToggleExpanded(appId)
                }}
                className="text-xs text-blue-600 hover:text-blue-800 ml-auto flex items-center gap-1"
              >
                <svg
                  className={`w-3 h-3 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M19 9l-7 7-7-7"
                  />
                </svg>
                Configure
              </button>
            )}
          </div>
          {app.description && <p className="text-xs text-gray-500 mt-1">{app.description}</p>}
          {isAutoDep && autoDepReason && (
            <p className="text-xs text-gray-400 mt-1 italic">Required by {autoDepReason}</p>
          )}
          {isDisabled && <p className="text-xs text-gray-400 mt-1 italic">Already installed</p>}
        </div>
      </div>

      {isChecked && isExpanded && hasVariables && (
        <div className="border-t border-gray-200 bg-white px-4 py-3 space-y-3">
          <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Configuration</p>
          {Object.entries(variables).map(([fieldName, fieldDef]) => (
            <ConfigField
              key={fieldName}
              appId={appId}
              fieldName={fieldName}
              fieldDef={fieldDef}
              value={config?.[fieldName]?.toString() || ''}
              onChange={onUpdateConfig}
              hypervisorName={hypervisorName}
              selectedMounts={selectedMounts}
            />
          ))}
        </div>
      )}
    </div>
  )
}
