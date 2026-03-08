import { ApiError } from './errors'

export interface StorageMount {
  mount_type: 'nfs' | 'smb'
  source: string
  mount_point: string
  options: string | null
}

export interface StorageBrowseResult {
  hypervisor_name: string
  path: string
  entries: { name: string; entry_type: string }[]
}

export interface StorageVerifyRequest {
  hypervisor_name: string
  mount_type: 'nfs' | 'smb'
  source: string
  credentials?: { username: string; password: string }
}

export interface StorageVerifyResult {
  accessible: boolean
  mount_type: string
  source: string
  mount_point: string | null
  error: string | null
  contents: string[]
}

export interface NetworkShare {
  id: string
  name: string
  mount_type: 'nfs' | 'smb'
  source: string
  mount_point: string
  discovered_from?: string
  verified_at?: string
}

export interface NetworkSharesConfig {
  location: string
  shares: NetworkShare[]
}

export interface InventoryMount {
  share_id: string
  mount_type: 'nfs' | 'smb'
  source: string
  mount_point: string
}

export interface AppConfigField {
  value: any
  default: any
  field_def: any
  is_override: boolean
}

export interface AppConfigResponse {
  app_id: string
  fields: Record<string, AppConfigField>
}

export interface ConfigUpdateResult {
  vm_name: string
  app_id: string
  field: string
  value: any
  updated: boolean
  workflow_triggered?: boolean
  workflow?: string
  error?: string
}

export interface WorkflowTriggerResult {
  app_id: string
  status: string
  run_url?: string
}

export interface ConfigDiffEntry {
  file: string
  diff: string
  has_changes: boolean
  rendered_preview: string
}

export interface ConfigPreviewResult {
  app_id: string
  vm_name: string
  diffs: ConfigDiffEntry[]
  has_changes: boolean
  warnings?: string[]
  summary: string
}

export interface ConfigApplyFileResult {
  file: string
  success: boolean
  output: string
  error: string
}

export interface ConfigApplyResult {
  app_id: string
  vm_name: string
  hostname: string
  namespace: string
  dry_run: boolean
  results: ConfigApplyFileResult[]
  success: boolean
  warnings?: string[]
  summary: string
}

const BASE = '/api/v1'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    if (body.error) {
      throw new ApiError(body.error)
    }
    throw new ApiError({
      code: 'UNKNOWN_ERROR',
      message: body.detail || res.statusText,
      category: 'internal',
    })
  }
  return res.json()
}

export const api = {
  health: () => request<any>('/health'),
  initStatus: () => request<any>('/init/status'),
  initSecrets: (body: any) =>
    request<any>('/init/secrets', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  listVms: (client?: string) =>
    request<any[]>(`/vms${client ? `?client=${client}` : ''}`),
  getVm: (name: string) => request<any>(`/vms/${name}`),
  createVm: (body: any) =>
    request<any>('/vms', { method: 'POST', body: JSON.stringify(body) }),
  deleteVm: (name: string) =>
    request<any>(`/vms/${name}`, { method: 'DELETE' }),
  updateVm: (name: string, body: any) =>
    request<any>(`/vms/${name}`, { method: 'PUT', body: JSON.stringify(body) }),
  regenerateKeypair: (name: string) =>
    request<any>(`/vms/${name}/regenerate-keypair`, { method: 'POST' }),
  deployVm: (name: string) =>
    request<any>(`/vms/${name}/deploy`, { method: 'POST' }),
  installAllApps: (name: string) =>
    request<any>(`/vms/${name}/phase/install-apps`, { method: 'POST' }),
  configureAllApps: (name: string) =>
    request<any>(`/vms/${name}/phase/configure-apps`, { method: 'POST' }),
  deployIngressSso: (name: string) =>
    request<any>(`/vms/${name}/phase/ingress-sso`, { method: 'POST' }),
  listInstalledApps: (vmName: string) =>
    request<any[]>(`/vms/${vmName}/apps`),
  installApps: (vmName: string, body: { apps: string[]; app_configs?: Record<string, any> }) =>
    request<any>(`/vms/${vmName}/apps`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  uninstallApp: (vmName: string, appId: string) =>
    request<any>(`/vms/${vmName}/apps/${appId}`, { method: 'DELETE' }),
  listWorkers: (masterName: string) =>
    request<any[]>(`/vms/${masterName}/workers`),
  createWorker: (masterName: string, body: { size: string; apps?: string[] }) =>
    request<any>(`/vms/${masterName}/workers`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  persistToken: (masterName: string) =>
    request<any>(`/vms/${masterName}/persist-token`, { method: 'POST' }),
  destroyVm: (name: string) =>
    request<any>(`/vms/${name}/destroy`, { method: 'POST' }),
  vmHealth: (client?: string) =>
    request<any[]>(`/vms/health${client ? `?client=${client}` : ''}`),
  listApps: (category?: string) =>
    request<any[]>(
      `/registry/apps${category ? `?category=${category}` : ''}`
    ),
  getApp: (id: string) => request<any>(`/registry/apps/${id}`),
  resolveDeps: (apps: string[]) =>
    request<any>('/registry/resolve-deps', {
      method: 'POST',
      body: JSON.stringify({ selected_apps: apps }),
    }),
  getSizes: (platform?: string) =>
    request<any>(`/schema/sizes${platform ? `?platform=${platform}` : ''}`),
  getResourceDefaults: () => request<any>('/schema/resource-defaults'),
  getPlatforms: () => request<any>('/schema/platforms'),
  validateName: (name: string) =>
    request<any>('/schema/validate-name', {
      method: 'POST',
      body: JSON.stringify({ vm_name: name }),
    }),
  refreshRegistry: () =>
    request<any>('/registry/refresh', { method: 'POST' }),
  installApp: (vmName: string, appId: string, skipDeps?: boolean) =>
    request<any>(
      `/vms/${vmName}/apps/${appId}/install${skipDeps ? '?skip_deps=true' : ''}`,
      { method: 'POST' }
    ),
  configureApp: (vmName: string, appId: string, config: Record<string, any>) =>
    request<any>(`/vms/${vmName}/apps/${appId}/configure`, {
      method: 'POST',
      body: JSON.stringify(config),
    }),
  checkInstallable: (appId: string, installed: string[]) =>
    request<any>(
      `/registry/apps/${appId}/installable?installed=${installed.join(',')}`
    ),

  validateIngress: (body: { mode: string; domain?: string }) =>
    request<{ valid: boolean; error?: string; warnings?: string[] }>(
      '/ingress/validate',
      { method: 'POST', body: JSON.stringify(body) },
    ),
  getTailnet: () => request<{ tailnet: string }>('/ingress/tailnet'),

  storageMounts: (hypervisorName: string) =>
    request<StorageMount[]>(
      `/storage/${encodeURIComponent(hypervisorName)}/mounts`
    ),

  storageBrowse: (
    hypervisorName: string,
    path: string,
    mount?: { source: string; mount_type: string; mount_point: string },
  ) => {
    const params = new URLSearchParams({ path })
    if (mount) {
      params.set('mount_source', mount.source)
      params.set('mount_type', mount.mount_type)
      params.set('mount_point', mount.mount_point)
    }
    return request<StorageBrowseResult>(
      `/storage/${encodeURIComponent(hypervisorName)}/browse?${params}`
    )
  },

  storageVerify: (data: StorageVerifyRequest) =>
    request<StorageVerifyResult>('/storage/verify', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  networkShares: (location: string) =>
    request<NetworkSharesConfig>(
      `/storage/network-shares/${encodeURIComponent(location)}`
    ),

  saveNetworkShares: (location: string, body: any) =>
    request<{ saved: boolean; location: string }>(
      `/storage/network-shares/${encodeURIComponent(location)}`,
      { method: 'PUT', body: JSON.stringify(body) },
    ),

  listHypervisors: () => request<any[]>('/hypervisors'),
  getHypervisor: (name: string) => request<any>(`/hypervisors/${name}`),
  bootstrapHypervisor: (config: any) =>
    fetch(`${BASE}/hypervisor/bootstrap`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    }),

  getAppConfig: (vmName: string, appId: string) =>
    request<AppConfigResponse>(`/vms/${vmName}/apps/${appId}/config`),

  updateAppConfig: (vmName: string, appId: string, field: string, value: any) =>
    request<ConfigUpdateResult>(`/vms/${vmName}/apps/${appId}/config`, {
      method: 'PATCH',
      body: JSON.stringify({ field, value }),
    }),

  resetAppConfig: (vmName: string, appId: string, field: string) =>
    request<void>(`/vms/${vmName}/apps/${appId}/config/${encodeURIComponent(field)}`, {
      method: 'DELETE',
    }),

  reinstallApp: (vmName: string, appId: string) =>
    request<WorkflowTriggerResult>(`/vms/${vmName}/apps/${appId}/reinstall`, {
      method: 'POST',
    }),

  previewConfigChanges: (vmName: string, appId: string) =>
    request<ConfigPreviewResult>(`/vms/${vmName}/apps/${appId}/preview`, {
      method: 'POST',
    }),

  applyConfigLive: (vmName: string, appId: string, dryRun = false) =>
    request<ConfigApplyResult>(
      `/vms/${vmName}/apps/${appId}/apply${dryRun ? '?dry_run=true' : ''}`,
      { method: 'POST' },
    ),
}

export { ApiError } from './errors'
