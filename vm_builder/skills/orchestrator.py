"""End-to-end orchestration for VM Builder repo skill generation."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from vm_builder.skills.constants import SKIP_MODULES
from vm_builder.skills.extractor import extract_public_operations
from vm_builder.skills.scanner import iter_source_modules
from vm_builder.skills.writer import write_skill_file


def generate_skills(
    source_root: Path,
    output_dir: Path,
    service: str = "vm-builder",
) -> list[Path]:
    """Generate VM Builder skill markdown files from source modules."""
    generated: list[Path] = []

    for source_file in iter_source_modules(source_root):
        if source_file.stem in SKIP_MODULES:
            continue

        operations = extract_public_operations(source_file)
        op_counts: dict[str, int] = Counter(str(op["operation"]) for op in operations)
        colliding_ops = {name for name, count in op_counts.items() if count > 1}

        for operation in operations:
            generated.append(
                write_skill_file(
                    operation=operation,
                    output_dir=output_dir,
                    colliding_operations=colliding_ops,
                    service=service,
                )
            )

    return generated

