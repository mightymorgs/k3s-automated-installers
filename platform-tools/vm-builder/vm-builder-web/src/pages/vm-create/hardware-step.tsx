import GcpConfigPanel, { GcpConfig } from '../../components/GcpConfigPanel'
import { estimateAppCapacity } from '../../components/ResourceBudget'

interface HardwareStepProps {
  isGcp: boolean
  sizesLoading: boolean
  sizesError: Error | null
  sizesData: Record<string, any> | undefined
  selectedSize: string
  onSelectSize: (size: string) => void
  gcpConfig: GcpConfig
  onGcpConfigChange: (config: GcpConfig) => void
  k3sOverhead: { cpu_millicores: number; memory_mb: number }
  defaults: {
    _default?: {
      min_cpu_millicores: number
      min_memory_mb: number
      recommended_cpu_millicores: number
      recommended_memory_mb: number
    }
  }
  hasResourceDefaults: boolean
}

export default function HardwareStep({
  isGcp,
  sizesLoading,
  sizesError,
  sizesData,
  selectedSize,
  onSelectSize,
  gcpConfig,
  onGcpConfigChange,
  k3sOverhead,
  defaults,
  hasResourceDefaults,
}: HardwareStepProps) {
  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">Hardware Size</h2>
      <p className="text-sm text-gray-600 mb-4">
        {isGcp
          ? 'Configure GCP machine type, disks, region, and network settings.'
          : 'Select a size preset for CPU, memory, and disk allocation.'}
      </p>
      {sizesLoading && <p className="text-gray-500">Loading sizes...</p>}
      {sizesError && <p className="text-red-600">Failed to load sizes: {sizesError.message}</p>}
      {sizesData && isGcp ? (
        <GcpConfigPanel presets={sizesData} config={gcpConfig} onChange={onGcpConfigChange} />
      ) : sizesData ? (
        <div className="grid grid-cols-3 gap-4">
          {Object.entries(sizesData).map(([name, preset]: [string, any]) => (
            <label
              key={name}
              className={`p-4 rounded-lg border cursor-pointer transition-colors ${
                selectedSize === name
                  ? 'bg-blue-50 border-blue-400 ring-2 ring-blue-200'
                  : 'bg-white border-gray-200 hover:border-blue-200'
              }`}
            >
              <input
                type="radio"
                name="size"
                value={name}
                checked={selectedSize === name}
                onChange={() => onSelectSize(name)}
                className="sr-only"
              />
              <div className="font-medium capitalize mb-2">{name}</div>
              <div className="text-sm text-gray-600 space-y-1">
                <div>
                  vCPU: <span className="font-medium">{preset.vcpu}</span>
                </div>
                <div>
                  Memory: <span className="font-medium">{preset.memory_mb} MB</span>
                </div>
                <div>
                  Disk: <span className="font-medium">{preset.disk_gb} GB</span>
                </div>
                {hasResourceDefaults && (
                  <div className="text-xs text-gray-400 mt-1">
                    Supports ~
                    {estimateAppCapacity(
                      { vcpu: preset.vcpu, memory_mb: preset.memory_mb },
                      k3sOverhead,
                      defaults._default || {
                        min_cpu_millicores: 250,
                        min_memory_mb: 256,
                        recommended_cpu_millicores: 500,
                        recommended_memory_mb: 512,
                      }
                    )}{' '}
                    typical apps
                  </div>
                )}
              </div>
            </label>
          ))}
        </div>
      ) : null}
    </div>
  )
}
