import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import SectionCard from '../components/SectionCard'

/** Ordered sections to display from the hypervisor inventory. */
const SECTION_ORDER = [
  'identity',
  'hardware',
  'network',
  'ssh',
  'github',
  'bootstrap',
  '_state',
]

/** Human-readable labels for sections. */
const SECTION_LABELS: Record<string, string> = {
  identity: 'Identity',
  hardware: 'Hardware',
  network: 'Network',
  ssh: 'SSH',
  github: 'GitHub',
  bootstrap: 'Bootstrap',
  _state: 'State',
}

export default function HypervisorDetail() {
  const { name } = useParams<{ name: string }>()

  const hv = useQuery({
    queryKey: ['hypervisor', name],
    queryFn: () => api.getHypervisor(name!),
    enabled: !!name,
  })

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <Link
          to="/hypervisors"
          className="text-sm text-blue-600 hover:text-blue-800"
        >
          &larr; Hypervisors
        </Link>
        <h1 className="text-2xl font-bold">{name}</h1>
      </div>

      {hv.isLoading && (
        <p className="text-gray-500">Loading hypervisor details...</p>
      )}

      {hv.error && (
        <div className="bg-red-50 border border-red-200 rounded-md p-4">
          <p className="text-sm text-red-700">
            Failed to load hypervisor: {(hv.error as Error).message}
          </p>
        </div>
      )}

      {hv.data && (
        <div className="space-y-4">
          {/* Schema version at top if present */}
          {hv.data.schema_version && (
            <p className="text-xs text-gray-400">
              Schema: {hv.data.schema_version}
            </p>
          )}

          {/* Ordered sections */}
          {SECTION_ORDER.map((section) => {
            const data = hv.data[section]
            if (!data || typeof data !== 'object') return null
            return (
              <SectionCard
                key={section}
                title={SECTION_LABELS[section] || section}
                data={data as Record<string, unknown>}
              />
            )
          })}

          {/* Any remaining keys not in SECTION_ORDER */}
          {Object.keys(hv.data)
            .filter(
              (k) => !SECTION_ORDER.includes(k) && k !== 'schema_version'
            )
            .map((section) => {
              const data = hv.data[section]
              if (!data || typeof data !== 'object') return null
              return (
                <SectionCard
                  key={section}
                  title={section}
                  data={data as Record<string, unknown>}
                />
              )
            })}
        </div>
      )}
    </div>
  )
}
