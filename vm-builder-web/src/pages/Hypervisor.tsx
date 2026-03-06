import { useState } from 'react'
import { api } from '../api/client'

/** Form state matching the HypervisorConfig Pydantic model. */
interface HypervisorFormState {
  name: string
  platform: string
  location: string
  local_ip: string
  ssh_user: string
  github_repo: string
  network_mode: string
}

const INITIAL_STATE: HypervisorFormState = {
  name: '',
  platform: 'libvirt',
  location: 'office',
  local_ip: '192.168.0.120',
  ssh_user: 'morgs',
  github_repo: '',
  network_mode: 'nat',
}

const PLATFORM_OPTIONS = ['libvirt', 'vsphere', 'proxmox']
const NETWORK_MODE_OPTIONS = ['nat', 'bridge']

export default function Hypervisor() {
  const [form, setForm] = useState<HypervisorFormState>(INITIAL_STATE)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  /** Computed hypervisor full name, mirrors HypervisorConfig.full_name on the backend. */
  const fullName = `hv-${form.name}-${form.platform}-${form.location}`

  function updateField(field: keyof HypervisorFormState, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)

    try {
      const response = await api.bootstrapHypervisor(form)
      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: response.statusText }))
        setError(err.detail || response.statusText)
        return
      }

      // Trigger file download from the response blob
      const blob = await response.blob()
      const disposition = response.headers.get('content-disposition')
      const filename = disposition?.match(/filename="(.+)"/)?.[1] || 'bootstrap.sh'
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate bootstrap script')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Hypervisor Bootstrap</h1>

      {/* Live name preview */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
        <p className="text-sm text-blue-700 font-medium">Full Hypervisor Name</p>
        <p className="text-lg font-mono mt-1 text-blue-900">{fullName}</p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div className="bg-white rounded-lg border p-6">
          <div className="grid grid-cols-2 gap-4">
            {/* Name */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Name <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => updateField('name', e.target.value)}
                required
                placeholder="e.g. workhorse"
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
              />
            </div>

            {/* Platform */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Platform
              </label>
              <select
                value={form.platform}
                onChange={(e) => updateField('platform', e.target.value)}
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
              >
                {PLATFORM_OPTIONS.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            </div>

            {/* Location */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Location
              </label>
              <input
                type="text"
                value={form.location}
                onChange={(e) => updateField('location', e.target.value)}
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
              />
            </div>

            {/* Local IP */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Local IP
              </label>
              <input
                type="text"
                value={form.local_ip}
                onChange={(e) => updateField('local_ip', e.target.value)}
                placeholder="192.168.0.120"
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
              />
            </div>

            {/* SSH User */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                SSH User
              </label>
              <input
                type="text"
                value={form.ssh_user}
                onChange={(e) => updateField('ssh_user', e.target.value)}
                placeholder="morgs"
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
              />
            </div>

            {/* GitHub Repo */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                GitHub Repo <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={form.github_repo}
                onChange={(e) => updateField('github_repo', e.target.value)}
                required
                placeholder="org/repo"
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
              />
            </div>

            {/* Network Mode */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Network Mode
              </label>
              <select
                value={form.network_mode}
                onChange={(e) => updateField('network_mode', e.target.value)}
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
              >
                {NETWORK_MODE_OPTIONS.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="mt-6">
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? 'Generating...' : 'Generate Bootstrap Script'}
            </button>
          </div>
        </div>
      </form>
    </div>
  )
}
