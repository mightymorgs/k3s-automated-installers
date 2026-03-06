import { GcpConfig } from './types'

export const DEFAULT_GCP_CONFIG: GcpConfig = {
  machine_type: 'e2-medium',
  boot_disk_size_gb: 30,
  boot_disk_type: 'pd-balanced',
  data_disk_size_gb: 0,
  data_disk_type: 'pd-balanced',
  region: 'us-central1',
  zone: 'us-central1-a',
  network_name: 'default',
  subnet_name: 'default',
  enable_external_ip: true,
  enable_static_ip: false,
}

export const DISK_TYPE_OPTIONS = [
  { value: 'pd-balanced', label: 'Balanced (pd-balanced)' },
  { value: 'pd-ssd', label: 'SSD (pd-ssd)' },
  { value: 'pd-standard', label: 'Standard (pd-standard)' },
]

export const REGION_OPTIONS = [
  'us-central1',
  'us-east1',
  'us-west1',
  'europe-west1',
  'asia-east1',
]

export const ZONE_SUFFIXES = ['a', 'b', 'c']
