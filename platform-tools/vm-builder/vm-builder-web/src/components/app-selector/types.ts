import { InventoryMount } from '../../api/client'

export interface AppConfig {
  [fieldName: string]: string | number | boolean
}

export interface AppSelectorProps {
  selected: string[]
  onChange: (apps: string[]) => void
  appConfigs?: Record<string, AppConfig>
  onConfigChange?: (configs: Record<string, AppConfig>) => void
  disabledApps?: string[]
  hypervisorName?: string
  selectedMounts?: InventoryMount[]
}

export interface RegistryApp {
  id?: string
  name?: string
  display_name?: string
  description?: string
  category?: string
  variables?: Record<string, any>
}
