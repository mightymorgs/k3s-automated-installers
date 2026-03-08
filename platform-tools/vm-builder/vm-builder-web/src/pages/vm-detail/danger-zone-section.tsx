interface DangerZoneSectionProps {
  vmName: string
  isK3sMaster: boolean
  workers: any[] | undefined
  vmRole: string | undefined
  onDestroy: () => void
  destroyPending: boolean
}

export default function DangerZoneSection({
  vmName,
  isK3sMaster,
  workers,
  vmRole,
  onDestroy,
  destroyPending,
}: DangerZoneSectionProps) {
  const handleDestroy = () => {
    const confirmed = window.prompt(
      `DANGER: This will permanently destroy VM "${vmName}" and all its infrastructure.\n\n` +
      `This action is IRREVERSIBLE. It will:\n` +
      `- Run terragrunt destroy on the hypervisor\n` +
      `- Remove the Tailscale device\n` +
      `- De-register any GitHub runner\n\n` +
      `Type the VM name to confirm:`
    )
    if (confirmed !== vmName) {
      return
    }
    onDestroy()
  }

  return (
    <div className="mt-8 border border-red-300 rounded-lg overflow-hidden">
      <div className="bg-red-50 border-b border-red-300 px-4 py-2">
        <h2 className="text-sm font-semibold text-red-700 uppercase tracking-wide">
          Danger Zone
        </h2>
      </div>
      <div className="p-4 space-y-3">
        {isK3sMaster && workers && workers.length > 0 && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-md p-3">
            <p className="text-sm text-yellow-800 font-medium">
              Warning: This master has {workers.length} active worker
              {workers.length !== 1 ? 's' : ''}.
            </p>
            <p className="text-xs text-yellow-700 mt-1">
              Destroying this master will leave workers orphaned. They will
              continue running but cannot rejoin or be managed. Destroy workers
              first, or plan for master replacement.
            </p>
          </div>
        )}

        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-gray-900">Destroy this VM</p>
            <p className="text-xs text-gray-500">
              Permanently destroy the VM infrastructure and remove all associated resources.
              {vmRole === 'agent' && ' The node will be drained before destruction.'}
            </p>
          </div>
          <button
            onClick={handleDestroy}
            disabled={destroyPending}
            className="px-4 py-2 text-sm font-semibold text-white bg-red-600 rounded hover:bg-red-700 disabled:opacity-50"
          >
            {destroyPending ? 'Destroying...' : 'Destroy VM'}
          </button>
        </div>
      </div>
    </div>
  )
}
