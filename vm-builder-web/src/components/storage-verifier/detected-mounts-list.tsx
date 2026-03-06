import { MountListProps } from './types'

export default function DetectedMountsList({
  mounts,
  verifyResults,
  verifyPending,
  onVerify,
  onBrowse,
  onSelect,
}: MountListProps) {
  return (
    <div className="max-h-64 overflow-y-auto">
      {mounts.map((mount) => {
        const verifyResult = verifyResults[mount.source]
        return (
          <div
            key={mount.source}
            className="px-3 py-2 border-b border-gray-50 last:border-b-0"
          >
            <div className="flex items-center justify-between gap-2">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span
                    className={`text-xs font-mono px-1.5 py-0.5 rounded ${
                      mount.mount_type === 'nfs'
                        ? 'bg-blue-100 text-blue-700'
                        : 'bg-purple-100 text-purple-700'
                    }`}
                  >
                    {mount.mount_type.toUpperCase()}
                  </span>
                  <span className="text-sm text-gray-800 truncate">{mount.source}</span>
                  {verifyResult && (
                    <span
                      className={`text-xs ${
                        verifyResult.accessible ? 'text-green-600' : 'text-red-600'
                      }`}
                    >
                      {verifyResult.accessible ? '\u2713 OK' : '\u2717 Failed'}
                    </span>
                  )}
                </div>
                <div className="text-xs text-gray-400 mt-0.5">{'\u2192'} {mount.mount_point}</div>
              </div>
              <div className="flex gap-1 flex-shrink-0">
                <button
                  type="button"
                  onClick={() => onVerify(mount)}
                  disabled={verifyPending}
                  className="text-xs bg-gray-100 text-gray-600 px-2 py-1 rounded hover:bg-gray-200"
                >
                  Verify
                </button>
                <button
                  type="button"
                  onClick={() => onBrowse(mount)}
                  className="text-xs bg-gray-100 text-gray-600 px-2 py-1 rounded hover:bg-gray-200"
                >
                  Browse
                </button>
                <button
                  type="button"
                  onClick={() => onSelect(mount.mount_point)}
                  className="text-xs bg-green-500 text-white px-2 py-1 rounded hover:bg-green-600"
                >
                  Select
                </button>
              </div>
            </div>
            {verifyResult && !verifyResult.accessible && verifyResult.error && (
              <div className="text-xs text-red-500 mt-1">{verifyResult.error}</div>
            )}
            {verifyResult && verifyResult.accessible && verifyResult.contents.length > 0 && (
              <div className="text-xs text-gray-500 mt-1">
                Contents: {verifyResult.contents.join(', ')}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
