import { Link } from 'react-router-dom'

interface ReviewStepProps {
  requestBody: Record<string, any>
  error: Error | null
  created: boolean
}

export default function ReviewStep({ requestBody, error, created }: ReviewStepProps) {
  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">Review &amp; Create</h2>
      <p className="text-sm text-gray-600 mb-4">
        Review the configuration below, then create the VM.
      </p>
      <pre className="bg-gray-50 border rounded-md p-4 text-sm font-mono overflow-auto mb-4">
        {JSON.stringify(requestBody, null, 2)}
      </pre>
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-md p-3 mb-4">
          <p className="text-sm text-red-700">{error.message}</p>
        </div>
      )}
      {created && (
        <div className="bg-green-50 border border-green-200 rounded-md p-4 mb-4">
          <p className="text-sm text-green-700 font-medium">VM created successfully!</p>
          <Link
            to="/vms"
            className="text-sm text-green-600 underline hover:text-green-800 mt-1 inline-block"
          >
            View all VMs
          </Link>
        </div>
      )}
    </div>
  )
}
