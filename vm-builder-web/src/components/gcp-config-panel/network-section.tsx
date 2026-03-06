import { GcpConfig } from './types'

interface NetworkSectionProps {
  config: GcpConfig
  onSet: <K extends keyof GcpConfig>(field: K, value: GcpConfig[K]) => void
}

export default function NetworkSection({ config, onSet }: NetworkSectionProps) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">
        Network
      </h3>
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Network Name</label>
          <input
            type="text"
            value={config.network_name}
            onChange={(e) => onSet('network_name', e.target.value)}
            placeholder="default"
            className="w-full border rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Subnet Name</label>
          <input
            type="text"
            value={config.subnet_name}
            onChange={(e) => onSet('subnet_name', e.target.value)}
            placeholder="default"
            className="w-full border rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
        </div>
      </div>

      <div className="space-y-3">
        <label className="flex items-center gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={config.enable_external_ip}
            onChange={(e) => onSet('enable_external_ip', e.target.checked)}
            className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          <div>
            <span className="text-sm font-medium text-gray-700">External IP</span>
            <p className="text-xs text-gray-500">
              Assign an ephemeral external IP address to this instance.
            </p>
          </div>
        </label>
        <label className="flex items-center gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={config.enable_static_ip}
            onChange={(e) => onSet('enable_static_ip', e.target.checked)}
            className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          <div>
            <span className="text-sm font-medium text-gray-700">Static IP</span>
            <p className="text-xs text-gray-500">
              Reserve a static external IP. Requires external IP to be enabled.
            </p>
          </div>
        </label>
      </div>
    </div>
  )
}
