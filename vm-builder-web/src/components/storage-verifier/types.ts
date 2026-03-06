import { InventoryMount, StorageMount, StorageVerifyResult } from '../../api/client'

export interface StorageVerifierProps {
  hypervisorName: string
  value: string
  onChange: (path: string) => void
  placeholder?: string
  selectedMounts?: InventoryMount[]
}

export interface MountListProps {
  mounts: StorageMount[]
  verifyResults: Record<string, StorageVerifyResult>
  verifyPending: boolean
  onVerify: (mount: StorageMount) => void
  onBrowse: (mount: StorageMount) => void
  onSelect: (mountPoint: string) => void
}

export interface BrowseViewProps {
  browsePath: string
  mountLabel?: string
  entries: { name: string; entry_type: string }[]
  isLoading: boolean
  error: Error | null
  onBack: () => void
  onBrowseDir: (name: string) => void
  onSelectPath: () => void
  onNavigateTo: (path: string) => void
}
