"""Init command wrapper."""

from vm_builder.commands.init_cmd.run import init_shared_secrets
from vm_builder.commands.init_cmd.status import show_init_status

__all__ = ["init_shared_secrets", "show_init_status"]
