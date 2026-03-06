// web/src/components/DiffModal.tsx

const SENSITIVE_FIELDS = new Set([
  'private_key_b64',
  'cluster_token',
  'oauth_client_secret_key',
])

interface DiffEntry {
  old: unknown
  new: unknown
}

interface DiffModalProps {
  changes: Record<string, DiffEntry>
  onConfirm: () => void
  onCancel: () => void
  isSaving: boolean
}

function formatDiffValue(key: string, value: unknown): string {
  if (value === null || value === undefined) return '(empty)'
  const field = key.split('.').pop() || key
  if (SENSITIVE_FIELDS.has(field) && typeof value === 'string' && value.length > 0) {
    return value.slice(0, 8) + '...'
  }
  if (Array.isArray(value)) return value.join(', ') || '(none)'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export default function DiffModal({ changes, onConfirm, onCancel, isSaving }: DiffModalProps) {
  const entries = Object.entries(changes)

  // Group by section
  const grouped: Record<string, [string, DiffEntry][]> = {}
  for (const [key, diff] of entries) {
    const section = key.split('.')[0]
    if (!grouped[section]) grouped[section] = []
    grouped[section].push([key, diff])
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[80vh] flex flex-col">
        <div className="px-6 py-4 border-b">
          <h2 className="text-lg font-semibold">Review Changes</h2>
          <p className="text-sm text-gray-500 mt-1">
            {entries.length} field{entries.length !== 1 ? 's' : ''} changed
          </p>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {entries.length === 0 ? (
            <p className="text-gray-500 text-sm">No changes to save.</p>
          ) : (
            Object.entries(grouped).map(([section, fields]) => (
              <div key={section}>
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                  {section}
                </h3>
                <div className="space-y-2">
                  {fields.map(([key, diff]) => (
                    <div key={key} className="rounded border overflow-hidden">
                      <div className="px-3 py-1 bg-gray-50 text-xs font-medium text-gray-600">
                        {key}
                      </div>
                      <div className="grid grid-cols-2 divide-x">
                        <div className="px-3 py-2 bg-red-50 text-sm text-red-800">
                          {formatDiffValue(key, diff.old)}
                        </div>
                        <div className="px-3 py-2 bg-green-50 text-sm text-green-800">
                          {formatDiffValue(key, diff.new)}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>

        <div className="px-6 py-4 border-t flex justify-end gap-3">
          <button
            onClick={onCancel}
            disabled={isSaving}
            className="px-4 py-2 text-sm text-gray-700 border rounded hover:bg-gray-50 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={isSaving || entries.length === 0}
            className="px-4 py-2 text-sm text-white bg-blue-600 rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {isSaving ? 'Saving...' : 'Confirm Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
