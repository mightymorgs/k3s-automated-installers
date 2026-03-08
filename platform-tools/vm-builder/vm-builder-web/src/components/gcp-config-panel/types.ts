export interface GcpConfig {
  machine_type: string
  boot_disk_size_gb: number
  boot_disk_type: string
  data_disk_size_gb: number
  data_disk_type: string
  region: string
  zone: string
  network_name: string
  subnet_name: string
  enable_external_ip: boolean
  enable_static_ip: boolean
}

export interface GcpConfigPanelProps {
  presets: Record<string, any>
  config: GcpConfig
  onChange: (config: GcpConfig) => void
}
