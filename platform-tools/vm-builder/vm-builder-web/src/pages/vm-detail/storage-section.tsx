import ShareSelector from '../../components/ShareSelector'
import { InventoryMount } from '../../api/client'

interface StorageSectionProps {
  editMode: boolean
  location: string
  mounts: InventoryMount[]
  appPaths: Record<string, unknown>
  onMountsChange: (mounts: InventoryMount[]) => void
}

export default function StorageSection({
  editMode,
  location,
  mounts,
  appPaths,
  onMountsChange,
}: StorageSectionProps) {
  return (
    <div className="bg-white border rounded-lg overflow-hidden">
      <div className="bg-gray-50 border-b px-4 py-2">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Storage</h2>
      </div>

      <dl className="divide-y divide-gray-100">
        <div className="px-4 py-2 flex justify-between gap-4 items-center">
          <dt className="text-sm font-medium text-gray-500 min-w-[180px]">location</dt>
          <dd className="text-sm text-gray-900 text-right">{location || '-'}</dd>
        </div>

        <div className="px-4 py-2">
          <dt className="text-sm font-medium text-gray-500 mb-2">mounts</dt>
          <dd>
            {editMode ? (
              <ShareSelector
                location={location}
                selectedMounts={mounts}
                onChange={onMountsChange}
              />
            ) : (
              <MountsDisplay mounts={mounts} />
            )}
          </dd>
        </div>

        {Object.keys(appPaths).length > 0 && (
          <div className="px-4 py-2">
            <dt className="text-sm font-medium text-gray-500 mb-1">app_paths</dt>
            <dd className="ml-4">
              <dl className="divide-y divide-gray-50">
                {Object.entries(appPaths).map(([app, paths]) => (
                  <div key={app} className="py-1 flex justify-between gap-4 items-center">
                    <dt className="text-sm text-gray-400 min-w-[140px]">{app}</dt>
                    <dd className="text-sm text-gray-900 text-right break-all whitespace-pre-wrap flex-1">
                      {typeof paths === 'object' && paths !== null
                        ? Object.entries(paths as Record<string, string>)
                            .map(([k, v]) => `${k}: ${v}`)
                            .join('\n')
                        : String(paths)}
                    </dd>
                  </div>
                ))}
              </dl>
            </dd>
          </div>
        )}
      </dl>
    </div>
  )
}

function MountsDisplay({ mounts }: { mounts: InventoryMount[] }) {
  if (mounts.length === 0) {
    return <p className="text-sm text-gray-400 italic">No mounts configured</p>
  }

  return (
    <div className="space-y-1.5">
      {mounts.map((m) => (
        <div
          key={m.share_id}
          className="flex items-center gap-2 text-sm"
        >
          <span
            className={`px-1.5 py-0.5 rounded text-xs font-medium ${
              m.mount_type === 'nfs'
                ? 'bg-green-100 text-green-700'
                : 'bg-purple-100 text-purple-700'
            }`}
          >
            {m.mount_type.toUpperCase()}
          </span>
          <span className="font-mono text-gray-600">{m.source}</span>
          <span className="text-gray-400">{'\u2192'}</span>
          <span className="font-mono text-gray-900">{m.mount_point}</span>
        </div>
      ))}
    </div>
  )
}
