import { StorageVerifierProps } from './types'

interface ManualEntryProps extends Pick<StorageVerifierProps, 'value' | 'onChange' | 'placeholder'> {
  onDetect: () => void
}

export default function ManualEntry({
  value,
  onChange,
  placeholder,
  onDetect,
}: ManualEntryProps) {
  return (
    <div className="flex gap-2">
      <input
        type="text"
        value={value}
        placeholder={placeholder || 'Enter mount path manually...'}
        onChange={(e) => onChange(e.target.value)}
        className="flex-1 text-sm border border-gray-300 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-400"
      />
      <button
        type="button"
        onClick={onDetect}
        className="text-xs text-blue-600 hover:text-blue-800 px-2"
      >
        Detect
      </button>
    </div>
  )
}
