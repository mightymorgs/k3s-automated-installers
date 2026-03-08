import { DISK_TYPE_OPTIONS } from './constants'
import { GcpConfig } from './types'

interface DiskConfigSectionProps {
  config: GcpConfig
  onSet: <K extends keyof GcpConfig>(field: K, value: GcpConfig[K]) => void
}

export default function DiskConfigSection({ config, onSet }: DiskConfigSectionProps) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">
        Disk Configuration
      </h3>

      <div className="mb-4">
        <p className="text-sm font-medium text-gray-700 mb-2">Boot Disk</p>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Size (GB)</label>
            <input
              type="number"
              min={10}
              max={2048}
              value={config.boot_disk_size_gb}
              onChange={(e) => onSet('boot_disk_size_gb', parseInt(e.target.value, 10) || 0)}
              className="w-full border rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Disk Type</label>
            <select
              value={config.boot_disk_type}
              onChange={(e) => onSet('boot_disk_type', e.target.value)}
              className="w-full border rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            >
              {DISK_TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div>
        <p className="text-sm font-medium text-gray-700 mb-2">
          Data Disk <span className="text-xs text-gray-400 font-normal">(set size to 0 for none)</span>
        </p>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Size (GB)</label>
            <input
              type="number"
              min={0}
              max={2048}
              value={config.data_disk_size_gb}
              onChange={(e) => onSet('data_disk_size_gb', parseInt(e.target.value, 10) || 0)}
              className="w-full border rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Disk Type</label>
            <select
              value={config.data_disk_type}
              onChange={(e) => onSet('data_disk_type', e.target.value)}
              className="w-full border rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            >
              {DISK_TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>
    </div>
  )
}
