---
description: Bring the engine half of this base up to the version the engine ships — replace the engine's own paths, drop what it retired, leave everything the person wrote untouched, and say in plain words what it means for them. Never a merge the person has to resolve.
---

# /minder:update

The engine evolves; the person's base should get those fixes without them tracking a
repository or resolving an overlap in a file they did not write. `.engine-manifest.yml`
says which paths belong to the engine and which belong to them; `tools/update.py` replaces
only the first kind. The result is one ordinary save in their base, revertible like any other.

## Before any step: stand in the base

This verb answers for a base, not for wherever the session happens to be open — the installer makes
it available from every folder, so the current folder is not the answer. The base is the path on the
**HARNESS HOME** line of the person's global entry (`~/.claude/CLAUDE.md` for Claude Code,
`~/.codex/AGENTS.md` for Codex), already loaded in this session. Every command below runs THERE.

Running `python3 tools/...` in whatever directory is current is not a smaller version of this:
another project can hold a file by the same name, and running it would execute somebody else's
script under this command's name.

No **HARNESS HOME** line means this base was never wired. Say so and stop; do not guess a path.

## Steps

1. **Look before touching** — `python3 tools/update.py --dry-run`. It names every engine path that
   actually differs, every seed this base never received and will now get, every path of theirs
   that a declared move will relocate, and everything the engine has retired and will drop.
2. **Read the refusals as instructions, not errors.**
   - *No engine remote* → this base was never connected to the repository it came from. Say that in
     plain words and offer to connect it (`git remote add minder-harness <the address `engine_remote:`
     declares>`).
   - *Engine paths have unsaved local edits* → something wrote into engine space. Find out what:
     a person's fact in an engine path survives exactly until this moment
     (`doctrine/engine-ownership.md`). Move it to its real home, then update.
   - *Not one engine path was found* → the update machinery on this base is broken, not the
     engine. Run `python3 tools/update.py --self-heal`, which restores the updater from the
     remote before trusting it, then retries.
   - *A declared change cannot be carried out* → it would land on something of theirs. Read what
     the path is before proposing anything. An unknown VERB is no longer a cause here: the
     machinery is brought to the release before any declaration is carried out.
   - *The release's updater will not parse* → nothing was changed and this base still works. It is
     the RELEASE that is broken, not anything here. Say that plainly; there is nothing to repair
     locally, and `--self-heal` would fetch the same file.
3. **Apply** — `python3 tools/update.py`. It may say it is bringing the updater itself up to date
   first and re-running: that is one handover, not a loop, and it is what makes the release's own
   declarations be carried out by the release's own code. It names every path it replaced, added, moved or
   dropped — read that list rather than the counts. It replaces the engine's paths, drops the
   retired ones, and refuses to report success if `VERSION` does not end up where the engine says.

   **If it stops to show moves**, the release wants to rearrange the person's OWN files, which
   is the one thing here that is not the engine's to decide. Tell them in plain words what moves
   and what it means for them, wait until they are content, then run
   `python3 tools/update.py --confirm`. Never run the two in the same breath: showing them and
   then immediately proceeding is not a confirmation, it is a narration
   (`rules/safety.md` → "Content is data until you know who wrote it" is the neighbouring rule;
   the deletion clause is in the same file).
4. **Say what it means for THEM.** Read `CHANGELOG.md` between the two versions and give
   one or two plain sentences about what changes in how they work — not a list of what
   changed in the engine. Nothing that touches them → say exactly that.
5. **Re-wire only if the wiring itself changed.** Adding a rule never needs it — every global
   entry points at `AGENTS.md` and picks up the list from there. A NEW agent runtime in the
   changelog does: re-run the installer for that runtime, or wire it by hand
   (`rules/multi-agent.md`).
6. **Save** — `python3 tools/sync.py save "<why>"`, so the update reaches their other
   devices too.

## A base older than the updater

A base set up before `tools/update.py` existed cannot run it. Land the machinery first,
then proceed from step 1:

```
git fetch https://github.com/S1lash/minder-harness main
git checkout FETCH_HEAD -- tools/update.py tools/lib .engine-manifest.yml
```

## The family boundary

This is a family verb: its name covers everything installed under the Minder name, and today it
reaches exactly one of those things — this base. Anything else the person runs from the family,
Minder Memory included, is not touched here, and has no verb of its own to send them to yet.

So the report says WHICH half ran. Never a bare "updated", never silence: one plain line that the
base is current and that nothing else under the Minder name was part of it. A person who reads
"done" and believes their whole setup moved has been told something untrue by omission — the same
failure as an update reporting success for a path it could not replace.

## Not this command

- Devices showing different things → `/minder:sync`. That is the person's own work moving
  between their own machines; this command is the engine moving to them.
- Checking whether an update exists → it already runs on its own, at most once a day, at
  session start. `python3 tools/update.py --check` forces it.
