"""Shared schema constants and resource preset tables."""

from __future__ import annotations

SIZE_PRESETS = {
    "small": {
        "vcpu": 2,
        "memory_mb": 4096,
        "disk_size_gb": 40,
        "data_disk_size_gb": 0,
    },
    "medium": {
        "vcpu": 4,
        "memory_mb": 8192,
        "disk_size_gb": 80,
        "data_disk_size_gb": 0,
    },
    "large": {
        "vcpu": 12,
        "memory_mb": 24576,
        "disk_size_gb": 120,
        "data_disk_size_gb": 200,
    },
    "gpu": {
        "vcpu": 12,
        "memory_mb": 24576,
        "disk_size_gb": 120,
        "data_disk_size_gb": 200,
        "enable_gpu_passthrough": True,
    },
}

GCP_SIZE_PRESETS = {
    "e2-micro": {
        "machine_type": "e2-micro",
        "description": "Shared-core, 0.25-2 vCPU, 1 GB",
        "vcpu": "0.25-2 (shared)",
        "memory_gb": 1,
        "cost_estimate": "Always free tier eligible",
        "boot_disk_size_gb": 20,
        "boot_disk_type": "pd-balanced",
    },
    "e2-small": {
        "machine_type": "e2-small",
        "description": "Shared-core, 0.5-2 vCPU, 2 GB",
        "vcpu": "0.5-2 (shared)",
        "memory_gb": 2,
        "cost_estimate": "~$12/mo",
        "boot_disk_size_gb": 20,
        "boot_disk_type": "pd-balanced",
    },
    "e2-medium": {
        "machine_type": "e2-medium",
        "description": "Shared-core, 1-2 vCPU, 4 GB — Recommended",
        "vcpu": "1-2 (shared)",
        "memory_gb": 4,
        "cost_estimate": "~$24/mo",
        "boot_disk_size_gb": 30,
        "boot_disk_type": "pd-balanced",
    },
    "e2-standard-2": {
        "machine_type": "e2-standard-2",
        "description": "2 vCPU, 8 GB",
        "vcpu": 2,
        "memory_gb": 8,
        "cost_estimate": "~$49/mo",
        "boot_disk_size_gb": 30,
        "boot_disk_type": "pd-balanced",
    },
    "e2-standard-4": {
        "machine_type": "e2-standard-4",
        "description": "4 vCPU, 16 GB",
        "vcpu": 4,
        "memory_gb": 16,
        "cost_estimate": "~$98/mo",
        "boot_disk_size_gb": 50,
        "boot_disk_type": "pd-balanced",
    },
}

K3S_OVERHEAD_CPU_MILLICORES = 500
K3S_OVERHEAD_MEMORY_MB = 512

RESOURCE_DEFAULTS = {
    "security": {
        "min_cpu_millicores": 500,
        "min_memory_mb": 512,
        "recommended_cpu_millicores": 1000,
        "recommended_memory_mb": 1024,
    },
    "storage": {
        "min_cpu_millicores": 250,
        "min_memory_mb": 256,
        "recommended_cpu_millicores": 500,
        "recommended_memory_mb": 512,
    },
    "observability": {
        "min_cpu_millicores": 250,
        "min_memory_mb": 256,
        "recommended_cpu_millicores": 500,
        "recommended_memory_mb": 512,
    },
    "media": {
        "min_cpu_millicores": 500,
        "min_memory_mb": 512,
        "recommended_cpu_millicores": 1000,
        "recommended_memory_mb": 1024,
    },
    "infrastructure": {
        "min_cpu_millicores": 250,
        "min_memory_mb": 256,
        "recommended_cpu_millicores": 500,
        "recommended_memory_mb": 512,
    },
    "_default": {
        "min_cpu_millicores": 250,
        "min_memory_mb": 256,
        "recommended_cpu_millicores": 500,
        "recommended_memory_mb": 512,
    },
}
