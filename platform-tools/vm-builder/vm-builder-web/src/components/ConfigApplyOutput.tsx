import { ConfigApplyResult } from '../api/client'

interface ConfigApplyOutputProps {
  result: ConfigApplyResult
  onClose: () => void
}

export default function ConfigApplyOutput({
  result,
  onClose,
}: ConfigApplyOutputProps) {
  return (
    <div className="mt-3 rounded border overflow-hidden">
      <div
        className={`px-3 py-2 text-sm font-medium flex items-center justify-between ${
          result.success
            ? 'bg-green-50 text-green-800 border-b border-green-200'
            : 'bg-red-50 text-red-800 border-b border-red-200'
        }`}
      >
        <span>
          {result.dry_run ? 'Dry Run' : 'Applied'}: {result.summary}
        </span>
        <button
          onClick={onClose}
          className="text-xs text-gray-500 hover:text-gray-700 ml-2"
        >
          Dismiss
        </button>
      </div>

      <div className="px-3 py-2 text-xs text-gray-500 bg-gray-50 border-b">
        Host: {result.hostname} | Namespace: {result.namespace}
      </div>

      <div className="divide-y">
        {result.results.map((r) => (
          <div key={r.file} className="px-3 py-2">
            <div className="flex items-center gap-2">
              <span
                className={`text-xs font-mono px-1.5 py-0.5 rounded ${
                  r.success
                    ? 'bg-green-100 text-green-700'
                    : 'bg-red-100 text-red-700'
                }`}
              >
                {r.success ? 'OK' : 'FAIL'}
              </span>
              <span className="text-sm font-medium">{r.file}</span>
            </div>
            {r.output && (
              <pre className="mt-1 text-xs text-gray-600 font-mono whitespace-pre-wrap">
                {r.output}
              </pre>
            )}
            {r.error && (
              <pre className="mt-1 text-xs text-red-600 font-mono whitespace-pre-wrap">
                {r.error}
              </pre>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
