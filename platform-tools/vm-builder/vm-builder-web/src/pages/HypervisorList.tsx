import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api/client'

/**
 * Hypervisor List page -- table of all hypervisors from BWS inventory.
 *
 * Fetches hypervisors from GET /api/v1/hypervisors.
 * Name column links to the detail page.
 */
export default function HypervisorList() {
  const hypervisors = useQuery({
    queryKey: ['hypervisors'],
    queryFn: () => api.listHypervisors(),
  })

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Hypervisors</h1>
        <Link
          to="/hypervisor"
          className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700"
        >
          Bootstrap New
        </Link>
      </div>

      {/* Loading state */}
      {hypervisors.isLoading && (
        <p className="text-gray-500">Loading hypervisors...</p>
      )}

      {/* Error state */}
      {hypervisors.error && (
        <p className="text-red-600">
          Failed to load hypervisors: {(hypervisors.error as Error).message}
        </p>
      )}

      {/* Empty state */}
      {hypervisors.data && hypervisors.data.length === 0 && (
        <div className="bg-white border rounded-lg p-8 text-center">
          <p className="text-gray-500 mb-4">No hypervisors found</p>
          <Link
            to="/hypervisor"
            className="text-sm text-blue-600 hover:text-blue-800 underline"
          >
            Bootstrap your first hypervisor
          </Link>
        </div>
      )}

      {/* Hypervisor table */}
      {hypervisors.data && hypervisors.data.length > 0 && (
        <div className="bg-white border rounded-lg overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b">
                <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide px-4 py-3">
                  Name
                </th>
                <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide px-4 py-3">
                  Client
                </th>
                <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide px-4 py-3">
                  Platform
                </th>
                <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide px-4 py-3">
                  State
                </th>
                <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide px-4 py-3">
                  Location
                </th>
                <th className="text-center text-xs font-medium text-gray-500 uppercase tracking-wide px-4 py-3">
                  Phase 0
                </th>
                <th className="text-center text-xs font-medium text-gray-500 uppercase tracking-wide px-4 py-3">
                  Ready
                </th>
              </tr>
            </thead>
            <tbody>
              {hypervisors.data.map((hv: any) => (
                <tr
                  key={hv.name}
                  className="border-b last:border-b-0 hover:bg-gray-50"
                >
                  <td className="px-4 py-3 text-sm font-medium">
                    <Link
                      to={`/hypervisors/${encodeURIComponent(hv.name)}`}
                      className="text-blue-600 hover:text-blue-800 hover:underline"
                    >
                      {hv.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {hv.client || '-'}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {hv.platform || '-'}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <span
                      className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                        hv.state === 'prod'
                          ? 'bg-green-100 text-green-700'
                          : hv.state === 'staging'
                            ? 'bg-yellow-100 text-yellow-700'
                            : hv.state === 'dev'
                              ? 'bg-blue-100 text-blue-700'
                              : 'bg-gray-100 text-gray-700'
                      }`}
                    >
                      {hv.state || '-'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {hv.location || '-'}
                  </td>
                  <td className="px-4 py-3 text-center text-sm">
                    {hv.phase0_completed ? (
                      <span className="text-green-600 font-medium">&#10003;</span>
                    ) : (
                      <span className="text-gray-400">&#8211;</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-center text-sm">
                    {hv.ready_for_phase2 ? (
                      <span className="text-green-600 font-medium">&#10003;</span>
                    ) : (
                      <span className="text-gray-400">&#8211;</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
