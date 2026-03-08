import { useState } from 'react'

export default function SecretInput({ label, name, value, onChange, exists, required = true }: {
  label: string; name: string; value: string; onChange: (v: string) => void;
  exists?: boolean; required?: boolean;
}) {
  const [show, setShow] = useState(false)
  return (
    <div className="mb-3">
      <label className="block text-sm font-medium text-gray-700 mb-1">
        {label}
        {exists !== undefined && (
          <span className={`ml-2 text-xs ${exists ? 'text-green-600' : 'text-gray-400'}`}>
            {exists ? '(exists in BWS)' : '(not set)'}
          </span>
        )}
      </label>
      <div className="relative">
        <input
          type={show ? 'text' : 'password'}
          name={name}
          value={value}
          onChange={e => onChange(e.target.value)}
          required={required}
          className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 pr-16"
        />
        <button
          type="button"
          onClick={() => setShow(!show)}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-500 hover:text-gray-700"
        >
          {show ? 'Hide' : 'Show'}
        </button>
      </div>
    </div>
  )
}
