import IngressAppOverrides from '../../components/IngressAppOverrides'
import IngressModeSelector from '../../components/IngressModeSelector'
import SsoToggleList from '../../components/SsoToggleList'
import UrlPreviewTable from '../../components/UrlPreviewTable'

interface IngressStepProps {
  selectedApps: string[]
  vmName: string
  ingressMode: string
  onIngressModeChange: (mode: string) => void
  ingressDomain: string
  onIngressDomainChange: (domain: string) => void
  onIngressValidationChange: (valid: boolean) => void
  tailnet: string
  onTailnetChange: (tailnet: string) => void
  ssoOverrides: Record<string, boolean>
  onSsoOverridesChange: (overrides: Record<string, boolean>) => void
  ingressAppOverrides: Record<string, string>
  onIngressAppOverridesChange: (overrides: Record<string, string>) => void
}

export default function IngressStep({
  selectedApps,
  vmName,
  ingressMode,
  onIngressModeChange,
  ingressDomain,
  onIngressDomainChange,
  onIngressValidationChange,
  tailnet,
  onTailnetChange,
  ssoOverrides,
  onSsoOverridesChange,
  ingressAppOverrides,
  onIngressAppOverridesChange,
}: IngressStepProps) {
  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-lg font-semibold mb-4">Ingress &amp; SSO</h2>
        <p className="text-sm text-gray-600 mb-4">
          Choose how apps will be accessed and configure SSO protection.
        </p>
        <IngressModeSelector
          mode={ingressMode}
          onModeChange={onIngressModeChange}
          domain={ingressDomain}
          onDomainChange={onIngressDomainChange}
          onValidationChange={onIngressValidationChange}
          onTailnetResolved={onTailnetChange}
        />
      </div>
      <SsoToggleList
        selectedApps={selectedApps}
        ssoOverrides={ssoOverrides}
        onOverridesChange={onSsoOverridesChange}
        ingressMode={ingressMode}
      />
      <IngressAppOverrides
        selectedApps={selectedApps}
        clusterDefault={ingressMode}
        appOverrides={ingressAppOverrides}
        onAppOverridesChange={onIngressAppOverridesChange}
      />
      <UrlPreviewTable
        selectedApps={selectedApps}
        ingressMode={ingressMode}
        domain={ingressDomain}
        tailnet={tailnet}
        vmName={vmName}
        ssoOverrides={ssoOverrides}
        ingressAppOverrides={ingressAppOverrides}
      />
    </div>
  )
}
