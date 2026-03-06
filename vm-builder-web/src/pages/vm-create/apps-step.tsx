import { InventoryMount } from '../../api/client'
import AppSelector from '../../components/AppSelector'
import ResourceBudget from '../../components/ResourceBudget'

interface AppsStepProps {
  selectedApps: string[]
  onSelectedAppsChange: (apps: string[]) => void
  appConfigs: Record<string, Record<string, string | number | boolean>>
  onAppConfigsChange: (
    configs: Record<string, Record<string, string | number | boolean>>
  ) => void
  selectedHypervisor: string
  currentHardware: { vcpu: number; memory_mb: number } | null
  selectedAppData: any[]
  k3sOverhead: { cpu_millicores: number; memory_mb: number }
  defaults: any
  hasResourceDefaults: boolean
  selectedSize: string
  selectedMounts: InventoryMount[]
}

export default function AppsStep({
  selectedApps,
  onSelectedAppsChange,
  appConfigs,
  onAppConfigsChange,
  selectedHypervisor,
  currentHardware,
  selectedAppData,
  k3sOverhead,
  defaults,
  hasResourceDefaults,
  selectedSize,
  selectedMounts,
}: AppsStepProps) {
  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">Applications</h2>
      <p className="text-sm text-gray-600 mb-4">
        Select apps to install. Dependencies will be resolved automatically.
      </p>
      <AppSelector
        selected={selectedApps}
        onChange={onSelectedAppsChange}
        appConfigs={appConfigs}
        onConfigChange={onAppConfigsChange}
        hypervisorName={selectedHypervisor}
        selectedMounts={selectedMounts}
      />
      {currentHardware && selectedApps.length > 0 && hasResourceDefaults && (
        <ResourceBudget
          apps={selectedAppData}
          hardware={currentHardware}
          k3sOverhead={k3sOverhead}
          defaults={defaults}
        />
      )}
      {!selectedSize && selectedApps.length > 0 && (
        <p className="mt-3 text-sm text-yellow-600">
          Select a hardware size in Step 2 to see resource budget.
        </p>
      )}
    </div>
  )
}
