import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api/client'

export default function Dashboard() {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health })

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Dashboard</h1>
      <div className="grid grid-cols-2 gap-4 mb-8">
        <StatusCard
          label="BWS CLI"
          available={health.data?.bws?.available}
          error={health.data?.bws?.error}
          loading={health.isLoading}
        />
        <StatusCard
          label="GitHub CLI"
          available={health.data?.gh?.available}
          error={health.data?.gh?.error}
          loading={health.isLoading}
        />
      </div>
      <h2 className="text-lg font-semibold mb-4">Quick Actions</h2>
      <div className="grid grid-cols-3 gap-4">
        <ActionCard
          to="/init"
          title="Init Secrets"
          desc="Configure shared infrastructure secrets"
        />
        <ActionCard
          to="/vm/create"
          title="Create VM"
          desc="Build a new VM inventory"
        />
        <ActionCard
          to="/vms"
          title="Browse VMs"
          desc="View existing VM inventories"
        />
      </div>
    </div>
  )
}

function StatusCard({
  label,
  available,
  error,
  loading,
}: {
  label: string
  available?: boolean
  error?: string
  loading: boolean
}) {
  return (
    <div className="bg-white rounded-lg border p-4">
      <div className="flex items-center gap-2">
        <span
          className={`w-3 h-3 rounded-full ${loading ? 'bg-gray-300' : available ? 'bg-green-500' : 'bg-red-500'}`}
        />
        <span className="font-medium">{label}</span>
      </div>
      {error && <p className="text-sm text-red-600 mt-1">{error}</p>}
    </div>
  )
}

function ActionCard({
  to,
  title,
  desc,
}: {
  to: string
  title: string
  desc: string
}) {
  return (
    <Link
      to={to}
      className="bg-white rounded-lg border p-4 hover:border-blue-500 transition-colors"
    >
      <h3 className="font-medium">{title}</h3>
      <p className="text-sm text-gray-500 mt-1">{desc}</p>
    </Link>
  )
}
