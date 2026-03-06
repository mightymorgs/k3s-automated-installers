import { useQuery } from '@tanstack/react-query'
import { api, NetworkShare, InventoryMount } from '../api/client'

interface ShareSelectorProps {
  location: string
  selectedMounts: InventoryMount[]
  onChange: (mounts: InventoryMount[]) => void
}

/**
 * ShareSelector -- shows available network shares for a location.
 *
 * Fetches shares from GET /api/v1/storage/network-shares/{location}.
 * User checks shares to include as VM mounts. Credentials are NOT
 * shown (stripped by API). Share metadata (name, type, source) is
 * displayed for selection.
 */
export default function ShareSelector({
  location,
  selectedMounts,
  onChange,
}: ShareSelectorProps) {
  const shares = useQuery({
    queryKey: ['network-shares', location],
    queryFn: () => api.networkShares(location),
    enabled: !!location,
  })

  const isSelected = (share: NetworkShare) =>
    selectedMounts.some((m) => m.share_id === share.id)

  const toggleShare = (share: NetworkShare) => {
    if (isSelected(share)) {
      onChange(selectedMounts.filter((m) => m.share_id !== share.id))
    } else {
      onChange([
        ...selectedMounts,
        {
          share_id: share.id,
          mount_type: share.mount_type,
          source: share.source,
          mount_point: share.mount_point,
        },
      ])
    }
  }

  if (!location) {
    return (
      <div className="bg-yellow-50 border border-yellow-200 rounded-md p-4">
        <p className="text-sm text-yellow-700">
          Select a hypervisor first to see available network shares.
        </p>
      </div>
    )
  }

  if (shares.isLoading) {
    return <p className="text-gray-500">Loading shares for {location}...</p>
  }

  if (shares.error) {
    return (
      <p className="text-red-600">
        Failed to load shares: {(shares.error as Error).message}
      </p>
    )
  }

  const shareList = shares.data?.shares || []

  if (shareList.length === 0) {
    return (
      <div className="bg-gray-50 border border-gray-200 rounded-md p-4">
        <p className="text-sm text-gray-600">
          No network shares available for location "{location}".
          VMs will use Longhorn (local) storage only.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-gray-600">
        Select network shares to mount on this VM. Shares are managed
        per-location and shared across all VMs at "{location}".
      </p>
      {shareList.map((share: NetworkShare) => (
        <label
          key={share.id}
          className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
            isSelected(share)
              ? 'bg-blue-50 border-blue-400'
              : 'bg-white border-gray-200 hover:border-blue-200'
          }`}
        >
          <input
            type="checkbox"
            checked={isSelected(share)}
            onChange={() => toggleShare(share)}
            className="mt-1"
          />
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <span className="font-medium text-sm">{share.name}</span>
              <span
                className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                  share.mount_type === 'nfs'
                    ? 'bg-green-100 text-green-700'
                    : 'bg-purple-100 text-purple-700'
                }`}
              >
                {share.mount_type.toUpperCase()}
              </span>
            </div>
            <div className="text-xs text-gray-500 mt-1 space-y-0.5">
              <div>Source: <span className="font-mono">{share.source}</span></div>
              <div>Mount: <span className="font-mono">{share.mount_point}</span></div>
              {share.verified_at && (
                <div>
                  Verified: {new Date(share.verified_at).toLocaleDateString()}
                </div>
              )}
            </div>
          </div>
        </label>
      ))}
    </div>
  )
}
