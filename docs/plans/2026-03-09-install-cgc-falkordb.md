# Install CGC + FalkorDB Lite Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Install CodeGraphContext with FalkorDB Lite backend so `cgc index .` and `cgc analyze` commands work against this repo's codebase.

**Architecture:** CGC is installed as a pip package into the existing `.venv`. FalkorDB Lite runs in-process (no Docker container). The `cgc index .` command walks Python/TypeScript source via tree-sitter, builds a graph in `~/.codegraphcontext/`, and exposes it via CLI and MCP server.

**Tech Stack:** Python 3.12, codegraphcontext 0.2.8, falkordblite 0.9.0

**GitHub Issue:** #21

---

## Task 1: Install CGC and FalkorDB Lite into the venv

**Files:**
- No file changes — pip install only

**Step 1: Install packages**

Run:
```bash
/Users/morgan/GitRepo/k3s-automated-installers/.venv/bin/pip install codegraphcontext falkordblite
```

Expected: Successful install with tree-sitter, typer, neo4j driver, and other deps.

**Step 2: Verify cgc CLI is available**

Run:
```bash
/Users/morgan/GitRepo/k3s-automated-installers/.venv/bin/cgc --help
```

Expected: Help output showing commands: `index`, `analyze`, `mcp`, `watch`, `list`, `neo4j`, `help`.

**Step 3: Verify FalkorDB Lite backend is available**

Run:
```bash
/Users/morgan/GitRepo/k3s-automated-installers/.venv/bin/python -c "import falkordblite; print('FalkorDB Lite OK')"
```

Expected: `FalkorDB Lite OK`

---

## Task 2: Index the repo with CGC

**Files:**
- No file changes — cgc stores its graph in `~/.codegraphcontext/`

**Step 1: Run cgc index from repo root**

Run:
```bash
cd /Users/morgan/GitRepo/k3s-automated-installers && .venv/bin/cgc index .
```

Expected: Output showing files indexed. CGC will parse Python files in `idi/`, `platform-tools/vm-builder/vm_builder/`, `scripts/`, and TypeScript files in `platform-tools/vm-builder/vm-builder-web/src/`.

Note: This may take 30-60 seconds for the full repo. If CGC prompts for backend selection, choose FalkorDB Lite.

**Step 2: Verify the index exists**

Run:
```bash
.venv/bin/cgc list
```

Expected: Shows the indexed repo with file count and graph stats.

---

## Task 3: Verify CGC analysis commands work

**Files:**
- No file changes — read-only queries

**Step 1: Test dead code detection**

Run:
```bash
cd /Users/morgan/GitRepo/k3s-automated-installers && .venv/bin/cgc analyze dead-code
```

Expected: List of potentially unreachable functions (may be empty or have false positives — that's OK, we just need the command to work).

**Step 2: Test call chain analysis on a known function**

Run:
```bash
.venv/bin/cgc analyze calls cli --depth 2
```

Expected: Shows functions called by `cli`. If `cli` is ambiguous, try a more specific function name from the codebase like `generate_all` or `download_specs`.

**Step 3: Test callers analysis**

Run:
```bash
.venv/bin/cgc analyze callers generate_all
```

Expected: Shows what calls `generate_all` (should find the script shim and CLI entry point).

---

## Task 4: Add CGC to .gitignore exclusions

**Files:**
- Modify: `.gitignore`

**Step 1: Check if CGC creates any local files in the repo**

Run:
```bash
cd /Users/morgan/GitRepo/k3s-automated-installers && git status --short
```

Look for any new untracked files created by CGC (e.g., `.codegraphcontext/` local cache). The main graph is stored in `~/.codegraphcontext/` (user home), but CGC may create a local `.cgc` or `.codegraphcontext` config in the repo root.

**Step 2: Add any CGC local files to .gitignore**

If CGC created local files (e.g., `.codegraphcontext/`), add them to `.gitignore`:

```gitignore
# CGC (CodeGraphContext) local cache
.codegraphcontext/
```

If no local files were created, skip this step.

**Step 3: Commit**

Run:
```bash
git add .gitignore
git commit -m "chore: add CGC local files to gitignore"
```

Only commit if `.gitignore` was changed.

---

## Task 5: Document CGC setup for developers

**Files:**
- Modify: `docs/plans/2026-03-09-auto-index-generation-design.md` (add setup verification section)

**Step 1: Add verified setup commands to the design doc**

After the CGC Setup Details section in the design doc, add a "Verified Setup" subsection documenting the exact commands that worked and any quirks discovered during installation (backend selection prompts, warnings, etc.).

**Step 2: Commit**

Run:
```bash
git add docs/plans/2026-03-09-auto-index-generation-design.md
git commit -m "docs: add verified CGC setup instructions"
```

---

## Verification Checklist

Before marking #21 complete, verify all of these pass:

- [ ] `cgc --help` shows CLI commands
- [ ] `cgc list` shows the indexed repo
- [ ] `cgc analyze dead-code` runs without error
- [ ] `cgc analyze calls <function>` returns call chain data
- [ ] `cgc analyze callers <function>` returns caller data
- [ ] No CGC artifacts committed to git
- [ ] FalkorDB Lite is the active backend (not Neo4j)
