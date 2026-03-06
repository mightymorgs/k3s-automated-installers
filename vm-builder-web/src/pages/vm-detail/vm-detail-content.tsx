import EditableSection from '../../components/EditableSection'
import IngressStatusTable from '../../components/IngressStatusTable'
import { InventoryMount } from '../../api/client'
import ApplicationsSection from './applications-section'
import ClusterSection from './cluster-section'
import { SECTION_ORDER } from './constants'
import DangerZoneSection from './danger-zone-section'
import ResourceUtilizationCard from './resource-utilization-card'
import StorageSection from './storage-section'

type VmDetailContentProps = {
  name: string
  vm: any
  editMode: boolean
  editedSections: Record<string, any>
  onFieldChange: (section: string, field: string, value: unknown) => void
  handleAppChange: (apps: string[]) => void
  uninstallMutation: any
  reinstallMutation: any
  configureAppMutation: any
  destroyMutation: any
  setShowInstallPanel: (open: boolean) => void
  installedApps: any
  allAppsQuery: any
  resourceDefaults: any
  isK3sMaster: boolean
  hasToken: boolean
  workers: any
  persistToken: any
  onNavigateIngress: () => void
}

export default function VmDetailContent({
  name,
  vm,
  editMode,
  editedSections,
  onFieldChange,
  handleAppChange,
  uninstallMutation,
  reinstallMutation,
  configureAppMutation,
  destroyMutation,
  setShowInstallPanel,
  installedApps,
  allAppsQuery,
  resourceDefaults,
  isK3sMaster,
  hasToken,
  workers,
  persistToken,
  onNavigateIngress,
}: VmDetailContentProps) {
  if (vm.isLoading) {
    return <p className="text-gray-500">Loading VM details...</p>
  }

  if (vm.error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-md p-4">
        <p className="text-sm text-red-700">Failed to load VM: {(vm.error as Error).message}</p>
      </div>
    )
  }

  if (!vm.data) {
    return null
  }

  return (
    <div className="space-y-4">
      {vm.data.schema_version && <p className="text-xs text-gray-400">Schema: {vm.data.schema_version}</p>}

      {SECTION_ORDER.map((section) => {
        const data = vm.data[section]
        if (!data || typeof data !== 'object') {
          return null
        }

        if (section === 'storage') {
          const storageData = data as Record<string, unknown>
          return (
            <StorageSection
              key={section}
              editMode={editMode}
              location={(storageData.location as string) || ''}
              mounts={(storageData.mounts as InventoryMount[]) || []}
              appPaths={(storageData.app_paths as Record<string, unknown>) || {}}
              onMountsChange={(mounts) => onFieldChange('storage', 'mounts', mounts)}
            />
          )
        }

        if (section === 'apps') {
          const currentApps =
            (editedSections.apps?.selected_apps as string[]) ?? data.selected_apps ?? []

          return (
            <ApplicationsSection
              key={section}
              vmName={name}
              editMode={editMode}
              installedAppsLoading={installedApps.isLoading}
              installedAppsData={installedApps.data}
              currentApps={currentApps}
              hypervisorName={data?.provider?.hypervisor}
              onAppChange={handleAppChange}
              onOpenInstallPanel={() => setShowInstallPanel(true)}
              onUninstall={(appId) => uninstallMutation.mutate(appId)}
              onReinstall={(appId) => reinstallMutation.mutate(appId)}
              onConfigure={(appId) => configureAppMutation.mutate(appId)}
            />
          )
        }

        return (
          <EditableSection
            key={section}
            section={section}
            data={data as Record<string, unknown>}
            editMode={editMode}
            editedData={editedSections[section] || {}}
            onFieldChange={onFieldChange}
          />
        )
      })}

      {vm.data.ingress && vm.data.ingress.mode !== 'nodeport' && (
        <IngressStatusTable inventory={vm.data} apps={allAppsQuery.data || []} />
      )}

      {vm.data.ingress && (
        <div>
          <button
            onClick={onNavigateIngress}
            className="text-sm text-blue-600 hover:text-blue-800 underline"
          >
            Reconfigure Ingress
          </button>
        </div>
      )}

      {resourceDefaults.data && allAppsQuery.data && (
        <ResourceUtilizationCard
          inventory={vm.data}
          allApps={allAppsQuery.data}
          resourceDefaults={resourceDefaults.data}
        />
      )}

      {Object.keys(vm.data)
        .filter((section) => !SECTION_ORDER.includes(section) && section !== 'schema_version')
        .map((section) => {
          const data = vm.data[section]
          if (!data || typeof data !== 'object') {
            return null
          }

          return (
            <EditableSection
              key={section}
              section={section}
              data={data as Record<string, unknown>}
              editMode={editMode}
              editedData={editedSections[section] || {}}
              onFieldChange={onFieldChange}
            />
          )
        })}

      {isK3sMaster && (
        <ClusterSection
          vmName={name}
          hasToken={hasToken}
          workersLoading={workers.isLoading}
          workers={workers.data}
          persistTokenPending={persistToken.isPending}
          persistTokenError={(persistToken.error as Error) || null}
          persistTokenSuccess={persistToken.isSuccess}
          onPersistToken={() => persistToken.mutate()}
        />
      )}

      <DangerZoneSection
        vmName={name}
        isK3sMaster={isK3sMaster}
        workers={workers.data}
        vmRole={vm.data?.k3s?.role}
        onDestroy={() => destroyMutation.mutate()}
        destroyPending={destroyMutation.isPending}
      />
    </div>
  )
}
