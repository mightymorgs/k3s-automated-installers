import { DEFAULT_GCP_CONFIG } from './constants'
import DiskConfigSection from './disk-config-section'
import MachineTypeSection from './machine-type-section'
import NetworkSection from './network-section'
import RegionZoneSection from './region-zone-section'
import { GcpConfig, GcpConfigPanelProps } from './types'
import { zonesForRegion } from './utils'

export { DEFAULT_GCP_CONFIG }
export type { GcpConfig }

export default function GcpConfigPanel({
  presets,
  config,
  onChange,
}: GcpConfigPanelProps) {
  const set = <K extends keyof GcpConfig>(field: K, value: GcpConfig[K]) => {
    onChange({ ...config, [field]: value })
  }

  const selectMachineType = (machineType: string) => {
    const preset = presets[machineType]
    const updates: Partial<GcpConfig> = { machine_type: machineType }

    if (preset?.boot_disk_size_gb) {
      updates.boot_disk_size_gb = preset.boot_disk_size_gb
    }
    if (preset?.boot_disk_type) {
      updates.boot_disk_type = preset.boot_disk_type
    }

    onChange({ ...config, ...updates })
  }

  const changeRegion = (region: string) => {
    const zones = zonesForRegion(region)
    onChange({ ...config, region, zone: zones[0] })
  }

  const availableZones = zonesForRegion(config.region)

  return (
    <div className="space-y-8">
      <MachineTypeSection
        presets={presets}
        selectedMachineType={config.machine_type}
        onSelectMachineType={selectMachineType}
      />
      <DiskConfigSection config={config} onSet={set} />
      <RegionZoneSection
        region={config.region}
        zone={config.zone}
        availableZones={availableZones}
        onChangeRegion={changeRegion}
        onChangeZone={(zone) => set('zone', zone)}
      />
      <NetworkSection config={config} onSet={set} />
    </div>
  )
}
