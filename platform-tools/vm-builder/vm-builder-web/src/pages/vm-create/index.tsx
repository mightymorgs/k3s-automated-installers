import { useNavigate } from 'react-router-dom'
import StepWizard from '../../components/StepWizard'
import { buildVmCreateSteps } from './vm-create-steps'
import { useVmCreateController } from './use-vm-create-controller'

export default function VmCreatePage() {
  const navigate = useNavigate()

  const controller = useVmCreateController()

  const steps = buildVmCreateSteps({
    masterName: controller.masterName,
    nameParts: controller.nameParts,
    onNamePartsChange: (parts) =>
      controller.setNameParts((prev) => ({
        client: parts.client ?? prev.client,
        vmtype: parts.vmtype ?? prev.vmtype,
        subtype: parts.subtype ?? prev.subtype,
        state: parts.state ?? prev.state,
        purpose: parts.purpose ?? prev.purpose,
        platform: parts.platform ?? prev.platform,
        version: parts.version ?? prev.version,
      })),
    isGcp: controller.isGcp,
    hypervisorsLoading: controller.hypervisors.isLoading,
    hypervisorsError: (controller.hypervisors.error as Error) || null,
    filteredHypervisors: controller.filteredHypervisors,
    selectedHypervisor: controller.selectedHypervisor,
    onSelectHypervisor: controller.setSelectedHypervisor,
    sizesLoading: controller.sizes.isLoading,
    sizesError: (controller.sizes.error as Error) || null,
    sizesData: controller.sizes.data,
    selectedSize: controller.selectedSize,
    onSelectSize: controller.setSelectedSize,
    gcpConfig: controller.gcpConfig,
    onGcpConfigChange: controller.setGcpConfig,
    k3sOverhead: controller.k3sOverhead,
    defaults: controller.defaults,
    hasResourceDefaults: !!controller.resourceDefaults.data,
    hypervisorLocation: controller.hypervisorLocation,
    selectedMounts: controller.selectedMounts,
    onMountsChange: controller.setSelectedMounts,
    selectedApps: controller.selectedApps,
    onSelectedAppsChange: controller.setSelectedApps,
    appConfigs: controller.appConfigs,
    onAppConfigsChange: controller.setAppConfigs,
    selectedSizeData: controller.selectedSizeData,
    selectedAppData: controller.selectedAppData,
    ingressMode: controller.ingressMode,
    onIngressModeChange: controller.setIngressMode,
    ingressDomain: controller.ingressDomain,
    onIngressDomainChange: controller.setIngressDomain,
    ingressValid: controller.ingressValid,
    onIngressValidationChange: controller.setIngressValid,
    tailnet: controller.tailnet,
    onTailnetChange: controller.setTailnet,
    ssoOverrides: controller.ssoOverrides,
    onSsoOverridesChange: controller.setSsoOverrides,
    ingressAppOverrides: controller.ingressAppOverrides,
    onIngressAppOverridesChange: controller.setIngressAppOverrides,
    requestBody: controller.requestBody,
    createVmError: (controller.createVm.error as Error) || null,
    created: controller.created,
  })

  const handleComplete = () => {
    if (controller.created) {
      navigate('/vms')
      return
    }
    controller.createVm.mutate()
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Create VM</h1>
      <StepWizard
        steps={steps}
        onComplete={handleComplete}
        canProceed={!controller.createVm.isPending}
      />
    </div>
  )
}
