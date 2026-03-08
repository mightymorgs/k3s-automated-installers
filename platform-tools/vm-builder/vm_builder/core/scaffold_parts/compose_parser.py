"""Extract wiring edges from Docker Compose files."""

import re
from dataclasses import dataclass, field


@dataclass
class WiringEdge:
    """A dependency edge between two services."""

    source: str
    target: str
    edge_type: str  # "depends_on", "env:VAR_NAME", "network:net_name"
    env_key: str = ""
    env_value: str = ""


@dataclass
class ComposeService:
    """Parsed service from a Compose file."""

    name: str
    image: str = ""
    host_port: int = 0
    container_port: int = 0
    environment: dict = field(default_factory=dict)
    volumes: list = field(default_factory=list)


@dataclass
class ComposeResult:
    """Result of parsing a Docker Compose file."""

    services: dict[str, ComposeService] = field(default_factory=dict)
    all_edges: list[WiringEdge] = field(default_factory=list)
    shared_volumes: dict[str, list[str]] = field(default_factory=dict)

    def edges_for(self, service_name: str) -> list[WiringEdge]:
        return [e for e in self.all_edges if e.source == service_name]


def _parse_port(port_str: str) -> tuple[int, int]:
    """Parse a port mapping like '8989:8989' or '8080'."""
    parts = str(port_str).split(":")
    if len(parts) == 2:
        return int(parts[0]), int(parts[1])
    return int(parts[0]), int(parts[0])


def parse_compose(compose_data: dict) -> ComposeResult:
    """Parse a Docker Compose dict and extract wiring edges."""
    result = ComposeResult()
    services_data = compose_data.get("services", {})
    service_names = set(services_data.keys())

    # Track volume usage
    volume_users: dict[str, list[str]] = {}

    for svc_name, svc_def in services_data.items():
        # Parse service basics
        svc = ComposeService(name=svc_name)
        svc.image = svc_def.get("image", "")
        svc.environment = svc_def.get("environment", {})
        if isinstance(svc.environment, list):
            svc.environment = dict(
                item.split("=", 1) for item in svc.environment if "=" in item
            )
        svc.volumes = svc_def.get("volumes", [])

        # Parse ports
        ports = svc_def.get("ports", [])
        if ports:
            host_port, container_port = _parse_port(ports[0])
            svc.host_port = host_port
            svc.container_port = container_port

        result.services[svc_name] = svc

        # Extract depends_on edges
        depends_on = svc_def.get("depends_on", [])
        if isinstance(depends_on, dict):
            depends_on = list(depends_on.keys())
        for dep in depends_on:
            result.all_edges.append(
                WiringEdge(source=svc_name, target=dep, edge_type="depends_on")
            )

        # Extract environment variable references
        for key, value in svc.environment.items():
            value_str = str(value)
            for other_svc in service_names:
                if other_svc == svc_name:
                    continue
                if other_svc in value_str or other_svc.replace("-", "_") in value_str:
                    result.all_edges.append(
                        WiringEdge(
                            source=svc_name,
                            target=other_svc,
                            edge_type=f"env:{key}",
                            env_key=key,
                            env_value=value_str,
                        )
                    )

        # Track volume usage
        for vol in svc.volumes:
            vol_name = str(vol).split(":")[0]
            if not vol_name.startswith("/") and not vol_name.startswith("."):
                volume_users.setdefault(vol_name, []).append(svc_name)

    # Identify shared volumes
    result.shared_volumes = {
        name: users for name, users in volume_users.items() if len(users) > 1
    }

    return result
