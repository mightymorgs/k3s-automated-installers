import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  api,
  StorageMount,
  StorageVerifyRequest,
  StorageVerifyResult,
} from '../../api/client'
import BrowseView from './browse-view'
import DetectedMountsList from './detected-mounts-list'
import ManualEntry from './manual-entry'
import { StorageVerifierProps } from './types'

export default function StorageVerifier({
  hypervisorName,
  value,
  onChange,
  placeholder,
  selectedMounts,
}: StorageVerifierProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [manualEntry, setManualEntry] = useState(false)
  const [browsePath, setBrowsePath] = useState<string | null>(null)
  const [activeMount, setActiveMount] = useState<StorageMount | null>(null)
  const [verifyResults, setVerifyResults] = useState<Record<string, StorageVerifyResult>>({})

  // Convert selectedMounts to StorageMount format for DetectedMountsList
  const selectedMountsAsStorage = (selectedMounts || []).map((m) => ({
    mount_type: m.mount_type as 'nfs' | 'smb',
    source: m.source,
    mount_point: m.mount_point,
    options: null,
  }))

  const hasSelectedMounts = selectedMountsAsStorage.length > 0

  const mounts = useQuery({
    queryKey: ['storage-mounts', hypervisorName],
    queryFn: () => api.storageMounts(hypervisorName),
    enabled: isOpen && !!hypervisorName && !hasSelectedMounts,
  })

  // Use selectedMounts when available, fall back to auto-detected
  const mountsData = hasSelectedMounts ? selectedMountsAsStorage : mounts.data
  const mountsLoading = hasSelectedMounts ? false : mounts.isLoading
  const mountsError = hasSelectedMounts ? null : mounts.error

  const browsing = useQuery({
    queryKey: ['storage-browse', hypervisorName, browsePath, activeMount?.source],
    queryFn: () =>
      api.storageBrowse(
        hypervisorName,
        browsePath!,
        activeMount
          ? {
              source: activeMount.source,
              mount_type: activeMount.mount_type,
              mount_point: activeMount.mount_point,
            }
          : undefined,
      ),
    enabled: isOpen && !!browsePath,
  })

  const verifyMutation = useMutation({
    mutationFn: (request: StorageVerifyRequest) => api.storageVerify(request),
    onSuccess: (result, variables) => {
      setVerifyResults((prev) => ({
        ...prev,
        [variables.source]: result,
      }))
    },
  })

  const handleVerify = (mountType: 'nfs' | 'smb', source: string) => {
    verifyMutation.mutate({
      hypervisor_name: hypervisorName,
      mount_type: mountType,
      source,
    })
  }

  const handleSelectMount = (mountPoint: string) => {
    onChange(mountPoint)
    setIsOpen(false)
  }

  const handleBrowseMount = (mount: StorageMount) => {
    setActiveMount(mount)
    setBrowsePath(mount.mount_point)
  }

  const handleBrowseDir = (dirName: string) => {
    const base = browsePath || ''
    setBrowsePath(base.endsWith('/') ? base + dirName : `${base}/${dirName}`)
  }

  const handleNavigateTo = (path: string) => {
    setBrowsePath(path)
  }

  const handleSelectBrowsedPath = () => {
    if (!browsePath) {
      return
    }
    onChange(browsePath)
    setIsOpen(false)
    setBrowsePath(null)
    setActiveMount(null)
  }

  if (manualEntry) {
    return (
      <ManualEntry
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        onDetect={() => setManualEntry(false)}
      />
    )
  }

  return (
    <div>
      <div className="flex gap-2 items-center">
        <input
          type="text"
          value={value}
          readOnly
          placeholder={placeholder || 'No storage path selected'}
          className="flex-1 text-sm border border-gray-300 rounded px-2 py-1.5 bg-gray-50 focus:outline-none"
        />
        <button
          type="button"
          onClick={() => {
            setIsOpen(!isOpen)
            setBrowsePath(null)
            setActiveMount(null)
          }}
          className="text-sm bg-blue-500 text-white px-3 py-1.5 rounded hover:bg-blue-600 transition-colors"
          disabled={!hypervisorName}
          title={!hypervisorName ? 'Select a hypervisor first' : 'Detect storage'}
        >
          {isOpen ? 'Close' : 'Detect...'}
        </button>
        <button
          type="button"
          onClick={() => setManualEntry(true)}
          className="text-xs text-gray-500 hover:text-gray-700 px-1"
          title="Type path manually"
        >
          Edit
        </button>
      </div>

      {isOpen && (
        <div className="mt-2 border border-gray-200 rounded-md bg-white shadow-sm">
          <div className="px-3 py-2 border-b border-gray-100 bg-gray-50 text-xs font-medium text-gray-600">
            {hasSelectedMounts ? 'Selected mount points' : `Storage mounts on ${hypervisorName}`}
          </div>

          {mountsLoading && (
            <div className="px-3 py-4 text-sm text-gray-500">Connecting to hypervisor...</div>
          )}

          {mountsError && (
            <div className="px-3 py-4 text-sm text-red-600">
              Could not reach hypervisor: {(mountsError as Error).message}
            </div>
          )}

          {mountsData && mountsData.length === 0 && !browsePath && (
            <div className="px-3 py-4 text-sm text-gray-400 italic">
              No NFS or SMB mounts detected on this hypervisor.
              <button
                type="button"
                onClick={() => setManualEntry(true)}
                className="ml-2 text-blue-500 hover:text-blue-700 underline"
              >
                Enter path manually
              </button>
            </div>
          )}

          {mountsData && mountsData.length > 0 && !browsePath && (
            <DetectedMountsList
              mounts={mountsData}
              verifyResults={verifyResults}
              verifyPending={verifyMutation.isPending}
              onVerify={(mount) => handleVerify(mount.mount_type, mount.source)}
              onBrowse={handleBrowseMount}
              onSelect={handleSelectMount}
            />
          )}

          {browsePath && (
            <BrowseView
              browsePath={browsePath}
              mountLabel={activeMount ? `${activeMount.mount_type.toUpperCase()} ${activeMount.source}` : undefined}
              entries={browsing.data?.entries || []}
              isLoading={browsing.isLoading}
              error={(browsing.error as Error) || null}
              onBack={() => {
                setBrowsePath(null)
                setActiveMount(null)
              }}
              onBrowseDir={handleBrowseDir}
              onSelectPath={handleSelectBrowsedPath}
              onNavigateTo={handleNavigateTo}
            />
          )}
        </div>
      )}
    </div>
  )
}
