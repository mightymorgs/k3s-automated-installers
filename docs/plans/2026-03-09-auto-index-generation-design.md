# Auto-Index Generation with CGC Enrichment

**Date:** 2026-03-09
**Status:** Design approved, pending implementation
**Source repo:** `/Users/morgan/GitRepo/attention-driven-architecture` (read-only reference)
**Target repo:** `/Users/morgan/GitRepo/k3s-automated-installers`

---

## Problem

LLMs and developers need a fast way to discover what's in this repo — which module does what, which playbook deploys which app, how services depend on each other. The attention-driven-architecture repo has a 3,600-line `scripts/generate_indexes.py` that generates comprehensive Markdown + JSON indexes for IDI and VM-Builder via AST analysis with optional CGC Neo4j enrichment. That script needs to be ported to this repo and expanded to cover the template system.

## Architecture

Three layers:

### Layer 1: CGC (CodeGraphContext)

[CodeGraphContext](https://github.com/CodeGraphContext/CodeGraphContext) indexes the repo's Python/TypeScript source into a FalkorDB Lite graph database (in-process, no Docker container needed). Provides call chains, import graphs, dead code detection, and impact analysis.

- **Backend:** FalkorDB Lite (Python 3.12+, Unix, in-process)
- **Install:** `pip install codegraphcontext falkordblite` (dev dependency)
- **Index:** `cgc index .` from repo root
- **MCP server:** `cgc mcp start` — configured in `.mcp.json`
- **CLI:** `cgc analyze callers|calls|dead-code|complexity`

CGC is a **separate graph from the IDI Neo4j** instance. IDI Neo4j stores skill/fact data; CGC FalkorDB stores code structure.

### Layer 2: generate_indexes.py

Ported from `attention-driven-architecture/scripts/generate_indexes.py`. Walks source trees via Python AST, queries CGC for enrichment, generates dual output (Markdown + JSON).

**Packages indexed:**

| Package | Source Path | Index File |
|---------|------------|------------|
| IDI generation | `idi/` | `docs/IDI-INDEX.md` + `.json` |
| VM-Builder backend | `platform-tools/vm-builder/vm_builder/` | `docs/VM-BUILDER-INDEX.md` + `.json` |
| VM-Builder frontend | `platform-tools/vm-builder/vm-builder-web/src/` | Included in VM-BUILDER-INDEX |
| App templates | `vm-builder-templates/apps/*/` | `docs/TEMPLATES-INDEX.md` + `.json` |

**Index sections per package:**

0. Quick reference cheat sheet (task → where to edit)
1. Static module index (every file, grouped by area, with docstrings)
2. Entry point map (CLI commands, API routes, MCP tools)
3. Tool-specific section (MCP tool map / API route map)
4. External dependency flow (which modules call which external systems)
5. Architectural patterns / web UI index

**CGC enrichment (wiring the dead code from the original):**

The original script defines `_cgc_call_chain()` and `_cgc_file_imports()` but never calls them. This port will wire them into:

- **Section 2 (Entry Point Map):** Replace hand-written call tree templates with real call graphs from CGC. `_cgc_call_chain(entry_func)` traces from each CLI/API entry point through the call graph.
- **Section 4 (External Dependencies):** `_cgc_file_imports(module)` enriches import dependency tables with actual consumers of each external package.
- **New section:** Dead code report from `cgc analyze dead-code`.

Graceful fallback: `--no-cgc` flag falls back to AST-only mode (existing behavior).

### Layer 3: Template Indexer

Two-stage pipeline for `vm-builder-templates/apps/*/`:

**Stage 1: Sidecar generation** (already ported — `vm_builder.template_sidecars`)

Walks all 33 app directories, parses each `.yml`/`.yaml`/`.j2` file:
- Extracts `playbook_metadata:` from comment blocks via `metadata.py`
- Detects API URI calls via `detect_uri.py`
- Detects Jinja2 template references via `detect_template.py`
- Detects BWS wiring (reads_from/writes_to) via `detect_wiring.py`
- Detects cross-service dependencies via `detect_uri.py`
- Writes structured `.idi-meta.yaml` per phase directory

Run via: `python scripts/generate_template_sidecars.py --generate`

**Stage 2: Index generation** (new, in `generate_indexes.py`)

Reads both `.idi-meta.yaml` structured data AND raw playbook metadata comments:

- `.idi-meta.yaml` → wiring, API calls, template refs, service deps
- `playbook_metadata:` comments → description, compatibility, bws_state, credentials, ingress, sso, vars, ui metadata
- Jinja2 template headers → variable documentation

Output per app in `docs/TEMPLATES-INDEX.md`:

```markdown
### vault (6 phases, 14 files)

| Phase | Playbook | Summary | Dependencies |
|-------|----------|---------|-------------|
| install | 01-deploy-server.yml | Deploy HashiCorp Vault server | longhorn |
| install | 02-verify.yml | Verify Vault deployment | — |
| config | 00-init-vault.yml | Initialize Vault cluster | — |
| config | 01-configure-audit.yml | Configure audit logging | — |

**BWS State:** reads ∅ | writes vault.url, vault.nodeport, vault.status, vault.root_token
**Templates:** 7 Jinja2 files (namespace, configmap, statefulset, service, ...)
**Depends on:** longhorn, cert-manager
**Required by:** external-secrets, grafana, authentik
```

JSON output includes the full structured data for programmatic access.

## Package Group Definitions

The original script has `IDI_GROUPS` and `VM_BUILDER_GROUPS` that map directory trees to index sections. These need updating for this repo's layout:

**IDI_GROUPS** (trimmed — this repo only has generation/common/enrichment):

```python
IDI_GROUPS = [
    ("###", "Top-Level Module", ""),
    ("###", "Common Utilities", "common"),
    ("###", "Generation — OpenAPI-to-Skill Pipeline", "generation"),
    ("####", "generation/adapters/", "generation/adapters"),
    ("####", "generation/dep_adapters/", "generation/dep_adapters"),
    ("####", "generation/crd/", "generation/crd"),
    ("###", "Enrichment — Context7 Integration", "enrichment"),
]
```

**VM_BUILDER_GROUPS** (same structure, path prefix changes to `platform-tools/vm-builder/vm_builder/`):

```python
VM_BUILDER_GROUPS = [
    ("###", "Top-Level Modules", ""),
    ("###", "CLI Atomic — Command Registration", "cli_atomic"),
    ("###", "Commands — CLI Implementation", "commands"),
    ("####", "commands/hypervisor_cmd/", "commands/hypervisor_cmd"),
    ("####", "commands/init_cmd/", "commands/init_cmd"),
    ("####", "commands/validate_cmd/", "commands/validate_cmd"),
    ("####", "commands/vm_cmd/", "commands/vm_cmd"),
    ("###", "API — FastAPI Application", "api"),
    ("####", "api/routes/", "api/routes"),
    ("###", "Core — Service Layer", "core"),
    ("###", "Core Atomic Parts", "_parts_"),
    ("###", "BWS Parts", "bws_parts"),
    ("###", "Schema Parts", "schema_parts"),
    ("###", "Template Sidecars", "template_sidecars"),
]
```

## CGC Setup Details

### Installation

```bash
# In the repo's venv
pip install codegraphcontext falkordblite

# Index the repo
cgc index .

# Verify
cgc analyze dead-code
cgc analyze callers generate_index
```

### MCP Configuration

Added to `.mcp.json`:

```json
{
  "mcpServers": {
    "codegraphcontext": {
      "command": "cgc",
      "args": ["mcp", "start"]
    }
  }
}
```

No Neo4j credentials needed — FalkorDB Lite is embedded.

### Integration in generate_indexes.py

Replace the Neo4j driver calls with CGC's Python API or CLI:

```python
def _cgc_connect():
    """Connect to CGC FalkorDB. Returns client or None."""
    try:
        from codegraphcontext import CodeGraphContext
        cgc = CodeGraphContext()
        return cgc
    except Exception:
        return None

def _cgc_call_chain(cgc, entry_func, max_depth=4):
    """Query CGC for call chain from a function."""
    # Use cgc.analyze_calls() or equivalent API
    ...

def _cgc_file_imports(cgc, module_name):
    """Query CGC for files that import a given module."""
    # Use cgc.analyze_callers() or equivalent API
    ...
```

## CLI Interface

```bash
# Regenerate all indexes (with CGC enrichment if available)
python scripts/generate_indexes.py

# Check if indexes are stale (CI mode)
python scripts/generate_indexes.py --check

# Skip CGC, AST-only
python scripts/generate_indexes.py --no-cgc

# Regenerate sidecars first, then indexes
python scripts/generate_template_sidecars.py --generate
python scripts/generate_indexes.py
```

## Output Files

```
docs/
├── IDI-INDEX.md              # IDI generation package index
├── IDI-INDEX.json            # Structured IDI data
├── VM-BUILDER-INDEX.md       # VM-Builder backend + frontend index
├── VM-BUILDER-INDEX.json     # Structured VM-Builder data
├── TEMPLATES-INDEX.md        # 33-app template index
└── TEMPLATES-INDEX.json      # Structured template data
```

All files include:
- Generation timestamp
- Git commit/branch/dirty state
- CGC mode flag (enriched vs AST-only)
- Module/file counts

## What's NOT in Scope

- Terraform/HCL indexing (defer to future issue)
- Ansible shared playbooks (`vm-builder-templates/ansible/`) — only app templates
- Real-time MCP-based querying (Approach C) — static files only
- Neo4j schema changes — CGC uses its own FalkorDB instance
