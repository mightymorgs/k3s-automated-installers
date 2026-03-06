import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import VmTable from './vm-table'

export default function VmListPage() {
  const queryClient = useQueryClient()
  const [clientFilter, setClientFilter] = useState<string>('')

  const vms = useQuery({
    queryKey: ['vms', clientFilter],
    queryFn: () => api.listVms(clientFilter || undefined),
  })

  const health = useQuery({
    queryKey: ['vm-health', clientFilter],
    queryFn: () => api.vmHealth(clientFilter || undefined),
    refetchInterval: 30_000,
  })

  const healthMap = new Map<string, any>()
  if (health.data) {
    for (const healthEntry of health.data) {
      healthMap.set(healthEntry.vm_name, healthEntry)
    }
  }

  const deployVm = useMutation({
    mutationFn: (name: string) => api.deployVm(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vms'] })
    },
  })

  const deleteVm = useMutation({
    mutationFn: (name: string) => api.deleteVm(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vms'] })
    },
  })

  const destroyVm = useMutation({
    mutationFn: (name: string) => api.destroyVm(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vms'] })
    },
  })

  const handleDeploy = (name: string) => {
    deployVm.mutate(name)
  }

  const handleDelete = (name: string) => {
    if (!window.confirm(`Delete VM "${name}"? This cannot be undone.`)) {
      return
    }
    deleteVm.mutate(name)
  }

  const handleDestroy = (name: string) => {
    const confirmed = window.prompt(
      `DANGER: This will permanently destroy VM "${name}" and all its infrastructure.\n\n` +
      `This action is IRREVERSIBLE. It will:\n` +
      `- Run terragrunt destroy on the hypervisor\n` +
      `- Remove the Tailscale device\n` +
      `- De-register any GitHub runner\n` +
      `- Delete the BWS inventory entry\n\n` +
      `Type the VM name to confirm:`
    )
    if (confirmed !== name) {
      return
    }
    destroyVm.mutate(name)
  }

  const clients = Array.from(
    new Set((vms.data || []).map((vm: any) => vm.client).filter(Boolean))
  ).sort() as string[]

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">VMs</h1>
        <Link
          to="/vm/create"
          className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700"
        >
          Create VM
        </Link>
      </div>

      <div className="mb-4">
        <select
          value={clientFilter}
          onChange={(event) => setClientFilter(event.target.value)}
          className="border rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
        >
          <option value="">All clients</option>
          {clients.map((client) => (
            <option key={client} value={client}>
              {client}
            </option>
          ))}
        </select>
      </div>

      {(deployVm.error || deleteVm.error || destroyVm.error) && (
        <div className="bg-red-50 border border-red-200 rounded-md p-3 mb-4">
          <p className="text-sm text-red-700">
            {(deployVm.error as Error)?.message ||
              (deleteVm.error as Error)?.message ||
              (destroyVm.error as Error)?.message}
          </p>
        </div>
      )}

      {vms.isLoading && <p className="text-gray-500">Loading VMs...</p>}

      {vms.error && (
        <p className="text-red-600">Failed to load VMs: {(vms.error as Error).message}</p>
      )}

      {vms.data && vms.data.length === 0 && (
        <div className="bg-white border rounded-lg p-8 text-center">
          <p className="text-gray-500 mb-4">No VMs found</p>
          <Link
            to="/vm/create"
            className="text-sm text-blue-600 hover:text-blue-800 underline"
          >
            Create your first VM
          </Link>
        </div>
      )}

      {vms.data && vms.data.length > 0 && (
        <VmTable
          vms={vms.data}
          healthMap={healthMap}
          deployPending={deployVm.isPending}
          deletePending={deleteVm.isPending}
          destroyPending={destroyVm.isPending}
          onDeploy={handleDeploy}
          onDelete={handleDelete}
          onDestroy={handleDestroy}
        />
      )}
    </div>
  )
}
