import { useState, useEffect } from 'react'
import { api } from '../api/client'

/** Subtype options keyed by vmtype. */
const SUBTYPE_OPTIONS: Record<string, string[]> = {
  k3s: ['master', 'worker', 'agent'],
  docker: ['standalone', 'swarm'],
  bare: ['standalone'],
  lxc: ['standalone'],
}

const VMTYPE_OPTIONS = ['k3s', 'docker', 'bare', 'lxc']
const STATE_OPTIONS = ['prod', 'staging', 'dev', 'test']
const PLATFORM_OPTIONS = ['libvirt', 'gcp', 'vsphere', 'proxmox']

/**
 * 7-segment VM name builder.
 * Format: {client}-{vmtype}-{subtype}-{state}-{purpose}-{platform}-{version}
 *
 * Validates the assembled name against the backend with a 500ms debounce.
 */
export default function VmNameBuilder({
  value,
  onChange,
}: {
  value: Record<string, string>
  onChange: (v: Record<string, string>) => void
}) {
  const [validation, setValidation] = useState<{
    valid: boolean
    error?: string
  } | null>(null)
  const [validating, setValidating] = useState(false)

  // Build the full hyphen-delimited name from individual parts
  const fullName = [
    value.client || '',
    value.vmtype || '',
    value.subtype || '',
    value.state || '',
    value.purpose || '',
    value.platform || '',
    value.version || '',
  ].join('-')

  // When vmtype changes, reset subtype to the first available option
  const handleVmTypeChange = (vmtype: string) => {
    const subtypes = SUBTYPE_OPTIONS[vmtype] || ['standalone']
    onChange({ ...value, vmtype, subtype: subtypes[0] })
  }

  // Update a single field in the name record
  const set = (field: string, v: string) => {
    onChange({ ...value, [field]: v })
  }

  // Debounced validation against the backend
  useEffect(() => {
    // Skip validation if any segment is empty
    const hasEmpty = [
      value.client,
      value.vmtype,
      value.subtype,
      value.state,
      value.purpose,
      value.platform,
      value.version,
    ].some((v) => !v)

    if (hasEmpty) {
      setValidation(null)
      return
    }

    setValidating(true)
    const timer = setTimeout(() => {
      api
        .validateName(fullName)
        .then(() => {
          setValidation({ valid: true })
          setValidating(false)
        })
        .catch((err: Error) => {
          setValidation({ valid: false, error: err.message })
          setValidating(false)
        })
    }, 500)

    return () => clearTimeout(timer)
  }, [fullName])

  const subtypes = SUBTYPE_OPTIONS[value.vmtype] || ['standalone']

  return (
    <div>
      <div className="grid grid-cols-2 gap-4 mb-6">
        {/* Client */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Client
          </label>
          <input
            type="text"
            value={value.client || ''}
            onChange={(e) => set('client', e.target.value)}
            placeholder="homelab"
            className="w-full border rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
        </div>

        {/* VM Type */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            VM Type
          </label>
          <select
            value={value.vmtype || ''}
            onChange={(e) => handleVmTypeChange(e.target.value)}
            className="w-full border rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="">Select...</option>
            {VMTYPE_OPTIONS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>

        {/* Subtype */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Subtype
          </label>
          <select
            value={value.subtype || ''}
            onChange={(e) => set('subtype', e.target.value)}
            className="w-full border rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="">Select...</option>
            {subtypes.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        {/* State */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            State
          </label>
          <select
            value={value.state || ''}
            onChange={(e) => set('state', e.target.value)}
            className="w-full border rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="">Select...</option>
            {STATE_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        {/* Purpose */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Purpose
          </label>
          <input
            type="text"
            value={value.purpose || ''}
            onChange={(e) => set('purpose', e.target.value)}
            placeholder="demo"
            className="w-full border rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
        </div>

        {/* Platform */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Platform
          </label>
          <select
            value={value.platform || ''}
            onChange={(e) => set('platform', e.target.value)}
            className="w-full border rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="">Select...</option>
            {PLATFORM_OPTIONS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>

        {/* Version */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Version
          </label>
          <input
            type="text"
            value={value.version || ''}
            onChange={(e) => set('version', e.target.value)}
            placeholder="latest"
            className="w-full border rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
        </div>
      </div>

      {/* Live name preview */}
      <div className="bg-gray-50 border rounded-md p-4">
        <label className="block text-sm font-medium text-gray-700 mb-1">
          VM Name Preview
        </label>
        <code className="text-sm font-mono text-gray-900">{fullName}</code>

        {/* Validation status */}
        <div className="mt-2">
          {validating && (
            <span className="text-sm text-gray-500">Validating...</span>
          )}
          {!validating && validation?.valid && (
            <span className="text-sm text-green-600">
              &#10003; Valid name
            </span>
          )}
          {!validating && validation && !validation.valid && (
            <span className="text-sm text-red-600">
              &#10007; {validation.error}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
