import { VmCreatePayloadArgs, VmNameParts } from './types'

export function buildVmName(parts: VmNameParts): string {
  return [
    parts.client,
    parts.vmtype,
    parts.subtype,
    parts.state,
    parts.purpose,
    parts.platform,
    parts.version,
  ].join('-')
}

export function normalizeNonEmptyConfigs(
  appConfigs: Record<string, Record<string, string | number | boolean>>
): Record<string, Record<string, string | number | boolean>> {
  return Object.fromEntries(
    Object.entries(appConfigs)
      .map(([appId, fields]) => [
        appId,
        Object.fromEntries(
          Object.entries(fields).filter(([, value]) => value !== '' && value !== undefined)
        ),
      ])
      .filter(([, fields]) => Object.keys(fields as object).length > 0)
  )
}

export function buildVmCreatePayload(args: VmCreatePayloadArgs): Record<string, any> {
  const payload: Record<string, any> = {
    vm_name: args.fullName,
    size: args.isGcp ? args.gcpConfig.machine_type : args.selectedSize,
    platform: args.platform,
    apps: args.selectedApps,
    ingress_mode: args.ingressMode,
  }

  if (args.selectedHypervisor) {
    payload.hypervisor = args.selectedHypervisor
  }

  if (Object.keys(args.nonEmptyConfigs).length > 0) {
    payload.app_configs = args.nonEmptyConfigs
  }

  const needsDomain = args.ingressMode === 'cloudflare' || Object.values(args.ingressAppOverrides).includes('cloudflare')
  if (needsDomain && args.ingressDomain) {
    payload.ingress_domain = args.ingressDomain
  }

  if (Object.keys(args.ssoOverrides).length > 0 && args.ingressMode !== 'nodeport') {
    payload.sso_overrides = args.ssoOverrides
  }

  if (Object.keys(args.ingressAppOverrides).length > 0) {
    payload.ingress_app_overrides = args.ingressAppOverrides
  }

  if (args.isGcp) {
    payload.gcp = {
      machine_type: args.gcpConfig.machine_type,
      boot_disk_size_gb: args.gcpConfig.boot_disk_size_gb,
      boot_disk_type: args.gcpConfig.boot_disk_type,
      data_disk_size_gb: args.gcpConfig.data_disk_size_gb,
      data_disk_type: args.gcpConfig.data_disk_type,
      region: args.gcpConfig.region,
      zone: args.gcpConfig.zone,
      network_name: args.gcpConfig.network_name,
      subnet_name: args.gcpConfig.subnet_name,
      enable_external_ip: args.gcpConfig.enable_external_ip,
      enable_static_ip: args.gcpConfig.enable_static_ip,
    }
  }

  if (args.selectedMounts.length > 0) {
    payload.storage_location = args.hypervisorLocation
    payload.storage_mounts = args.selectedMounts
  }

  if (Object.keys(args.appPaths).length > 0) {
    payload.storage_app_paths = args.appPaths
  }

  return payload
}
