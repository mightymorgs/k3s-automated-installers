import { InventoryMount } from '../../api/client'
import AppsStep from './apps-step'
import HardwareStep from './hardware-step'
import HypervisorStep from './hypervisor-step'
import IdentityStep from './identity-step'
import IngressStep from './ingress-step'
import ReviewStep from './review-step'
import StorageStep from './storage-step'
import { buildVmName } from './payload'
import { VmNameParts } from './types'

type WizardStep = {
  label: string
  content: React.ReactNode
  canProceed?: boolean
}

type BuildVmCreateStepsArgs = {
  masterName: string | null
  nameParts: VmNameParts
  onNamePartsChange: (parts: Partial<VmNameParts>) => void
  isGcp: boolean
  hypervisorsLoading: boolean
  hypervisorsError: Error | null
  filteredHypervisors: any[]
  selectedHypervisor: string
  onSelectHypervisor: (name: string) => void
  sizesLoading: boolean
  sizesError: Error | null
  sizesData: Record<string, any> | undefined
  selectedSize: string
  onSelectSize: (size: string) => void
  gcpConfig: any
  onGcpConfigChange: (value: any) => void
  k3sOverhead: { cpu_millicores: number; memory_mb: number }
  defaults: Record<string, any>
  hasResourceDefaults: boolean
  hypervisorLocation: string
  selectedMounts: InventoryMount[]
  onMountsChange: (mounts: InventoryMount[]) => void
  selectedApps: string[]
  onSelectedAppsChange: (apps: string[]) => void
  appConfigs: Record<string, Record<string, string | number | boolean>>
  onAppConfigsChange: (configs: Record<string, Record<string, string | number | boolean>>) => void
  selectedSizeData: any
  selectedAppData: any[]
  ingressMode: string
  onIngressModeChange: (mode: string) => void
  ingressDomain: string
  onIngressDomainChange: (domain: string) => void
  ingressValid: boolean
  onIngressValidationChange: (valid: boolean) => void
  tailnet: string
  onTailnetChange: (tailnet: string) => void
  ssoOverrides: Record<string, boolean>
  onSsoOverridesChange: (overrides: Record<string, boolean>) => void
  ingressAppOverrides: Record<string, string>
  onIngressAppOverridesChange: (overrides: Record<string, string>) => void
  requestBody: Record<string, any>
  createVmError: Error | null
  created: boolean
}

export function buildVmCreateSteps(args: BuildVmCreateStepsArgs): WizardStep[] {
  return [
    {
      label: 'Identity',
      content: (
        <IdentityStep
          masterName={args.masterName}
          nameParts={args.nameParts}
          onNamePartsChange={args.onNamePartsChange}
        />
      ),
    },
    {
      label: 'Hypervisor',
      content: (
        <HypervisorStep
          isGcp={args.isGcp}
          platform={args.nameParts.platform}
          hypervisorsLoading={args.hypervisorsLoading}
          hypervisorsError={args.hypervisorsError}
          filteredHypervisors={args.filteredHypervisors}
          selectedHypervisor={args.selectedHypervisor}
          onSelectHypervisor={args.onSelectHypervisor}
        />
      ),
    },
    {
      label: 'Hardware',
      content: (
        <HardwareStep
          isGcp={args.isGcp}
          sizesLoading={args.sizesLoading}
          sizesError={args.sizesError}
          sizesData={args.sizesData}
          selectedSize={args.selectedSize}
          onSelectSize={args.onSelectSize}
          gcpConfig={args.gcpConfig}
          onGcpConfigChange={args.onGcpConfigChange}
          k3sOverhead={args.k3sOverhead}
          defaults={args.defaults}
          hasResourceDefaults={args.hasResourceDefaults}
        />
      ),
    },
    {
      label: 'Storage',
      content: (
        <StorageStep
          hypervisorLocation={args.hypervisorLocation}
          selectedMounts={args.selectedMounts}
          onMountsChange={args.onMountsChange}
        />
      ),
    },
    {
      label: 'Apps',
      content: (
        <AppsStep
          selectedApps={args.selectedApps}
          onSelectedAppsChange={args.onSelectedAppsChange}
          appConfigs={args.appConfigs}
          onAppConfigsChange={args.onAppConfigsChange}
          selectedHypervisor={args.selectedHypervisor}
          currentHardware={args.selectedSizeData}
          selectedAppData={args.selectedAppData}
          k3sOverhead={args.k3sOverhead}
          defaults={args.defaults}
          hasResourceDefaults={args.hasResourceDefaults}
          selectedSize={args.selectedSize}
          selectedMounts={args.selectedMounts}
        />
      ),
    },
    {
      label: 'Ingress',
      content: (
        <IngressStep
          selectedApps={args.selectedApps}
          vmName={buildVmName(args.nameParts)}
          ingressMode={args.ingressMode}
          onIngressModeChange={args.onIngressModeChange}
          ingressDomain={args.ingressDomain}
          onIngressDomainChange={args.onIngressDomainChange}
          onIngressValidationChange={args.onIngressValidationChange}
          tailnet={args.tailnet}
          onTailnetChange={args.onTailnetChange}
          ssoOverrides={args.ssoOverrides}
          onSsoOverridesChange={args.onSsoOverridesChange}
          ingressAppOverrides={args.ingressAppOverrides}
          onIngressAppOverridesChange={args.onIngressAppOverridesChange}
        />
      ),
      canProceed: args.ingressValid,
    },
    {
      label: 'Review',
      content: (
        <ReviewStep
          requestBody={args.requestBody}
          error={args.createVmError}
          created={args.created}
        />
      ),
    },
  ]
}
