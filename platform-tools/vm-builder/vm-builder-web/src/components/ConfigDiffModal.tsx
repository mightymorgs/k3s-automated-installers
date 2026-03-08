import { ConfigPreviewResult } from '../api/client'

interface ConfigDiffModalProps {
  preview: ConfigPreviewResult
  onApply: () => void
  onClose: () => void
  isApplying: boolean
}

export default function ConfigDiffModal({
  preview,
  onApply,
  onClose,
  isApplying,
}: ConfigDiffModalProps) {
  const changedDiffs = preview.diffs.filter((d) => d.has_changes)

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full max-h-[80vh] flex flex-col">
        <div className="px-6 py-4 border-b">
          <h2 className="text-lg font-semibold">
            Config Preview: {preview.app_id}
          </h2>
          <p className="text-sm text-gray-500 mt-1">{preview.summary}</p>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {preview.warnings && preview.warnings.length > 0 && (
            <div className="rounded border border-yellow-300 bg-yellow-50 px-4 py-3">
              <p className="text-sm font-medium text-yellow-800 mb-1">Warnings</p>
              <ul className="list-disc list-inside text-sm text-yellow-700 space-y-0.5">
                {preview.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          {!preview.has_changes ? (
            <p className="text-gray-500 text-sm">
              No differences between rendered config and base manifests.
            </p>
          ) : (
            changedDiffs.map((entry) => (
              <div key={entry.file} className="rounded border overflow-hidden">
                <div className="px-3 py-2 bg-gray-50 text-sm font-medium text-gray-700 border-b">
                  {entry.file}
                </div>
                <pre className="px-3 py-2 text-xs font-mono overflow-x-auto bg-gray-900 text-gray-100 max-h-64">
                  {entry.diff.split('\n').map((line, i) => {
                    let cls = ''
                    if (line.startsWith('+') && !line.startsWith('+++')) cls = 'text-green-400'
                    else if (line.startsWith('-') && !line.startsWith('---')) cls = 'text-red-400'
                    else if (line.startsWith('@@')) cls = 'text-blue-400'
                    return (
                      <div key={i} className={cls}>
                        {line}
                      </div>
                    )
                  })}
                </pre>
              </div>
            ))
          )}

          {preview.diffs.filter((d) => !d.has_changes).length > 0 && (
            <p className="text-xs text-gray-400">
              {preview.diffs.filter((d) => !d.has_changes).length} file(s)
              unchanged
            </p>
          )}
        </div>

        <div className="px-6 py-4 border-t flex justify-end gap-3">
          <button
            onClick={onClose}
            disabled={isApplying}
            className="px-4 py-2 text-sm text-gray-700 border rounded hover:bg-gray-50 disabled:opacity-50"
          >
            Close
          </button>
          {preview.has_changes && (
            <button
              onClick={onApply}
              disabled={isApplying}
              className="px-4 py-2 text-sm text-white bg-green-600 rounded hover:bg-green-700 disabled:opacity-50"
            >
              {isApplying ? 'Applying...' : 'Apply to VM'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
