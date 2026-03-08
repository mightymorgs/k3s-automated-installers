"""Convert Helm Deployment resources to StatefulSets."""

import copy
from typing import Optional


DEFAULT_STORAGE_SIZE = "5Gi"
DEFAULT_STORAGE_CLASS = "longhorn"


def convert_deployment_to_statefulset(
    doc: dict, service_name: str
) -> dict:
    """Convert a Deployment to a StatefulSet. Returns unchanged if not a Deployment."""
    if doc.get("kind") != "Deployment":
        return doc

    result = copy.deepcopy(doc)
    result["kind"] = "StatefulSet"
    result["apiVersion"] = "apps/v1"

    spec = result["spec"]
    spec["serviceName"] = service_name
    spec["podManagementPolicy"] = "Parallel"

    # Convert strategy -> updateStrategy
    if "strategy" in spec:
        strategy_type = spec.pop("strategy").get("type", "RollingUpdate")
        spec["updateStrategy"] = {"type": strategy_type}

    # Convert emptyDir volumes to volumeClaimTemplates
    pod_spec = spec["template"]["spec"]
    volumes = pod_spec.get("volumes", [])
    volume_mounts = []
    for container in pod_spec.get("containers", []):
        volume_mounts.extend(container.get("volumeMounts", []))

    vcts: list[dict] = []
    remaining_volumes: list[dict] = []
    for vol in volumes:
        if "emptyDir" in vol:
            vcts.append(
                {
                    "metadata": {"name": vol["name"]},
                    "spec": {
                        "accessModes": ["ReadWriteOnce"],
                        "storageClassName": DEFAULT_STORAGE_CLASS,
                        "resources": {
                            "requests": {"storage": DEFAULT_STORAGE_SIZE}
                        },
                    },
                }
            )
        else:
            remaining_volumes.append(vol)

    if vcts:
        spec["volumeClaimTemplates"] = vcts
    if remaining_volumes:
        pod_spec["volumes"] = remaining_volumes
    elif "volumes" in pod_spec:
        del pod_spec["volumes"]

    return result


def find_matching_service(
    manifests: list[dict], app_name: str
) -> Optional[dict]:
    """Find the Service manifest matching the app name."""
    for m in manifests:
        if m.get("kind") == "Service" and m.get("metadata", {}).get("name") == app_name:
            return m
    return None
