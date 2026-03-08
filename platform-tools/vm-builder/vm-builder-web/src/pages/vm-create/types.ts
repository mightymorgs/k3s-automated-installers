import { InventoryMount } from '../../api/client'
import { GcpConfig } from '../../components/GcpConfigPanel'

export interface VmNameParts {
  [key: string]: string
  client: string
  vmtype: string
  subtype: string
  state: string
  purpose: string
  platform: string
  version: string
}

export interface VmCreatePayloadArgs {
  fullName: string
  selectedSize: string
  platform: string
  selectedApps: string[]
  ingressMode: string
  selectedHypervisor: string
  nonEmptyConfigs: Record<string, Record<string, string | number | boolean>>
  ingressDomain: string
  ssoOverrides: Record<string, boolean>
  ingressAppOverrides: Record<string, string>
  isGcp: boolean
  gcpConfig: GcpConfig
  selectedMounts: InventoryMount[]
  hypervisorLocation: string
  appPaths: Record<string, { share_id: string; path: string }>
}
