import { Link } from 'react-router-dom'

interface ClusterSectionProps {
  vmName: string
  hasToken: boolean
  workersLoading: boolean
  workers: any[] | undefined
  persistTokenPending: boolean
  persistTokenError: Error | null
  persistTokenSuccess: boolean
  onPersistToken: () => void
}

export default function ClusterSection({
  vmName,
  hasToken,
  workersLoading,
  workers,
  persistTokenPending,
  persistTokenError,
  persistTokenSuccess,
  onPersistToken,
}: ClusterSectionProps) {
  return (
    <div className="bg-white border rounded-lg overflow-hidden">
      <div className="bg-gray-50 border-b px-4 py-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Cluster</h2>
        {hasToken && (
          <Link
            to={`/vm/create?master=${encodeURIComponent(vmName)}`}
            className="px-3 py-1 text-xs font-medium text-white bg-green-600 rounded hover:bg-green-700"
          >
            Add Worker
          </Link>
        )}
      </div>
      <div className="p-4">
        {!hasToken && (
          <div className="mb-4">
            <p className="text-sm text-yellow-700 mb-2">
              No cluster token persisted yet. Deploy this master first,
              then persist the token to enable worker creation.
            </p>
            <button
              onClick={onPersistToken}
              disabled={persistTokenPending}
              className="px-3 py-1.5 text-sm font-medium text-white bg-blue-600 rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {persistTokenPending ? 'Persisting...' : 'Persist Token'}
            </button>
            {persistTokenError && (
              <p className="text-sm text-red-600 mt-2">{persistTokenError.message}</p>
            )}
            {persistTokenSuccess && (
              <p className="text-sm text-green-600 mt-2">
                Token persisted successfully. Reload to see updated status.
              </p>
            )}
          </div>
        )}

        {hasToken && (
          <>
            {workersLoading && <p className="text-sm text-gray-500">Loading workers...</p>}
            {workers && workers.length === 0 && (
              <p className="text-sm text-gray-500">
                No workers yet. Click "Add Worker" to scale up.
              </p>
            )}
            {workers && workers.length > 0 && (
              <div className="space-y-2">
                <p className="text-sm font-medium text-gray-700 mb-2">
                  {workers.length} worker{workers.length !== 1 ? 's' : ''}
                </p>
                {workers.map((worker: any) => (
                  <div
                    key={worker.name}
                    className="flex items-center justify-between border rounded px-3 py-2"
                  >
                    <Link
                      to={`/vms/${encodeURIComponent(worker.name)}`}
                      className="text-sm text-blue-600 hover:text-blue-800 hover:underline"
                    >
                      {worker.name}
                    </Link>
                    <span className="text-xs text-gray-500">
                      {worker.state} | {worker.phase}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
