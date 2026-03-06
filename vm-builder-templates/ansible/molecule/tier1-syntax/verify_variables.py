#!/usr/bin/env python3
"""Verify all J2 templates render without undefined variables using BWS-cached data."""

import json
import sys
from pathlib import Path

import jinja2

SCRIPT_DIR = Path(__file__).parent
ANSIBLE_DIR = SCRIPT_DIR.parent.parent  # tier1-syntax -> molecule -> ansible
FIXTURES_DIR = SCRIPT_DIR.parent / "fixtures"
APPS_DIR = ANSIBLE_DIR.parent / "apps"


def load_vars(app: str) -> dict:
    """Load per-app config vars from fixtures."""
    config_path = FIXTURES_DIR / "per-app" / f"config-{app}.json"
    if config_path.exists():
        return json.loads(config_path.read_text())
    return {}


def main() -> int:
    errors: list[str] = []
    tested = 0

    for app_dir in sorted(APPS_DIR.iterdir()):
        if not app_dir.is_dir():
            continue
        templates_dir = app_dir / "templates"
        if not templates_dir.exists():
            continue

        app = app_dir.name
        app_vars = load_vars(app)
        # Add common defaults that playbooks set in vars: blocks
        app_vars.setdefault("app_name", app)
        app_vars.setdefault("app_namespace", app_vars.get("namespace", "default"))
        app_vars.setdefault("render_dir", f"/tmp/{app}-manifests")
        app_vars.setdefault("kubectl_action", "apply")
        app_vars.setdefault("install_mode", "rebuild")
        app_vars.setdefault("target_hosts", "localhost")

        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(templates_dir)),
            undefined=jinja2.StrictUndefined,
        )
        # Register Ansible-specific filters as pass-through stubs
        ansible_filters = {
            "quote": lambda x: str(x),
            "to_json": lambda x: str(x),
            "to_yaml": lambda x: str(x),
            "to_nice_json": lambda x: str(x),
            "to_nice_yaml": lambda x: str(x),
            "b64encode": lambda x: str(x),
            "b64decode": lambda x: str(x),
            "from_json": lambda x: x,
            "from_yaml": lambda x: x,
            "bool": lambda x: bool(x),
            "ternary": lambda val, true_val, false_val="": true_val if val else false_val,
            "regex_replace": lambda val, pattern="", replacement="": str(val),
            "regex_search": lambda val, pattern="": str(val),
            "combine": lambda *args, **kwargs: {},
            "dict2items": lambda x: list(x.items()) if isinstance(x, dict) else x,
            "items2dict": lambda x: dict(x) if isinstance(x, list) else x,
            "flatten": lambda x: x,
            "unique": lambda x: list(set(x)) if isinstance(x, list) else x,
            "mandatory": lambda x: x,
            "default": lambda x, d="": x if x else d,
            "basename": lambda x: str(x).rsplit("/", 1)[-1],
            "dirname": lambda x: str(x).rsplit("/", 1)[0],
            "hash": lambda x, algo="sha1": str(x),
            "urlencode": lambda x: str(x),
        }
        env.filters.update(ansible_filters)

        for j2_file in sorted(templates_dir.glob("*.j2")):
            tested += 1
            try:
                template = env.get_template(j2_file.name)
                template.render(**app_vars)
            except jinja2.UndefinedError as e:
                errors.append(f"{app}/templates/{j2_file.name}: {e}")
            except jinja2.TemplateSyntaxError as e:
                errors.append(f"{app}/templates/{j2_file.name}: SYNTAX ERROR: {e}")
            except Exception as e:
                errors.append(f"{app}/templates/{j2_file.name}: UNEXPECTED: {e}")

    print(f"\nTested {tested} templates across {len(list(APPS_DIR.iterdir()))} apps")

    if errors:
        print(f"\n{len(errors)} FAILURES:")
        for err in errors:
            print(f"  FAIL: {err}")
        return 1
    else:
        print("All templates render successfully with BWS-cached vars.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
