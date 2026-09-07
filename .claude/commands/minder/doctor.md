---
description: Report-only health check of this base. Verifies the canon is wired hot and named identically for every agent, the indexes exist, the base can actually reach the person's other devices, the engine half is updatable and portable, every local MCP server is wrapped, and profile.md has a language. Reports PASS / WARN / FAIL and fixes nothing.
---

# /minder:doctor

Self-check of this base. Reads state, reports findings, **fixes nothing** — the agent or the
relevant flow fixes what it surfaces.

## Before any step: stand in the base

This verb answers for a base, not for wherever the session happens to be open — the installer makes
it available from every folder, so the current folder is not the answer. The base is the path on the
**HARNESS HOME** line of the person's global entry (`~/.claude/CLAUDE.md` for Claude Code,
`~/.codex/AGENTS.md` for Codex), already loaded in this session. Every command below runs THERE.

Running `python3 tools/...` in whatever directory is current is not a smaller version of this:
another project can hold a file by the same name, and running it would execute somebody else's
script under this command's name.

No **HARNESS HOME** line means this base was never wired. Say so and stop; do not guess a path.

## Checks (each → PASS / WARN / FAIL)

1. **Canon is hot.** The canon reaches you in this session. On a machine the person installed on,
   that is the agent's global entry point (Claude `~/.claude/CLAUDE.md`, Codex `~/.codex/AGENTS.md`,
   Cursor user rules) naming this base. In a session that starts from a fresh clone of the base,
   `CLAUDE.md` at the repo root carries it and no global wiring exists — that is PASS, not FAIL.
2. **Canon complete, and listed once.** Every file in `rules/` appears in the canon list in
   `AGENTS.md` — the one hand-maintained list. A rule missing there is a FAIL naming it: it is
   silently not in force for every runtime. A second copy of the list anywhere else is also a FAIL
   — it drifts, and the person goes on believing a rule applies (`rules/multi-agent.md`).
   `python3 tools/check_engine.py` proves both.
3. **The base is one thing.** The repository root is the base root, `projects/` is inside it, and
   nothing important sits outside. A `projects/` folder beside the base instead of inside is a FAIL:
   nothing there can ever reach the person's phone.
4. **The base can reach their other devices.** Run `python3 tools/sync.py status`. No remote at all
   is a FAIL — their base exists on one machine only. A remote reported **PUBLIC** is a FAIL
   before anything else: everything the person has ever saved is readable by anyone, and the engine
   asserted "private" only once, at creation. A visibility it could not establish is reported as
   unverified, never as private. Unsaved work or changes that never went out
   is a WARN with what is sitting here. More than one branch is a WARN
   (`rules/device-sync.md`).
5. **The machinery still works.** `python3 -m unittest discover -s tools/tests` passes. A failure
   here is a FAIL naming the test: something in this base's own tooling is broken, and it will
   surface as a lost save or a silently empty update rather than as an error.
6. **Sessions catch up on their own, and an ending session saves.** `.claude/settings.json` runs
   `tools/sync.py session-start` at session start and `session-end` when one closes, and `python3`
   is available to run both. Missing either is a WARN, not a FAIL — the canon still requires you
   to do it by hand, and the end-of-session hook is not a guarantee (`KNOWN-LIMITS.md`).
7. **Every project has a contract.** Each directory under `projects/` has `AGENTS.md`, a
   `CLAUDE.md` importing it, and its own `.claude/`. A project without one is a WARN naming it —
   the next session that opens it starts blind (`doctrine/project-home.md`). Each is also a row in
   `projects/_index.md`; a project missing from the index is the same WARN.
8. **The engine half can still be updated.** `.engine-manifest.yml` and `VERSION` exist, a remote
   pointing at the engine's own address is configured, and `version:` in the manifest matches
   `VERSION` and
   `.claude-plugin/plugin.json`. A base with no engine remote can never receive a fix — FAIL. A
   version mismatch between the three is a FAIL: the updater's own post-condition will refuse the
   next update.
9. **The engine half still runs everywhere.** `python3 tools/check_portability.py`. Every file the
   engine ships is checked against the machine-checkable clauses of `rules/cross-platform.md` — a
   bash 4 builtin, a GNU-only flag, a hardcoded path from one machine, text read without an
   encoding, a native command that a stop-on-error PowerShell turns into a crash. A finding here is
   a FAIL naming the file, line and clause: something in an engine path was edited into a shape that
   works on this machine and nowhere else, and it will be replaced at the next update anyway.
10. **Every pointer lands somewhere.** `python3 tools/check_engine.py` also resolves each
    reference naming a document and a section inside it, in every engine-owned file. A citation from a
    remembered heading rots on the first rewrite and then points confidently at the wrong
    paragraph, which is worse than no pointer (`rules/present-not-history.md`). A break is a FAIL
    naming both ends.
11. **Nothing personal sits in an engine path.** Spot-check the paths the manifest lists under
    `engine:` for anything the person or their agent wrote — it survives exactly until the next
    update (`doctrine/engine-ownership.md`). Any find is a FAIL naming the file and its real home.
12. **Indexes present.** `knowledge/_index.md`, `activities/_index.md`, `tools/_index.md`,
    `tools/_engine.md` and `projects/_index.md` exist and parse.
13. **MCP wrapped.** Every local MCP server (Docker / npx / native) in the agent's MCP config routes
    through `tools/mcp-wrapper.js`. An unwrapped local server is a FAIL
    (`doctrine/tool-vs-instrument.md`). Remote / SSE / URL servers are exempt.
14. **Profile ready.** `profile.md` exists and has a `Language:` value.
15. **No drift.** Anything the canon requires but the base lacks (a rule file missing, a dead
    pointer, a person's fact sitting in an engine-owned path — `doctrine/engine-ownership.md`) → WARN with
    the specific gap.

## Output

A short PASS/WARN/FAIL list in the person's language, then a one-line verdict. Never mutate.

## The family boundary

This is a family verb: its name covers everything installed under the Minder name, and today it
reaches exactly one of those things — this base. Anything else the person runs from the family,
Minder Memory included, is not examined here and has no health check of its own to send them to yet.

So the verdict says WHAT was examined. Never a bare "healthy", never silence: the report names the
base as its subject and says plainly that nothing else under the Minder name was looked at. A green
verdict a person reads as covering their whole setup is worse than no verdict, because it stops them
looking.
