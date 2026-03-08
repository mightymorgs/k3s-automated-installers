interface StatusDotProps {
  vmName: string
  healthMap: Map<string, any>
}

export default function StatusDot({ vmName, healthMap }: StatusDotProps) {
  const health = healthMap.get(vmName)

  if (!health || health.tailscale_online === null || health.tailscale_online === undefined) {
    return <span title="Not found in Tailscale" className="inline-block w-2.5 h-2.5 rounded-full bg-gray-400" />
  }

  if (health.tailscale_online) {
    return (
      <span
        title={`Online via ${health.tailscale_ip || 'Tailscale'} (${health.os || 'unknown OS'})`}
        className="inline-block w-2.5 h-2.5 rounded-full bg-green-500"
      />
    )
  }

  return (
    <span
      title={`Offline since ${health.last_seen || 'unknown'}`}
      className="inline-block w-2.5 h-2.5 rounded-full bg-red-500"
    />
  )
}
