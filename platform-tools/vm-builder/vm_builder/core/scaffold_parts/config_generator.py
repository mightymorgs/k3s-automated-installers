"""Generate Phase 4 config playbooks from Compose wiring edges."""

import yaml

from vm_builder.core.scaffold_parts.compose_parser import WiringEdge


def generate_wiring_playbook(
    app_name: str, edge: WiringEdge, nodeport: int = 0
) -> str:
    """Generate a single wiring playbook for one dependency."""
    tasks = [
        {
            "name": f"TODO: Wire {edge.target} connection for {app_name}",
            "ansible.builtin.debug": {
                "msg": (
                    f"Configure {app_name} to connect to {edge.target}. "
                    f"Edge type: {edge.edge_type}. "
                    f"Implement the API call or config update here."
                ),
            },
        },
    ]

    metadata_comment = (
        f"# playbook_metadata:\n"
        f"#   id: {app_name}-wire-{edge.target}\n"
        f"#   type: atomic\n"
        f"#   requires_apps:\n"
        f"#     - {app_name}\n"
        f"#     - {edge.target}\n"
    )

    playbook = [{
        "name": f"Wire {edge.target} for {app_name}",
        "hosts": "localhost",
        "gather_facts": False,
        "vars": {
            "app_name": app_name,
            "app_namespace": f"{{{{ app_namespace | default('{app_name}') }}}}",
            f"{edge.target}_nodeport": f"{{{{ {edge.target}_nodeport | default(0) }}}}",
            f"{edge.target}_api_key": f"{{{{ {edge.target}_api_key | default('') }}}}",
        },
        "tasks": tasks,
    }]

    return metadata_comment + yaml.dump(
        playbook, default_flow_style=False, sort_keys=False, width=120
    )


def generate_config_playbooks(
    app_name: str, edges: list[WiringEdge], nodeport: int = 0
) -> list[tuple[str, str]]:
    """Generate config playbooks for all wiring edges. Returns [(content, filename)]."""
    if not edges:
        return []

    # Deduplicate by target
    seen_targets: set[str] = set()
    unique_edges: list[WiringEdge] = []
    for edge in edges:
        if edge.target not in seen_targets:
            seen_targets.add(edge.target)
            unique_edges.append(edge)

    results: list[tuple[str, str]] = []
    for i, edge in enumerate(unique_edges):
        number = 5 + i  # Start at 05-wire-*
        filename = f"{number:02d}-wire-{edge.target}.yml"
        content = generate_wiring_playbook(app_name, edge, nodeport)
        results.append((content, filename))

    return results
