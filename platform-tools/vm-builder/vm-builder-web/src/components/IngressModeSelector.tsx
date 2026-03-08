import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '../api/client'

/**
 * Ingress mode configuration for three modes:
 *   - title: Display name shown on the radio card
 *   - description: One-line explanation shown below the title
 *   - key: Value stored in inventory (nodeport | tailscale | cloudflare)
 */
const INGRESS_MODES = [
  {
    key: 'nodeport',
    title: 'NodePort',
    description: 'Direct port access for dev/testing. No DNS or TLS.',
  },
  {
    key: 'tailscale',
    title: 'Tailscale MagicDNS',
    description: 'Private VPN access with automatic HTTPS.',
  },
  {
    key: 'cloudflare',
    title: 'Cloudflare Tunnel',
    description: 'Public access with DDoS protection and custom domain.',
  },
] as const

interface IngressModeSelectorProps {
  mode: string
  onModeChange: (mode: string) => void
  domain: string
  onDomainChange: (domain: string) => void
  onValidationChange?: (isValid: boolean) => void
  onTailnetResolved?: (tailnet: string) => void
}

/**
 * IngressModeSelector -- radio card selector for ingress mode.
 *
 * Renders three radio cards (NodePort, Tailscale, Cloudflare).
 * When Cloudflare is selected, a domain input appears with server-side
 * validation on blur. When Tailscale is selected, the tailnet name is
 * fetched and displayed. Validation state is exported to the parent
 * via onValidationChange so the wizard can gate the Next button.
 */
export default function IngressModeSelector({
  mode,
  onModeChange,
  domain,
  onDomainChange,
  onValidationChange,
  onTailnetResolved,
}: IngressModeSelectorProps) {
  // Track whether the Cloudflare domain has been validated successfully
  const [domainValid, setDomainValid] = useState(false)
  // Track whether the domain field has been touched (blurred at least once)
  const [domainTouched, setDomainTouched] = useState(false)

  // Ref to avoid calling onValidationChange on initial render with stale state
  const prevValidRef = useRef<boolean | null>(null)

  // --- Task 4.2: Cloudflare domain validation via useMutation ---
  const validateMutation = useMutation({
    mutationFn: (body: { mode: string; domain?: string }) =>
      api.validateIngress(body),
    onSuccess: (result) => {
      setDomainValid(result.valid)
    },
    onError: () => {
      setDomainValid(false)
    },
  })

  /** Validate domain on blur (not on every keystroke) */
  const handleDomainBlur = () => {
    setDomainTouched(true)
    if (domain.trim()) {
      validateMutation.mutate({ mode: 'cloudflare', domain: domain.trim() })
    } else {
      setDomainValid(false)
    }
  }

  // --- Task 4.3: Tailscale tailnet fetch ---
  const tailnetQuery = useQuery({
    queryKey: ['tailnet'],
    queryFn: () => api.getTailnet(),
    enabled: mode === 'tailscale',
    retry: false,
  })

  // Notify parent when tailnet is resolved
  useEffect(() => {
    if (tailnetQuery.data?.tailnet && onTailnetResolved) {
      onTailnetResolved(tailnetQuery.data.tailnet)
    }
  }, [tailnetQuery.data?.tailnet])

  // --- Task 4.4: Export validation state ---
  // Compute whether the current configuration is valid
  const isValid =
    mode === 'nodeport' || mode === 'tailscale' || (mode === 'cloudflare' && domainValid)

  useEffect(() => {
    if (prevValidRef.current !== isValid) {
      prevValidRef.current = isValid
      onValidationChange?.(isValid)
    }
  }, [isValid])

  // When mode changes, reset domain validation state appropriately
  const handleModeChange = (newMode: string) => {
    onModeChange(newMode)
    // Reset domain validation state when switching away from cloudflare
    if (newMode !== 'cloudflare') {
      setDomainValid(false)
      setDomainTouched(false)
    }
  }

  return (
    <div className="space-y-4">
      {/* Radio cards */}
      <div className="grid gap-3">
        {INGRESS_MODES.map((option) => {
          const isSelected = mode === option.key
          return (
            <button
              key={option.key}
              type="button"
              onClick={() => handleModeChange(option.key)}
              className={`flex items-start gap-3 p-4 rounded-lg text-left transition-colors ${
                isSelected
                  ? 'border-2 border-blue-500 bg-blue-50'
                  : 'border border-gray-200 bg-white hover:border-blue-200'
              }`}
            >
              {/* Radio circle indicator */}
              <span
                className={`mt-0.5 flex-shrink-0 w-4 h-4 rounded-full border-2 flex items-center justify-center ${
                  isSelected
                    ? 'border-blue-500'
                    : 'border-gray-300'
                }`}
              >
                {isSelected && (
                  <span className="w-2 h-2 rounded-full bg-blue-500" />
                )}
              </span>

              {/* Card content */}
              <div>
                <span className="text-sm font-medium text-gray-900">
                  {option.title}
                </span>
                <p className="text-xs text-gray-500 mt-0.5">
                  {option.description}
                </p>
              </div>
            </button>
          )
        })}
      </div>

      {/* Task 4.1/4.2: Cloudflare domain input with validation feedback */}
      {mode === 'cloudflare' && (
        <div className="pl-7">
          <label className="block text-xs font-medium text-gray-700 mb-1">
            Domain
          </label>
          <input
            type="text"
            value={domain}
            placeholder="example.com"
            onChange={(e) => {
              onDomainChange(e.target.value)
              // Reset validation when user edits after a previous validation
              if (domainTouched) {
                setDomainValid(false)
              }
            }}
            onBlur={handleDomainBlur}
            className={`w-full text-sm border rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-400 ${
              domainTouched && validateMutation.data
                ? validateMutation.data.valid
                  ? 'border-green-400'
                  : 'border-red-400'
                : 'border-gray-300'
            }`}
          />

          {/* Validation feedback */}
          {validateMutation.isPending && (
            <p className="text-xs text-gray-400 mt-1">Validating...</p>
          )}

          {domainTouched && !validateMutation.isPending && validateMutation.data && (
            <div className="mt-1">
              {validateMutation.data.valid ? (
                <p className="text-xs text-green-600 flex items-center gap-1">
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                  Valid
                </p>
              ) : (
                <p className="text-xs text-red-600">
                  {validateMutation.data.error || 'Invalid domain'}
                </p>
              )}

              {/* Warnings (shown regardless of valid/invalid) */}
              {validateMutation.data.warnings &&
                validateMutation.data.warnings.length > 0 && (
                  <div className="mt-1 space-y-0.5">
                    {validateMutation.data.warnings.map((warning, i) => (
                      <p key={i} className="text-xs text-yellow-600">
                        {warning}
                      </p>
                    ))}
                  </div>
                )}
            </div>
          )}

          {domainTouched && !validateMutation.isPending && !domain.trim() && (
            <p className="text-xs text-red-600 mt-1">
              Domain is required for Cloudflare mode
            </p>
          )}
        </div>
      )}

      {/* Task 4.3: Tailscale tailnet info box */}
      {mode === 'tailscale' && (
        <div className="pl-7">
          {tailnetQuery.isLoading && (
            <div className="bg-blue-50 border border-blue-200 rounded-md px-3 py-2">
              <p className="text-sm text-blue-600">Loading tailnet info...</p>
            </div>
          )}

          {tailnetQuery.data?.tailnet && (
            <div className="bg-blue-50 border border-blue-200 rounded-md px-3 py-2">
              <p className="text-sm text-gray-700">
                Tailnet:{' '}
                <span className="font-semibold">{tailnetQuery.data.tailnet}</span>
              </p>
            </div>
          )}

          {tailnetQuery.error && (
            <div className="bg-yellow-50 border border-yellow-200 rounded-md px-3 py-2">
              <p className="text-sm text-yellow-700">
                Tailscale not configured. Set tailnet name on the Init Secrets page.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
