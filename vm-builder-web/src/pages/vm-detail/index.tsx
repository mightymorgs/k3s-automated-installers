import { Link, useNavigate } from 'react-router-dom'
import AppInstallPanel from '../../components/AppInstallPanel'
import DiffModal from '../../components/DiffModal'
import PhaseActionsSection from './phase-actions-section'
import VmDetailContent from './vm-detail-content'
import { useVmDetailController } from './use-vm-detail-controller'

export default function VmDetailPage() {
  const navigate = useNavigate()
  const {
    name,
    vm,
    isK3sMaster,
    hasToken,
    workers,
    showInstallPanel,
    setShowInstallPanel,
    installedApps,
    installedAppIds,
    resourceDefaults,
    allAppsQuery,
    persistToken,
    editMode,
    editedSections,
    showDiff,
    setShowDiff,
    showDeployBanner,
    setShowDeployBanner,
    saveMutation,
    deployMutation,
    installAppsMutation,
    configureAppsMutation,
    ingressSsoMutation,
    destroyMutation,
    uninstallMutation,
    reinstallMutation,
    configureAppMutation,
    onFieldChange,
    computedChanges,
    handleEdit,
    handleRevert,
    handleCancel,
    handleSave,
    handleConfirmSave,
    handleAppChange,
    hasChanges,
  } = useVmDetailController()

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Link to="/vms" className="text-sm text-blue-600 hover:text-blue-800">
            &larr; VMs
          </Link>
          <h1 className="text-2xl font-bold">{name}</h1>
        </div>
        <div className="flex items-center gap-2">
          {!editMode ? (
            <button
              onClick={handleEdit}
              disabled={!vm.data}
              className="px-4 py-2 text-sm text-white bg-blue-600 rounded hover:bg-blue-700 disabled:opacity-50"
            >
              Edit
            </button>
          ) : (
            <>
              <button
                onClick={handleRevert}
                disabled={!hasChanges}
                className="px-4 py-2 text-sm text-gray-700 border rounded hover:bg-gray-50 disabled:opacity-50"
              >
                Revert
              </button>
              <button
                onClick={handleCancel}
                className="px-4 py-2 text-sm text-gray-700 border rounded hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={!hasChanges}
                className="px-4 py-2 text-sm text-white bg-green-600 rounded hover:bg-green-700 disabled:opacity-50"
              >
                Save
              </button>
            </>
          )}
        </div>
      </div>

      {showDeployBanner && (
        <div className="mb-4 bg-yellow-50 border border-yellow-200 rounded-md p-4 flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-yellow-800">
              Changes saved. Some changes require re-deployment to take effect.
            </p>
            <p className="text-xs text-yellow-600 mt-1">
              Hardware, network, and provider changes need a full re-deploy.
            </p>
          </div>
          <button
            onClick={() => setShowDeployBanner(false)}
            className="text-xs text-yellow-600 hover:text-yellow-800 underline ml-4"
          >
            Dismiss
          </button>
        </div>
      )}

      {saveMutation.error && (
        <div className="mb-4 bg-red-50 border border-red-200 rounded-md p-4">
          <p className="text-sm text-red-700">
            Failed to save: {(saveMutation.error as Error).message}
          </p>
        </div>
      )}

      {destroyMutation.error && (
        <div className="mb-4 bg-red-50 border border-red-200 rounded-md p-4">
          <p className="text-sm text-red-700">
            Failed to destroy: {(destroyMutation.error as Error).message}
          </p>
        </div>
      )}

      <div className="mb-4">
        <PhaseActionsSection
          deployMutation={deployMutation}
          installAppsMutation={installAppsMutation}
          configureAppsMutation={configureAppsMutation}
          ingressSsoMutation={ingressSsoMutation}
        />
      </div>

      <VmDetailContent
        name={name || ''}
        vm={vm}
        editMode={editMode}
        editedSections={editedSections}
        onFieldChange={onFieldChange}
        handleAppChange={handleAppChange}
        uninstallMutation={uninstallMutation}
        reinstallMutation={reinstallMutation}
        configureAppMutation={configureAppMutation}
        destroyMutation={destroyMutation}
        setShowInstallPanel={setShowInstallPanel}
        installedApps={installedApps}
        allAppsQuery={allAppsQuery}
        resourceDefaults={resourceDefaults}
        isK3sMaster={isK3sMaster}
        hasToken={!!hasToken}
        workers={workers}
        persistToken={persistToken}
        onNavigateIngress={() => navigate(`/vm/${name}/ingress`)}
      />

      <AppInstallPanel
        vmName={name || ''}
        installedApps={installedAppIds}
        isOpen={showInstallPanel}
        onClose={() => setShowInstallPanel(false)}
      />

      {showDiff && (
        <DiffModal
          changes={computedChanges}
          onConfirm={handleConfirmSave}
          onCancel={() => setShowDiff(false)}
          isSaving={saveMutation.isPending}
        />
      )}
    </div>
  )
}
