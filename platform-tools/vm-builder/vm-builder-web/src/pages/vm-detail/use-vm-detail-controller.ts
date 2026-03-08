import { useCallback, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { api } from '../../api/client'

export function useVmDetailController() {
  const { name } = useParams<{ name: string }>()
  const queryClient = useQueryClient()

  const vm = useQuery({
    queryKey: ['vm', name],
    queryFn: () => api.getVm(name!),
    enabled: !!name,
  })

  const isK3sMaster = vm.data?.k3s?.role === 'server'
  const hasToken = vm.data?.k3s?.cluster_token && vm.data.k3s.cluster_token.length > 0

  const workers = useQuery({
    queryKey: ['workers', name],
    queryFn: () => api.listWorkers(name!),
    enabled: !!name && isK3sMaster,
  })

  const [showInstallPanel, setShowInstallPanel] = useState(false)

  const installedApps = useQuery({
    queryKey: ['installed-apps', name],
    queryFn: () => api.listInstalledApps(name!),
    enabled: !!name,
  })

  const installedAppIds = (installedApps.data || []).map((app: any) => app.app_id)

  const resourceDefaults = useQuery({
    queryKey: ['resource-defaults'],
    queryFn: api.getResourceDefaults,
  })

  const allAppsQuery = useQuery({
    queryKey: ['apps'],
    queryFn: () => api.listApps(),
  })

  const persistToken = useMutation({
    mutationFn: () => api.persistToken(name!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vm', name] })
    },
  })

  const [editMode, setEditMode] = useState(false)
  const [editedSections, setEditedSections] = useState<Record<string, Record<string, unknown>>>({})
  const [showDiff, setShowDiff] = useState(false)
  const [showDeployBanner, setShowDeployBanner] = useState(false)

  const saveMutation = useMutation({
    mutationFn: (body: any) => api.updateVm(name!, body),
    onSuccess: (data) => {
      setShowDiff(false)
      setEditMode(false)
      setEditedSections({})
      queryClient.invalidateQueries({ queryKey: ['vm', name] })

      const changedSections = new Set(
        Object.keys(data.changes || {}).map((key: string) => key.split('.')[0])
      )
      const needsDeploy = ['hardware', 'network', 'provider', 'apps'].some((section) =>
        changedSections.has(section)
      )
      if (needsDeploy) {
        setShowDeployBanner(true)
      }
    },
  })

  const deployMutation = useMutation({
    mutationFn: () => api.deployVm(name!),
    onSuccess: () => {
      setShowDeployBanner(false)
      queryClient.invalidateQueries({ queryKey: ['vm', name] })
    },
  })

  const installAppsMutation = useMutation({
    mutationFn: () => api.installAllApps(name!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vm', name] })
      queryClient.invalidateQueries({ queryKey: ['installed-apps', name] })
    },
  })

  const configureAppsMutation = useMutation({
    mutationFn: () => api.configureAllApps(name!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vm', name] })
    },
  })

  const ingressSsoMutation = useMutation({
    mutationFn: () => api.deployIngressSso(name!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vm', name] })
    },
  })

  const destroyMutation = useMutation({
    mutationFn: () => api.destroyVm(name!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vm', name] })
      queryClient.invalidateQueries({ queryKey: ['vms'] })
    },
  })

  const uninstallMutation = useMutation({
    mutationFn: (appId: string) => api.uninstallApp(name!, appId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vm', name] })
      queryClient.invalidateQueries({ queryKey: ['installed-apps', name] })
    },
  })

  const reinstallMutation = useMutation({
    mutationFn: (appId: string) => api.reinstallApp(name!, appId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vm', name] })
      queryClient.invalidateQueries({ queryKey: ['installed-apps', name] })
    },
  })

  const configureAppMutation = useMutation({
    mutationFn: (appId: string) => api.configureApp(name!, appId, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vm', name] })
      queryClient.invalidateQueries({ queryKey: ['installed-apps', name] })
    },
  })

  const onFieldChange = useCallback((section: string, field: string, value: unknown) => {
    setEditedSections((prev) => ({
      ...prev,
      [section]: { ...prev[section], [field]: value },
    }))
  }, [])

  const computedChanges = useMemo(() => {
    if (!vm.data) {
      return {}
    }

    const changes: Record<string, { old: unknown; new: unknown }> = {}

    for (const [section, fields] of Object.entries(editedSections)) {
      const originalSection = vm.data[section] || {}
      for (const [field, newValue] of Object.entries(fields as Record<string, unknown>)) {
        const oldValue = originalSection[field]
        if (JSON.stringify(oldValue) !== JSON.stringify(newValue)) {
          changes[`${section}.${field}`] = { old: oldValue, new: newValue }
        }
      }
    }

    return changes
  }, [editedSections, vm.data])

  const buildUpdateBody = useCallback(() => {
    const body: Record<string, Record<string, unknown>> = {}

    if (!vm.data) {
      return body
    }

    for (const [section, fields] of Object.entries(editedSections)) {
      const originalSection = vm.data[section] || {}
      const changedFields: Record<string, unknown> = {}
      let hasChanges = false

      for (const [field, newValue] of Object.entries(fields as Record<string, unknown>)) {
        if (JSON.stringify(originalSection[field]) !== JSON.stringify(newValue)) {
          changedFields[field] = newValue
          hasChanges = true
        }
      }

      if (hasChanges) {
        body[section] = changedFields
      }
    }

    return body
  }, [editedSections, vm.data])

  const handleEdit = () => {
    setEditMode(true)
    setEditedSections({})
    setShowDeployBanner(false)
  }

  const handleRevert = () => {
    setEditedSections({})
    queryClient.invalidateQueries({ queryKey: ['vm', name] })
  }

  const handleCancel = () => {
    setEditMode(false)
    setEditedSections({})
  }

  const handleSave = () => {
    setShowDiff(true)
  }

  const handleConfirmSave = () => {
    const body = buildUpdateBody()
    saveMutation.mutate(body)
  }

  const handleAppChange = useCallback(
    (apps: string[]) => {
      onFieldChange('apps', 'selected_apps', apps)
    },
    [onFieldChange]
  )

  const hasChanges = Object.keys(computedChanges).length > 0

  return {
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
  }
}
