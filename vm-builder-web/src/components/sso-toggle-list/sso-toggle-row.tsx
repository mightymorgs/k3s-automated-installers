import ShieldIcon from './shield-icon'
import { SsoToggleRowProps } from './types'

export default function SsoToggleRow({
  app,
  active,
  expanded,
  onToggle,
  onToggleExpanded,
}: SsoToggleRowProps) {
  const appId = app.id || app.name
  const subdomain = app.ingress?.subdomain
  const bypassPaths = app.sso?.bypass_paths || []
  const hasBypassPaths = bypassPaths.length > 0

  return (
    <div className="rounded-md border border-gray-200 bg-white">
      <div className="flex items-center gap-3 px-3 py-2.5">
        <ShieldIcon active={active} />

        <div className="flex-1 min-w-0">
          <span className="text-sm font-medium text-gray-900">
            {app.display_name || app.name || appId}
          </span>
          {subdomain && <span className="text-xs text-gray-400 ml-2">{subdomain}</span>}
        </div>

        {active ? (
          <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">
            SSO Protected
          </span>
        ) : (
          <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">
            Direct Access
          </span>
        )}

        <button
          type="button"
          onClick={() => onToggle(appId)}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
            active ? 'bg-blue-600' : 'bg-gray-200'
          }`}
          aria-label={`Toggle SSO for ${app.display_name || app.name || appId}`}
        >
          <span
            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
              active ? 'translate-x-6' : 'translate-x-1'
            }`}
          />
        </button>

        {hasBypassPaths && (
          <button
            type="button"
            onClick={() => onToggleExpanded(appId)}
            className="text-gray-400 hover:text-gray-600"
            aria-label={`${expanded ? 'Hide' : 'Show'} bypass paths`}
          >
            <svg
              className={`w-4 h-4 transition-transform ${expanded ? 'rotate-180' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M19 9l-7 7-7-7"
              />
            </svg>
          </button>
        )}
      </div>

      {hasBypassPaths && expanded && (
        <div className="border-t border-gray-100 px-3 py-2 bg-gray-50">
          <p className="text-xs text-gray-500 font-medium mb-1">Bypass Paths (read-only)</p>
          <ul className="space-y-0.5">
            {bypassPaths.map((path) => (
              <li key={path} className="text-xs text-gray-600 font-mono">
                {path}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
