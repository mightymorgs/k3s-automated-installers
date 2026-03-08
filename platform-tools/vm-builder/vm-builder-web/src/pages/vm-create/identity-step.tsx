import VmNameBuilder from '../../components/VmNameBuilder'

interface IdentityStepProps {
  masterName: string | null
  nameParts: Record<string, string>
  onNamePartsChange: (parts: Record<string, string>) => void
}

export default function IdentityStep({
  masterName,
  nameParts,
  onNamePartsChange,
}: IdentityStepProps) {
  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">VM Identity</h2>
      {masterName && (
        <div className="bg-blue-50 border border-blue-200 rounded-md p-3 mb-4">
          <p className="text-sm text-blue-700">
            Creating worker for master: <span className="font-mono font-medium">{masterName}</span>
          </p>
          <p className="text-xs text-blue-600 mt-1">
            Client, state, platform, and version are inherited from the master.
            The purpose field will be auto-suffixed with a worker index.
          </p>
        </div>
      )}
      <p className="text-sm text-gray-600 mb-4">
        Configure the 7-segment VM name. Each segment is separated by hyphens.
      </p>
      <VmNameBuilder value={nameParts} onChange={onNamePartsChange} />
    </div>
  )
}
