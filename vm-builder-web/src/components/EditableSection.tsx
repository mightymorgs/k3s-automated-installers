// web/src/components/EditableSection.tsx
import { useState } from 'react'

/** Fields that are never editable (read-only display). */
const NON_EDITABLE: Record<string, Set<string>> = {
  identity: new Set(['hostname', 'client', 'vmtype', 'subtype', 'state', 'purpose', 'version']),
  ssh: new Set(['user', 'keypair']),
  tailscale: new Set(['oauth_client_id_key', 'oauth_client_secret_key', 'tailnet_key']),
  k3s: new Set(['role', 'cluster_token']),
}

/** Entirely read-only sections. */
const READONLY_SECTIONS = new Set(['bootstrap', '_state'])

/** Sensitive field names whose values should be masked. */
const SENSITIVE_FIELDS = new Set([
  'private_key_b64',
  'cluster_token',
  'oauth_client_secret_key',
])

/** Human-readable labels for sections. */
const SECTION_LABELS: Record<string, string> = {
  identity: 'Identity',
  hardware: 'Hardware',
  network: 'Network',
  ssh: 'SSH',
  tailscale: 'Tailscale',
  k3s: 'K3s',
  provider: 'Provider',
  storage: 'Storage',
  apps: 'Applications',
  ingress: 'Ingress & SSO',
  bootstrap: 'Bootstrap',
  _state: 'State',
}

function isEditable(section: string, field: string): boolean {
  if (READONLY_SECTIONS.has(section)) return false
  return !(NON_EDITABLE[section]?.has(field) ?? false)
}

function formatReadOnlyValue(key: string, value: unknown): string {
  if (value === null || value === undefined) return '-'
  if (SENSITIVE_FIELDS.has(key) && typeof value === 'string' && value.length > 0) {
    return value.slice(0, 8) + '...'
  }
  if (Array.isArray(value)) return value.length === 0 ? '(none)' : value.join(', ')
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

interface EditableSectionProps {
  section: string
  data: Record<string, unknown>
  editMode: boolean
  editedData: Record<string, unknown>
  onFieldChange: (section: string, field: string, value: unknown) => void
}

export default function EditableSection({
  section,
  data,
  editMode,
  editedData,
  onFieldChange,
}: EditableSectionProps) {
  const title = SECTION_LABELS[section] || section
  const isReadonlySection = READONLY_SECTIONS.has(section)
  const entries = Object.entries(data)
  if (entries.length === 0) return null

  // Separate flat fields from nested objects
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
      <div className="bg-gray-50 border-b px-4 py-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
          {title}
        </h2>
        {isReadonlySection && editMode && (
          <span className="text-xs text-gray-400 italic">Read-only</span>
        )}
      </div>
      <dl className="divide-y divide-gray-100">
        {simple.map(([key, val]) => {
          const editable = editMode && isEditable(section, key)
          const currentValue = editMode ? (editedData[key] ?? val) : val

          return (
            <div key={key} className="px-4 py-2 flex justify-between gap-4 items-center">
              <dt className="text-sm font-medium text-gray-500 min-w-[180px]">
                {key}
                {editMode && !isEditable(section, key) && !isReadonlySection && (
                  <span className="ml-1 text-xs text-gray-300">(locked)</span>
                )}
              </dt>
              <dd className="text-sm text-gray-900 text-right break-all whitespace-pre-wrap flex-1">
                {editable ? (
                  <FieldEditor
                    field={key}
                    value={currentValue}
                    onChange={(v) => onFieldChange(section, key, v)}
                  />
                ) : (
                  formatReadOnlyValue(key, currentValue)
                )}
              </dd>
            </div>
          )
        })}
        {nested.map(([key, obj]) => {
          const editable = editMode && isEditable(section, key)
          const nestedEdited = (editedData[key] as Record<string, unknown>) || {}

          return (
            <div key={key} className="px-4 py-2">
              <dt className="text-sm font-medium text-gray-500 mb-1">
                {key}
                {editMode && !isEditable(section, key) && !isReadonlySection && (
                  <span className="ml-1 text-xs text-gray-300">(locked)</span>
                )}
              </dt>
              <dd className="ml-4">
                <dl className="divide-y divide-gray-50">
                  {Object.entries(obj).map(([nk, nv]) => {
                    const nestedCurrentValue = editable ? (nestedEdited[nk] ?? nv) : nv
                    return (
                      <div key={nk} className="py-1 flex justify-between gap-4 items-center">
                        <dt className="text-sm text-gray-400 min-w-[140px]">{nk}</dt>
                        <dd className="text-sm text-gray-900 text-right break-all whitespace-pre-wrap flex-1">
                          {editable ? (
                            <FieldEditor
                              field={nk}
                              value={nestedCurrentValue}
                              onChange={(v) => {
                                const updated = { ...obj, ...nestedEdited, [nk]: v }
                                onFieldChange(section, key, updated)
                              }}
                            />
                          ) : (
                            formatReadOnlyValue(nk, nestedCurrentValue)
                          )}
                        </dd>
                      </div>
                    )
                  })}
                </dl>
              </dd>
            </div>
          )
        })}
      </dl>
    </div>
  )
}

/** Renders a comma-separated text input for array values. */
function ArrayEditor({
  value,
  onChange,
}: {
  value: unknown[]
  onChange: (v: unknown) => void
}) {
  const [text, setText] = useState(value.join(', '))
  return (
    <input
      type="text"
      value={text}
      onChange={(e) => {
        setText(e.target.value)
        onChange(e.target.value.split(',').map((s: string) => s.trim()).filter(Boolean))
      }}
      placeholder="comma-separated values"
      className="w-full text-sm border border-gray-300 rounded px-2 py-1 text-right focus:ring-1 focus:ring-blue-400"
    />
  )
}

/** Renders an appropriate input based on the value type. */
function FieldEditor({
  field: _field,
  value,
  onChange,
}: {
  field: string
  value: unknown
  onChange: (v: unknown) => void
}) {
  if (typeof value === 'boolean') {
    return (
      <select
        value={value ? 'true' : 'false'}
        onChange={(e) => onChange(e.target.value === 'true')}
        className="text-sm border border-gray-300 rounded px-2 py-1 bg-white focus:ring-1 focus:ring-blue-400"
      >
        <option value="true">Yes</option>
        <option value="false">No</option>
      </select>
    )
  }

  if (typeof value === 'number') {
    return (
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full text-sm border border-gray-300 rounded px-2 py-1 text-right focus:ring-1 focus:ring-blue-400"
      />
    )
  }

  if (Array.isArray(value)) {
    return <ArrayEditor value={value} onChange={onChange} />
  }

  // Default: string input
  return (
    <input
      type="text"
      value={String(value ?? '')}
      onChange={(e) => onChange(e.target.value)}
      className="w-full text-sm border border-gray-300 rounded px-2 py-1 text-right focus:ring-1 focus:ring-blue-400"
    />
  )
}
