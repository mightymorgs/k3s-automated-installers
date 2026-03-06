import { InventoryMount } from '../../api/client'
import ShareSelector from '../../components/ShareSelector'

interface StorageStepProps {
  hypervisorLocation: string
  selectedMounts: InventoryMount[]
  onMountsChange: (mounts: InventoryMount[]) => void
}

export default function StorageStep({
  hypervisorLocation,
  selectedMounts,
  onMountsChange,
}: StorageStepProps) {
  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">Storage</h2>
      <p className="text-sm text-gray-600 mb-4">
        Select network shares to mount on the VM. Shares are shared across all
        VMs at the same location.
      </p>
      <ShareSelector
        location={hypervisorLocation}
        selectedMounts={selectedMounts}
        onChange={onMountsChange}
      />
    </div>
  )
}
