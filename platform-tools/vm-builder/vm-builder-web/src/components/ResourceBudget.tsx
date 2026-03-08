import { useMemo } from 'react'

interface AppResource {
  min_cpu_millicores: number
  min_memory_mb: number
  recommended_cpu_millicores: number
  recommended_memory_mb: number
}

interface AppData {
  id: string
  display_name?: string
  name?: string
  category?: string
  resources?: AppResource
}

interface Hardware {
  vcpu: number
  memory_mb: number
}

interface K3sOverhead {
  cpu_millicores: number
  memory_mb: number
}

interface ResourceDefaultsMap {
  [category: string]: AppResource
  _default: AppResource
}

interface BudgetResult {
  totalMinCpu: number
  totalMinMem: number
  totalRecCpu: number
  totalRecMem: number
  availableCpu: number
  availableMem: number
  cpuPct: number
  memPct: number
  perApp: {
    id: string
    name: string
    cpu: number
    mem: number
  }[]
}

function computeBudget(
  apps: AppData[],
  hardware: Hardware,
  k3sOverhead: K3sOverhead,
  defaults: ResourceDefaultsMap,
): BudgetResult {
  const availableCpu = hardware.vcpu * 1000 - k3sOverhead.cpu_millicores
  const availableMem = hardware.memory_mb - k3sOverhead.memory_mb

  let totalMinCpu = 0
  let totalMinMem = 0
  let totalRecCpu = 0
  let totalRecMem = 0
  const perApp: BudgetResult['perApp'] = []

  for (const app of apps) {
    const res =
      app.resources ||
      defaults[app.category || ''] ||
      defaults._default
    totalMinCpu += res.min_cpu_millicores
    totalMinMem += res.min_memory_mb
    totalRecCpu += res.recommended_cpu_millicores
    totalRecMem += res.recommended_memory_mb
    perApp.push({
      id: app.id,
      name: app.display_name || app.name || app.id,
      cpu: res.min_cpu_millicores,
      mem: res.min_memory_mb,
    })
  }

  const cpuPct = availableCpu > 0 ? (totalMinCpu / availableCpu) * 100 : 0
  const memPct = availableMem > 0 ? (totalMinMem / availableMem) * 100 : 0

  return {
    totalMinCpu,
    totalMinMem,
    totalRecCpu,
    totalRecMem,
    availableCpu,
    availableMem,
    cpuPct,
    memPct,
    perApp,
  }
}

function barColor(pct: number): string {
  if (pct > 90) return 'bg-red-500'
  if (pct > 70) return 'bg-yellow-500'
  return 'bg-green-500'
}

function barLabel(pct: number): { text: string; color: string } {
  if (pct > 90) return { text: 'Exceeds recommended capacity', color: 'text-red-700' }
  if (pct > 70) return { text: 'Tight fit -- consider upgrading', color: 'text-yellow-700' }
  return { text: 'Plenty of headroom', color: 'text-green-700' }
}

/**
 * Resource budget bars for CPU and memory.
 *
 * Tallies min resource requirements across selected apps, subtracts
 * k3s system overhead from the hardware, and renders horizontal bars
 * with green (<70%), yellow (70-90%), red (>90%) coloring.
 *
 * Threshold legend:
 *   Green  (<70%): "Plenty of headroom"
 *   Yellow (70-90%): "Tight fit -- consider upgrading"
 *   Red    (>90%): "Exceeds recommended capacity"
 */
export default function ResourceBudget({
  apps,
  hardware,
  k3sOverhead,
  defaults,
}: {
  apps: AppData[]
  hardware: Hardware | null
  k3sOverhead: K3sOverhead
  defaults: ResourceDefaultsMap
}) {
  const budget = useMemo(() => {
    if (!hardware || apps.length === 0) return null
    return computeBudget(apps, hardware, k3sOverhead, defaults)
  }, [apps, hardware, k3sOverhead, defaults])

  if (!budget || !hardware) {
    return null
  }

  const cpuLabel = barLabel(budget.cpuPct)
  const memLabel = barLabel(budget.memPct)

  return (
    <div className="mt-4 p-4 bg-gray-50 rounded-lg border space-y-4">
      <h4 className="text-sm font-semibold text-gray-700">Resource Budget</h4>

      {/* CPU Bar */}
      <div>
        <div className="flex justify-between text-xs text-gray-600 mb-1">
          <span>CPU: {budget.totalMinCpu}m / {budget.availableCpu}m available</span>
          <span className={cpuLabel.color}>{Math.round(budget.cpuPct)}% -- {cpuLabel.text}</span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-3">
          <div
            className={`h-3 rounded-full transition-all ${barColor(budget.cpuPct)}`}
            style={{ width: `${Math.min(budget.cpuPct, 100)}%` }}
          />
        </div>
      </div>

      {/* Memory Bar */}
      <div>
        <div className="flex justify-between text-xs text-gray-600 mb-1">
          <span>Memory: {budget.totalMinMem} MB / {budget.availableMem} MB available</span>
          <span className={memLabel.color}>{Math.round(budget.memPct)}% -- {memLabel.text}</span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-3">
          <div
            className={`h-3 rounded-full transition-all ${barColor(budget.memPct)}`}
            style={{ width: `${Math.min(budget.memPct, 100)}%` }}
          />
        </div>
      </div>

      {/* Per-app breakdown tooltip */}
      {budget.perApp.length > 0 && (
        <details className="text-xs text-gray-500">
          <summary className="cursor-pointer hover:text-gray-700">
            Per-app breakdown ({budget.perApp.length} apps)
          </summary>
          <div className="mt-2 space-y-1 ml-2">
            <div className="text-xs text-gray-400 italic mb-1">
              k3s overhead: {k3sOverhead.cpu_millicores}m CPU, {k3sOverhead.memory_mb} MB RAM (reserved)
            </div>
            {budget.perApp.map((a) => (
              <div key={a.id} className="flex justify-between">
                <span>{a.name}</span>
                <span className="text-gray-400">{a.cpu}m CPU, {a.mem} MB RAM</span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}

/**
 * Exported for use in Step 2 (Hardware) to show app capacity hints.
 *
 * Estimates how many "typical" apps (using _default resources) a given
 * hardware preset can support after k3s overhead.
 */
export function estimateAppCapacity(
  hardware: Hardware,
  k3sOverhead: K3sOverhead,
  defaultResources: AppResource,
): number {
  const availableCpu = hardware.vcpu * 1000 - k3sOverhead.cpu_millicores
  const availableMem = hardware.memory_mb - k3sOverhead.memory_mb
  const cpuApps = Math.floor(availableCpu / defaultResources.min_cpu_millicores)
  const memApps = Math.floor(availableMem / defaultResources.min_memory_mb)
  return Math.min(cpuApps, memApps)
}
