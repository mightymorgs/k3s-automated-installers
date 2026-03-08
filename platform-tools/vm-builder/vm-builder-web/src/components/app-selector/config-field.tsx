import { useState } from 'react'
import { InventoryMount } from '../../api/client'
import StorageVerifier from '../StorageVerifier'

interface ConfigFieldProps {
  appId: string
  fieldName: string
  fieldDef: any
  value: string
  onChange: (appId: string, field: string, value: string) => void
  hypervisorName?: string
  selectedMounts?: InventoryMount[]
}

export default function ConfigField({
  appId,
  fieldName,
  fieldDef,
  value,
  onChange,
  hypervisorName,
  selectedMounts,
}: ConfigFieldProps) {
  const fieldType = fieldDef.type || 'string'
  const label = fieldDef.label || fieldName
  const description = fieldDef.description || ''
  const placeholder = fieldDef.placeholder || fieldDef.default?.toString() || ''
  const isSecret = fieldType === 'secret'

  const [showSecret, setShowSecret] = useState(false)

  return (
    <div>
      <label className="block text-xs font-medium text-gray-700 mb-1">
        {label}
        {fieldDef.required && <span className="text-red-500 ml-0.5">*</span>}
      </label>
      {fieldType === 'choice' ? (
        <select
          value={value || fieldDef.default || ''}
          onChange={(e) => onChange(appId, fieldName, e.target.value)}
          className="w-full text-sm border border-gray-300 rounded px-2 py-1.5 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
        >
          {(fieldDef.options || []).map((opt: any) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      ) : fieldType === 'boolean' ? (
        <input
          type="checkbox"
          checked={value === 'true' || (!value && fieldDef.default === true)}
          onChange={(e) =>
            onChange(appId, fieldName, e.target.checked ? 'true' : 'false')
          }
          className="mt-0.5"
        />
      ) : fieldType === 'directory' ? (
        <StorageVerifier
          hypervisorName={hypervisorName || ''}
          value={value}
          onChange={(path) => onChange(appId, fieldName, path)}
          placeholder={placeholder ? `Default: ${placeholder}` : 'Select a storage path...'}
          selectedMounts={selectedMounts}
        />
      ) : (
        <div className="relative">
          <input
            type={isSecret && !showSecret ? 'password' : 'text'}
            value={value}
            placeholder={placeholder ? `Default: ${placeholder}` : ''}
            onChange={(e) => onChange(appId, fieldName, e.target.value)}
            className="w-full text-sm border border-gray-300 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-400 pr-8"
          />
          {isSecret && (
            <button
              type="button"
              onClick={() => setShowSecret(!showSecret)}
              className="absolute right-2 top-1.5 text-xs text-gray-400 hover:text-gray-600"
            >
              {showSecret ? 'Hide' : 'Show'}
            </button>
          )}
        </div>
      )}
      {description && <p className="text-xs text-gray-400 mt-0.5">{description}</p>}
    </div>
  )
}
