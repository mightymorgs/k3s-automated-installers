import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, InventoryMount } from '../../api/client'
import { DEFAULT_GCP_CONFIG, GcpConfig } from '../../components/GcpConfigPanel'
import { buildVmCreatePayload, buildVmName, normalizeNonEmptyConfigs } from './payload'
import { VmNameParts } from './types'

function initialNameParts(masterName: string | null): VmNameParts {
  if (masterName) {
    const parts = masterName.split('-')
    if (parts.length === 7) {
      return {
        client: parts[0],
        vmtype: 'k3s',
        subtype: 'worker',
        state: parts[3],
        purpose: parts[4],
        platform: parts[5],
        version: parts[6],
      }
    }
  }

  return {
    client: 'homelab',
    vmtype: '',
    subtype: '',
    state: '',
    purpose: '',
    platform: '',
    version: 'latest',
  }
}

export function useVmCreateController() {
  const [searchParams] = useSearchParams()
  const masterName = searchParams.get('master')

  const [nameParts, setNameParts] = useState<VmNameParts>(() => initialNameParts(masterName))
  const [selectedHypervisor, setSelectedHypervisor] = useState<string>('')
  const [selectedSize, setSelectedSize] = useState<string>('')
  const [selectedMounts, setSelectedMounts] = useState<InventoryMount[]>([])
  const [appPaths] = useState<Record<string, { share_id: string; path: string }>>({})
  const [selectedApps, setSelectedApps] = useState<string[]>([])
  const [appConfigs, setAppConfigs] = useState<Record<string, Record<string, string | number | boolean>>>({})
  const [ingressMode, setIngressMode] = useState<string>('nodeport')
  const [ingressDomain, setIngressDomain] = useState<string>('')
  const [ssoOverrides, setSsoOverrides] = useState<Record<string, boolean>>({})
  const [ingressAppOverrides, setIngressAppOverrides] = useState<Record<string, string>>({})
  const [ingressValid, setIngressValid] = useState<boolean>(true)
  const [tailnet, setTailnet] = useState<string>('')
  const [gcpConfig, setGcpConfig] = useState<GcpConfig>(DEFAULT_GCP_CONFIG)
  const [created, setCreated] = useState(false)

  const platform = nameParts.platform || 'libvirt'
  const isGcp = platform === 'gcp'

  const sizes = useQuery({
    queryKey: ['sizes', platform],
    queryFn: () => api.getSizes(platform),
  })

  const hypervisors = useQuery({
    queryKey: ['hypervisors'],
    queryFn: () => api.listHypervisors(),
  })

  const resourceDefaults = useQuery({
    queryKey: ['resource-defaults'],
    queryFn: api.getResourceDefaults,
  })

  const allApps = useQuery({
    queryKey: ['apps'],
    queryFn: () => api.listApps(),
  })

  const fullName = buildVmName(nameParts)
  const filteredHypervisors = (hypervisors.data || []).filter(
    (hypervisor: any) => !nameParts.platform || hypervisor.platform === nameParts.platform
  )
  const selectedHvData = (hypervisors.data || []).find(
    (hypervisor: any) => hypervisor.name === selectedHypervisor
  )
  const hypervisorLocation = selectedHvData?.location || ''

  const selectedAppData = (allApps.data || []).filter((app: any) =>
    selectedApps.includes(app.id || app.name)
  )
  const currentHardware = selectedSize && sizes.data ? sizes.data[selectedSize] : null

  const k3sOverhead = resourceDefaults.data?.k3s_overhead || {
    cpu_millicores: 500,
    memory_mb: 512,
  }
  const defaults = resourceDefaults.data || {
    _default: {
      min_cpu_millicores: 250,
      min_memory_mb: 256,
      recommended_cpu_millicores: 500,
      recommended_memory_mb: 512,
    },
  }

  const nonEmptyConfigs = normalizeNonEmptyConfigs(appConfigs)

  const createVm = useMutation({
    mutationFn: () => {
      if (masterName) {
        return api.createWorker(masterName, {
          size: selectedSize,
          apps: selectedApps.length > 0 ? selectedApps : undefined,
        })
      }

      return api.createVm(
        buildVmCreatePayload({
          fullName,
          selectedSize,
          platform: nameParts.platform,
          selectedApps,
          ingressMode,
          selectedHypervisor,
          nonEmptyConfigs,
          ingressDomain,
          ssoOverrides,
          ingressAppOverrides,
          isGcp,
          gcpConfig,
          selectedMounts,
          hypervisorLocation,
          appPaths,
        })
      )
    },
    onSuccess: () => {
      setCreated(true)
    },
  })

  const requestBody = buildVmCreatePayload({
    fullName,
    selectedSize,
    platform: nameParts.platform,
    selectedApps,
    ingressMode,
    selectedHypervisor,
    nonEmptyConfigs,
    ingressDomain,
    ssoOverrides,
    ingressAppOverrides,
    isGcp,
    gcpConfig,
    selectedMounts,
    hypervisorLocation,
    appPaths,
  })

  return {
    masterName,
    nameParts,
    setNameParts,
    selectedHypervisor,
    setSelectedHypervisor,
    selectedSize,
    setSelectedSize,
    selectedMounts,
    setSelectedMounts,
    selectedApps,
    setSelectedApps,
    appConfigs,
    setAppConfigs,
    ingressMode,
    setIngressMode,
    ingressDomain,
    setIngressDomain,
    ingressValid,
    setIngressValid,
    tailnet,
    setTailnet,
    ssoOverrides,
    setSsoOverrides,
    ingressAppOverrides,
    setIngressAppOverrides,
    gcpConfig,
    setGcpConfig,
    created,
    platform,
    isGcp,
    sizes,
    hypervisors,
    resourceDefaults,
    filteredHypervisors,
    selectedSizeData: currentHardware,
    selectedHypervisorData: selectedHvData,
    hypervisorLocation,
    selectedAppData,
    k3sOverhead,
    defaults,
    createVm,
    requestBody,
  }
}
