"""Stub playbook and exception sidecar generation for failed wiring edges."""

from __future__ import annotations

from typing import Any

import yaml

from vm_builder.core.wiring_compiler_parts.models import WiringException


def create_stub_playbook(exception: WiringException) -> str:
    """Generate a valid Ansible playbook stub for a failed wiring edge."""
    consumer = exception.consumer_app
    provider = exception.provider_app
    reason = exception.reason
    taxonomy = exception.stub_taxonomy.value

    metadata_comment = (
        f"# playbook_metadata:\n"
        f"#   id: wire-{consumer}-{provider}-stub\n"
        f"#   type: stub\n"
        f"#   requires_apps:\n"
        f"#     - {consumer}\n"
        f"#     - {provider}\n"
        f"#   stub_reason: {taxonomy}\n"
    )

    playbook = [{
        "name": f"STUB: Wire {consumer} to {provider}",
        "hosts": "localhost",
        "gather_facts": False,
        "tasks": [{
            "name": f"Stub: {reason}",
            "ansible.builtin.debug": {
                "msg": (
                    f"This wiring playbook could not be auto-generated. "
                    f"Reason: {reason} "
                    f"Taxonomy: {taxonomy} "
                    f"TODO: Implement manually or provide enrichment data."
                ),
            },
        }],
    }]

    body = yaml.dump(playbook, default_flow_style=False, sort_keys=False, width=120)
    return metadata_comment + "---\n" + body


def create_exception_sidecar(exception: WiringException) -> dict[str, Any]:
    """Generate a .wiring-exception.json sidecar dict for a failed wiring edge."""
    return {
        "consumer_app": exception.consumer_app,
        "provider_app": exception.provider_app,
        "reason": exception.reason,
        "stub_taxonomy": exception.stub_taxonomy.value,
        "fields_attempted": exception.fields_attempted,
        "error_detail": exception.error_detail,
    }
