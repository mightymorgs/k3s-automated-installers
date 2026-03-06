interface ResourceUtilizationCardProps {
  inventory: any
  allApps: any[]
  resourceDefaults: any
}

function colorFor(percent: number): string {
  if (percent > 90) {
    return 'text-red-600'
  }
  if (percent > 70) {
    return 'text-yellow-600'
  }
  return 'text-green-600'
}

export default function ResourceUtilizationCard({
  inventory,
  allApps,
  resourceDefaults,
}: ResourceUtilizationCardProps) {
  if (!inventory?.apps?.selected_apps?.length || !inventory.hardware) {
    return null
  }

  const apps = allApps.filter((app: any) =>
    inventory.apps.selected_apps.includes(app.id || app.name)
  )

  if (apps.length === 0) {
    return null
  }

  const k3sOverhead = resourceDefaults.k3s_overhead || {
    cpu_millicores: 500,
    memory_mb: 512,
  }

  const hardware = inventory.hardware
  const availableCpu = (hardware.vcpu || 0) * 1000 - k3sOverhead.cpu_millicores
  const availableMemory = (hardware.memory_mb || 0) - k3sOverhead.memory_mb

  let totalCpu = 0
  let totalMemory = 0
  for (const app of apps) {
    const resources =
      app.resources || resourceDefaults[app.category || ''] || resourceDefaults._default
    totalCpu += resources?.min_cpu_millicores || 250
    totalMemory += resources?.min_memory_mb || 256
  }

  const cpuPercent = availableCpu > 0 ? Math.round((totalCpu / availableCpu) * 100) : 0
  const memoryPercent =
    availableMemory > 0 ? Math.round((totalMemory / availableMemory) * 100) : 0

  return (
    <div className="bg-white border rounded-lg overflow-hidden">
      <div className="bg-gray-50 border-b px-4 py-2">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
          Resource Utilization
        </h2>
      </div>
      <div className="px-4 py-3 space-y-2">
        <div className="flex justify-between text-sm">
          <span className="text-gray-500">CPU</span>
          <span className={colorFor(cpuPercent)}>
            {totalCpu}m / {availableCpu}m ({cpuPercent}%)
          </span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-gray-500">Memory</span>
          <span className={colorFor(memoryPercent)}>
            {totalMemory} MB / {availableMemory} MB ({memoryPercent}%)
          </span>
        </div>
        <p className="text-xs text-gray-400 mt-1">
          Based on minimum requirements for {apps.length} app{apps.length !== 1 ? 's' : ''}.
          {' '}k3s overhead: {k3sOverhead.cpu_millicores}m CPU, {k3sOverhead.memory_mb} MB RAM.
        </p>
      </div>
    </div>
  )
}
