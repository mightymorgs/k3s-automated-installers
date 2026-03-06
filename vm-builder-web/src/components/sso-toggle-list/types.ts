export interface SsoToggleListProps {
  selectedApps: string[]
  ssoOverrides: Record<string, boolean>
  onOverridesChange: (overrides: Record<string, boolean>) => void
  ingressMode: string
}

export interface RegistryApp {
  id: string
  name: string
  display_name?: string
  ingress?: { enabled: boolean; subdomain: string; service_port: number }
  sso?: { enabled: boolean; bypass_paths?: string[] }
}

export interface SsoToggleRowProps {
  app: RegistryApp
  active: boolean
  expanded: boolean
  onToggle: (appId: string) => void
  onToggleExpanded: (appId: string) => void
}
