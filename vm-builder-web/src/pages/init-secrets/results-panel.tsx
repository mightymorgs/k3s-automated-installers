interface ResultsPanelProps {
  results: any[]
}

function statusDotClass(status: string): string {
  if (status === 'created') {
    return 'bg-green-500'
  }
  if (status === 'updated') {
    return 'bg-blue-500'
  }
  if (status === 'skipped') {
    return 'bg-yellow-500'
  }
  return 'bg-red-500'
}

function statusTextClass(status: string): string {
  if (status === 'created') {
    return 'text-green-600'
  }
  if (status === 'updated') {
    return 'text-blue-600'
  }
  if (status === 'skipped') {
    return 'text-yellow-600'
  }
  return 'text-red-600'
}

export default function ResultsPanel({ results }: ResultsPanelProps) {
  return (
    <div className="mt-6 bg-white rounded-lg border p-6">
      <h2 className="text-lg font-semibold mb-4">Results</h2>
      <div className="space-y-2">
        {results.map((result: any, index: number) => (
          <div key={index} className="flex items-center gap-2 text-sm">
            <span className={`w-2 h-2 rounded-full ${statusDotClass(result.status)}`} />
            <span className="font-mono text-gray-700">{result.path}</span>
            <span className={`font-medium ${statusTextClass(result.status)}`}>{result.status}</span>
            {result.error && <span className="text-red-600">- {result.error}</span>}
          </div>
        ))}
      </div>
    </div>
  )
}
