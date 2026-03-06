"""Template sidecar generation package for VM Builder templates."""

from vm_builder.template_sidecars.app import generate_sidecar_for_app
from vm_builder.template_sidecars.detect_template import detect_template_refs
from vm_builder.template_sidecars.detect_uri import detect_uri_calls
from vm_builder.template_sidecars.detect_wiring import detect_wiring
from vm_builder.template_sidecars.metadata import parse_playbook_metadata
from vm_builder.template_sidecars.orchestrator import generate_all_sidecars

__all__ = [
    "detect_template_refs",
    "detect_uri_calls",
    "detect_wiring",
    "generate_all_sidecars",
    "generate_sidecar_for_app",
    "parse_playbook_metadata",
]
