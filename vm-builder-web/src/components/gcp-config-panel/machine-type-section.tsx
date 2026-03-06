interface MachineTypeSectionProps {
  presets: Record<string, any>
  selectedMachineType: string
  onSelectMachineType: (machineType: string) => void
}

export default function MachineTypeSection({
  presets,
  selectedMachineType,
  onSelectMachineType,
}: MachineTypeSectionProps) {
  const presetEntries = Object.entries(presets)

  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">
        Machine Type
      </h3>
      <p className="text-sm text-gray-600 mb-4">
        Select a GCP machine type. This determines vCPU and memory allocation.
      </p>
      {presetEntries.length === 0 ? (
        <p className="text-gray-500 text-sm">No machine type presets available.</p>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          {presetEntries.map(([name, preset]: [string, any]) => {
            const isSelected = selectedMachineType === name
            const isRecommended = preset.description?.toLowerCase().includes('recommended')

            return (
              <label
                key={name}
                className={`p-4 rounded-lg border cursor-pointer transition-colors relative ${
                  isSelected
                    ? 'bg-blue-50 border-blue-400 ring-2 ring-blue-200'
                    : 'bg-white border-gray-200 hover:border-blue-200'
                }`}
              >
                <input
                  type="radio"
                  name="machine_type"
                  value={name}
                  checked={isSelected}
                  onChange={() => onSelectMachineType(name)}
                  className="sr-only"
                />
                {isRecommended && (
                  <span className="absolute top-2 right-2 text-xs bg-green-100 text-green-700 px-1.5 py-0.5 rounded font-medium">
                    Recommended
                  </span>
                )}
                <div className="font-medium text-sm mb-2">{name}</div>
                <div className="text-sm text-gray-600 space-y-1">
                  {preset.description && (
                    <div className="text-xs text-gray-500">
                      {preset.description.replace(/\s*[-—]\s*Recommended\s*/i, '')}
                    </div>
                  )}
                  {preset.vcpu && (
                    <div>
                      vCPU: <span className="font-medium">{preset.vcpu}</span>
                    </div>
                  )}
                  {preset.memory_gb !== undefined && (
                    <div>
                      Memory: <span className="font-medium">{preset.memory_gb} GB</span>
                    </div>
                  )}
                  {preset.cost_estimate && (
                    <div className="text-xs text-gray-400 mt-1">{preset.cost_estimate}</div>
                  )}
                </div>
              </label>
            )
          })}
        </div>
      )}
    </div>
  )
}
