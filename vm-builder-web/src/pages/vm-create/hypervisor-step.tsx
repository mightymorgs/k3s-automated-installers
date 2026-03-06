import { Link } from 'react-router-dom'

interface HypervisorStepProps {
  isGcp: boolean
  platform: string
  hypervisorsLoading: boolean
  hypervisorsError: Error | null
  filteredHypervisors: any[]
  selectedHypervisor: string
  onSelectHypervisor: (name: string) => void
}

export default function HypervisorStep({
  isGcp,
  platform,
  hypervisorsLoading,
  hypervisorsError,
  filteredHypervisors,
  selectedHypervisor,
  onSelectHypervisor,
}: HypervisorStepProps) {
  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">Hypervisor</h2>
      {isGcp ? (
        <div className="bg-blue-50 border border-blue-200 rounded-md p-4">
          <p className="text-sm text-blue-700">
            No hypervisor needed for cloud platforms. GCP provisioning is handled
            via Terraform/Terragrunt -- press <strong>Next</strong> to continue.
          </p>
        </div>
      ) : (
        <>
          <p className="text-sm text-gray-600 mb-4">
            Select which hypervisor to create the VM on.
            {platform && (
              <span className="ml-1">
                Showing hypervisors for platform: <strong>{platform}</strong>
              </span>
            )}
          </p>
          {hypervisorsLoading && <p className="text-gray-500">Loading hypervisors...</p>}
          {hypervisorsError && (
            <p className="text-red-600">Failed to load hypervisors: {hypervisorsError.message}</p>
          )}
          {!hypervisorsLoading && !hypervisorsError && filteredHypervisors.length === 0 && (
            <div className="bg-yellow-50 border border-yellow-200 rounded-md p-4">
              <p className="text-sm text-yellow-700">
                No hypervisors found{platform ? ` for platform "${platform}"` : ''}.
                You can skip this step or <Link to="/hypervisor" className="underline">bootstrap a hypervisor</Link> first.
              </p>
            </div>
          )}
          {filteredHypervisors.length > 0 && (
            <div className="grid grid-cols-2 gap-4">
              {filteredHypervisors.map((hypervisor: any) => (
                <label
                  key={hypervisor.name}
                  className={`p-4 rounded-lg border cursor-pointer transition-colors ${
                    selectedHypervisor === hypervisor.name
                      ? 'bg-blue-50 border-blue-400 ring-2 ring-blue-200'
                      : 'bg-white border-gray-200 hover:border-blue-200'
                  }`}
                >
                  <input
                    type="radio"
                    name="hypervisor"
                    value={hypervisor.name}
                    checked={selectedHypervisor === hypervisor.name}
                    onChange={() => onSelectHypervisor(hypervisor.name)}
                    className="sr-only"
                  />
                  <div className="font-medium mb-2 text-sm break-all">{hypervisor.name}</div>
                  <div className="text-sm text-gray-600 space-y-1">
                    <div>
                      Platform: <span className="font-medium">{hypervisor.platform}</span>
                    </div>
                    <div>
                      State:{' '}
                      <span
                        className={`inline-block px-1.5 py-0.5 rounded text-xs font-medium ${
                          hypervisor.state === 'prod'
                            ? 'bg-green-100 text-green-700'
                            : hypervisor.state === 'dev'
                              ? 'bg-blue-100 text-blue-700'
                              : 'bg-gray-100 text-gray-700'
                        }`}
                      >
                        {hypervisor.state}
                      </span>
                    </div>
                    <div>
                      Location: <span className="font-medium">{hypervisor.location}</span>
                    </div>
                    <div>
                      Ready:{' '}
                      {hypervisor.ready_for_phase2 ? (
                        <span className="text-green-600 font-medium">Yes</span>
                      ) : (
                        <span className="text-gray-400">No</span>
                      )}
                    </div>
                  </div>
                </label>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
