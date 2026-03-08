"""Generate golden-master-compliant install/verify/uninstall playbooks."""

from dataclasses import dataclass
from typing import Optional

import yaml


@dataclass
class PlaybookConfig:
    """Configuration for playbook generation."""

    app_name: str
    app_namespace: str
    nodeport: int = 0
    container_port: int = 8080
    image: str = ""
    has_pvc: bool = False
    has_secrets: bool = False
    has_pushsecret: bool = False
    health_endpoint: str = ""
    kustomize_dir: str = "k8s-base"
    category: str = "Application"
    credential_fields: Optional[list[str]] = None


def generate_install_playbook(config: PlaybookConfig) -> str:
    """Generate a golden-master-compliant install playbook (kustomize variant)."""
    tasks = []

    # Section 1: Prerequisites
    tasks.append({
        "name": "Verify K3s is running",
        "ansible.builtin.command": {"cmd": "kubectl cluster-info"},
        "changed_when": False,
        "register": "cluster_check",
        "failed_when": "cluster_check.rc != 0",
    })

    # Section 3: Render protected J2 templates
    tasks.append({
        "name": "Create render directory",
        "ansible.builtin.file": {
            "path": "{{ render_dir }}",
            "state": "directory",
            "mode": "0755",
        },
    })

    tasks.append({
        "name": "Render protected J2 templates",
        "ansible.builtin.template": {
            "src": "{{ item }}",
            "dest": "{{ render_dir }}/{{ item | basename | regex_replace('\\.j2$', '') }}",
        },
        "loop": "{{ lookup('fileglob', templates_dir + '/*.j2') | sort }}",
    })

    # Section 4: Ensure namespace
    tasks.append({
        "name": "Ensure namespace exists",
        "ansible.builtin.command": {
            "cmd": "kubectl apply -f {{ render_dir }}/00-namespace.yaml",
        },
        "register": "ns_result",
        "changed_when": "'created' in ns_result.stdout or 'configured' in ns_result.stdout",
    })

    # Section 5: Dry-run validation
    tasks.append({
        "name": "Dry-run validate rendered manifests",
        "ansible.builtin.command": {
            "cmd": "kubectl apply --dry-run=server -f {{ render_dir }}/",
        },
        "changed_when": False,
    })

    # Section 6: PVC safety gate (conditional)
    if config.has_pvc:
        tasks.append({
            "name": "Check for existing Bound PVCs (safety gate)",
            "ansible.builtin.command": {
                "cmd": (
                    "kubectl get pvc -n {{ app_namespace }} -o json"
                ),
            },
            "register": "existing_pvcs",
            "changed_when": False,
            "failed_when": False,
        })
        tasks.append({
            "name": "Downgrade to apply if Bound PVCs detected",
            "ansible.builtin.set_fact": {
                "kubectl_action": "apply",
            },
            "when": "existing_pvcs.rc == 0 and (existing_pvcs.stdout | from_json).items | length > 0",
        })

    # Section 7: Apply protected resources (always kubectl apply)
    tasks.append({
        "name": "Apply protected resources (secrets, PVCs)",
        "ansible.builtin.command": {
            "cmd": "kubectl apply -f {{ render_dir }}/{{ item }}",
        },
        "loop": (
            "{{ lookup('fileglob', render_dir + '/*') "
            "| map('basename') | select('match', '^[0-3]') | sort | list }}"
        ),
        "register": "protected_result",
        "changed_when": "'created' in protected_result.stdout or 'configured' in protected_result.stdout",
    })

    # Section 8: Apply kustomize base
    tasks.append({
        "name": f"Apply kustomize base (workload resources)",
        "ansible.builtin.command": {
            "cmd": "kubectl {{ kubectl_action }} -k {{ kustomize_dir }}",
        },
        "register": "kustomize_result",
        "changed_when": "'created' in kustomize_result.stdout or 'configured' in kustomize_result.stdout",
    })

    # Section 9: Two-step pod wait
    tasks.append({
        "name": f"Wait for {config.app_name} pod to exist",
        "ansible.builtin.command": {
            "cmd": (
                f"kubectl get pods -n {{{{ app_namespace }}}} "
                f"-l app.kubernetes.io/name={{{{ app_name }}}} -o json"
            ),
        },
        "register": "pod_check",
        "until": "(pod_check.stdout | from_json).items | length > 0",
        "retries": "{{ pod_exists_retries }}",
        "delay": "{{ pod_exists_delay }}",
        "changed_when": False,
    })
    tasks.append({
        "name": f"Wait for {config.app_name} pod readiness",
        "ansible.builtin.command": {
            "cmd": (
                f"kubectl wait --for=condition=Ready pod "
                f"-l app.kubernetes.io/name={{{{ app_name }}}} "
                f"-n {{{{ app_namespace }}}} --timeout={{{{ pod_ready_timeout }}}}s"
            ),
        },
        "changed_when": False,
    })

    # Section 11: Status display
    tasks.append({
        "name": "Display deployment status",
        "ansible.builtin.command": {
            "cmd": "kubectl get all -n {{ app_namespace }}",
        },
        "register": "status",
        "changed_when": False,
    })
    tasks.append({
        "name": "Show status",
        "ansible.builtin.debug": {"msg": "{{ status.stdout_lines }}"},
    })

    # Section 12: Cleanup
    tasks.append({
        "name": "Cleanup render directory",
        "ansible.builtin.file": {
            "path": "{{ render_dir }}",
            "state": "absent",
        },
    })

    playbook = [{
        "name": f"Deploy {config.app_name} to K3s cluster",
        "hosts": "localhost",
        "gather_facts": False,
        "vars": {
            "app_name": config.app_name,
            "app_namespace": config.app_namespace,
            "templates_dir": f"{{{{ playbook_dir }}}}/../templates",
            "kustomize_dir": f"{{{{ playbook_dir }}}}/../{config.kustomize_dir}",
            "render_dir": f"/tmp/{config.app_name}-manifests",
            "kubectl_action": "{{ kubectl_action | default('apply') }}",
            "install_mode": "{{ install_mode | default('rebuild') }}",
            "pod_exists_retries": 30,
            "pod_exists_delay": 10,
            "pod_ready_timeout": 300,
        },
        "tasks": tasks,
    }]

    return yaml.dump(playbook, default_flow_style=False, sort_keys=False, width=120)


def generate_verify_playbook(config: PlaybookConfig) -> str:
    """Generate a verification playbook."""
    tasks = []

    tasks.append({
        "name": f"Check {config.app_name} pod is running",
        "ansible.builtin.command": {
            "cmd": (
                f"kubectl get pods -n {{{{ app_namespace }}}} "
                f"-l app.kubernetes.io/name={{{{ app_name }}}} "
                f"-o jsonpath='{{{{.items[0].status.phase}}}}'"
            ),
        },
        "register": "pod_status",
        "changed_when": False,
        "failed_when": "'Running' not in pod_status.stdout",
    })

    if config.health_endpoint:
        tasks.append({
            "name": f"Verify {config.app_name} health endpoint",
            "ansible.builtin.uri": {
                "url": f"http://127.0.0.1:{{{{ nodeport }}}}{config.health_endpoint}",
                "status_code": [200],
            },
            "register": "health_result",
            "retries": 3,
            "delay": 10,
        })

    tasks.append({
        "name": "Deployment verification complete",
        "ansible.builtin.debug": {
            "msg": f"{config.app_name} is healthy and running in {{{{ app_namespace }}}}",
        },
    })

    playbook = [{
        "name": f"Verify {config.app_name} deployment",
        "hosts": "localhost",
        "gather_facts": False,
        "vars": {
            "app_name": config.app_name,
            "app_namespace": config.app_namespace,
            "nodeport": config.nodeport,
        },
        "tasks": tasks,
    }]

    return yaml.dump(playbook, default_flow_style=False, sort_keys=False, width=120)


def generate_uninstall_playbook(config: PlaybookConfig) -> str:
    """Generate an uninstall playbook."""
    tasks = [
        {
            "name": f"Delete {config.app_name} namespace and all resources",
            "ansible.builtin.command": {
                "cmd": f"kubectl delete namespace {{{{ app_namespace }}}} --ignore-not-found",
            },
            "register": "delete_result",
            "changed_when": "'deleted' in delete_result.stdout",
        },
        {
            "name": "Confirm removal",
            "ansible.builtin.debug": {
                "msg": f"{config.app_name} has been removed from the cluster",
            },
        },
    ]

    playbook = [{
        "name": f"Remove {config.app_name} from K3s cluster",
        "hosts": "localhost",
        "gather_facts": False,
        "vars": {
            "app_name": config.app_name,
            "app_namespace": config.app_namespace,
        },
        "tasks": tasks,
    }]

    return yaml.dump(playbook, default_flow_style=False, sort_keys=False, width=120)
