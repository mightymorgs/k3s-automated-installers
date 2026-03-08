/** Sensitive field names whose values should be masked. */
export const SENSITIVE_FIELDS = new Set([
  'private_key_b64',
  'cluster_token',
  'oauth_client_secret_key',
])

export function formatValue(key: string, value: unknown): string {
  if (value === null || value === undefined) return '-'
  if (SENSITIVE_FIELDS.has(key) && typeof value === 'string' && value.length > 0) {
    return value.slice(0, 8) + '...'
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return '(none)'
    // If array contains objects, show key fields on separate lines
    if (typeof value[0] === 'object' && value[0] !== null) {
      return value
        .map((v: Record<string, unknown>) => {
          // For mounts: show "source → mount_point (type)"
          if ('mount_point' in v && 'source' in v) {
            return `${v.source} → ${v.mount_point} (${v.mount_type})`
          }
          return JSON.stringify(v)
        })
        .join('\n')
    }
    return value.join(', ')
  }
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

export default function SectionCard({
  title,
  data,
}: {
  title: string
  data: Record<string, unknown>
}) {
  const entries = Object.entries(data)
  if (entries.length === 0) return null

  // Separate simple values from nested objects
  const simple: [string, unknown][] = []
  const nested: [string, Record<string, unknown>][] = []

  for (const [k, v] of entries) {
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      nested.push([k, v as Record<string, unknown>])
    } else {
      simple.push([k, v])
    }
  }

  return (
    <div className="bg-white border rounded-lg overflow-hidden">
      <div className="bg-gray-50 border-b px-4 py-2">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
          {title}
        </h2>
      </div>
      <dl className="divide-y divide-gray-100">
        {simple.map(([key, val]) => (
          <div key={key} className="px-4 py-2 flex justify-between gap-4">
            <dt className="text-sm font-medium text-gray-500 min-w-[180px]">{key}</dt>
            <dd className="text-sm text-gray-900 text-right break-all whitespace-pre-wrap">
              {formatValue(key, val)}
            </dd>
          </div>
        ))}
        {nested.map(([key, obj]) => (
          <div key={key} className="px-4 py-2">
            <dt className="text-sm font-medium text-gray-500 mb-1">{key}</dt>
            <dd className="ml-4">
              <dl className="divide-y divide-gray-50">
                {Object.entries(obj).map(([nk, nv]) => (
                  <div key={nk} className="py-1 flex justify-between gap-4">
                    <dt className="text-sm text-gray-400 min-w-[140px]">{nk}</dt>
                    <dd className="text-sm text-gray-900 text-right break-all whitespace-pre-wrap">
                      {formatValue(nk, nv)}
                    </dd>
                  </div>
                ))}
              </dl>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
