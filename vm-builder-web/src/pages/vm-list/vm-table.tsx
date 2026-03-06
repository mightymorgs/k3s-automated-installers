import { Link } from 'react-router-dom'
import StatusDot from './status-dot'

interface VmTableProps {
  vms: any[]
  healthMap: Map<string, any>
  deployPending: boolean
  deletePending: boolean
  destroyPending: boolean
  onDeploy: (name: string) => void
  onDelete: (name: string) => void
  onDestroy: (name: string) => void
}

function stateBadgeClass(state: string): string {
  if (state === 'prod') {
    return 'bg-green-100 text-green-700'
  }
  if (state === 'staging') {
    return 'bg-yellow-100 text-yellow-700'
  }
  if (state === 'dev') {
    return 'bg-blue-100 text-blue-700'
  }
  return 'bg-gray-100 text-gray-700'
}

export default function VmTable({
  vms,
  healthMap,
  deployPending,
  deletePending,
  destroyPending,
  onDeploy,
  onDelete,
  onDestroy,
}: VmTableProps) {
  return (
    <div className="bg-white border rounded-lg overflow-hidden">
      <table className="w-full">
        <thead>
          <tr className="bg-gray-50 border-b">
            <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide px-4 py-3">Name</th>
            <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide px-4 py-3">Status</th>
            <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide px-4 py-3">Client</th>
            <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide px-4 py-3">Platform</th>
            <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide px-4 py-3">State</th>
            <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide px-4 py-3">Role</th>
            <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide px-4 py-3">Hypervisor</th>
            <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide px-4 py-3">Apps</th>
            <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide px-4 py-3">Phase</th>
            <th className="text-right text-xs font-medium text-gray-500 uppercase tracking-wide px-4 py-3">Actions</th>
          </tr>
        </thead>
        <tbody>
          {vms.map((vm: any) => {
            const vmName = vm.name || vm.vm_name
            return (
              <tr key={vmName} className="border-b last:border-b-0 hover:bg-gray-50">
                <td className="px-4 py-3 text-sm font-medium">
                  <div>
                    <Link
                      to={`/vms/${encodeURIComponent(vmName)}`}
                      className="text-blue-600 hover:text-blue-800 hover:underline"
                    >
                      {vmName}
                    </Link>
                    {vm.master_name && (
                      <div className="text-xs text-gray-400 mt-0.5">
                        worker of{' '}
                        <Link
                          to={`/vms/${encodeURIComponent(vm.master_name)}`}
                          className="text-gray-500 hover:text-blue-600"
                        >
                          {vm.master_name}
                        </Link>
                      </div>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3 text-sm text-center">
                  <StatusDot vmName={vmName} healthMap={healthMap} />
                </td>
                <td className="px-4 py-3 text-sm text-gray-600">{vm.client || '-'}</td>
                <td className="px-4 py-3 text-sm text-gray-600">{vm.platform || '-'}</td>
                <td className="px-4 py-3 text-sm">
                  <span
                    className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${stateBadgeClass(
                      vm.state
                    )}`}
                  >
                    {vm.state || '-'}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm">
                  {vm.k3s_role === 'server' && (
                    <span className="inline-flex items-center gap-1">
                      <span className="inline-block px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-700">
                        master
                      </span>
                      {vm.worker_count > 0 && <span className="text-xs text-gray-500">{vm.worker_count}w</span>}
                    </span>
                  )}
                  {vm.k3s_role === 'agent' && (
                    <span className="inline-block px-2 py-0.5 rounded text-xs font-medium bg-indigo-100 text-indigo-700">
                      worker
                    </span>
                  )}
                  {vm.k3s_role === 'none' && <span className="text-xs text-gray-400">-</span>}
                </td>
                <td className="px-4 py-3 text-sm text-gray-600">{vm.hypervisor || '-'}</td>
                <td className="px-4 py-3 text-sm text-gray-600">{vm.apps_count ?? '-'}</td>
                <td className="px-4 py-3 text-sm text-gray-600">{vm.phase || '-'}</td>
                <td className="px-4 py-3 text-right space-x-2">
                  <button
                    onClick={() => onDeploy(vmName)}
                    disabled={deployPending}
                    className="text-sm text-blue-600 hover:text-blue-800 disabled:opacity-50"
                  >
                    Deploy
                  </button>
                  <button
                    onClick={() => onDelete(vmName)}
                    disabled={deletePending}
                    className="text-sm text-red-600 hover:text-red-800 disabled:opacity-50"
                  >
                    Delete
                  </button>
                  <button
                    onClick={() => onDestroy(vmName)}
                    disabled={destroyPending}
                    className="text-sm text-red-700 font-semibold hover:text-red-900 disabled:opacity-50"
                  >
                    Destroy
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
