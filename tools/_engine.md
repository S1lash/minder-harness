# The tools the engine ships

> Engine-owned, so every update carries the current list. The person's own tools are catalogued
> beside this, in `_index.md`, which no update touches.
> What a tool is versus a skill or an instrument: `../doctrine/tool-vs-instrument.md`.

| Tool | What it does | Invoke |
|---|---|---|
| `sync.py` | Reports what state the base is in across the person's devices and takes the safe action for it. Never forces, never discards a side. | `python3 tools/sync.py status\|session-start\|pull\|save "<why>"` |
| `update.py` | Brings the engine half of this base up to the version the engine ships: replaces engine paths, seeds what is missing, carries declared moves, drops what the engine retired. Never touches what the person wrote. | `python3 tools/update.py [--dry-run\|--check\|--self-heal]` |
| `check_engine.py` | Proves the engine half of a base is coherent. `--authoring` adds the release gates. | `python3 tools/check_engine.py [--authoring]` |
| `check_portability.py` | Proves every file the engine ships would run the same on Windows, macOS and Linux — the machine-checkable half of `rules/cross-platform.md`. Called by `check_engine.py`; run it alone to see what it checks. | `python3 tools/check_portability.py [--report\|--rules\|--path <p>]` |
| `tests/` | Re-runs by machine what was once verified by hand. | `python3 -m unittest discover -s tools/tests` |
| `mcp-wrapper.js` | Wraps a local MCP server so it can't leave zombie processes on exit. | `node tools/mcp-wrapper.js <command> <args…>` (in MCP config) |
