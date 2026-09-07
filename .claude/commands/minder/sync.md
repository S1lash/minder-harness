---
description: Bring the base in step with the person's other devices — pick up what changed elsewhere, and save and send out what changed here. Reports in plain language, never in git words.
---

# /minder:sync

Put this base back in step across every surface the person uses. The contract is
`rules/device-sync.md`; the mechanics are `tools/sync.py`. This command is the manual entry
point — the same thing you do on your own at the start of a session and after a chunk of work.

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

1. **Read the state** — `python3 tools/sync.py status`. It reports the branch, whether anything
   here is unsaved, how far apart the two sides are, and the one action required.
2. **Do what it says**, following `rules/device-sync.md`:
   - behind, nothing unsaved → `python3 tools/sync.py pull`, then say nothing about it;
   - unsaved work here → propose saving it in one plain sentence, then
     `python3 tools/sync.py save "<why this change exists>"`;
   - both sides moved → `pull`, resolve anything overlapping by reading what it means, then save;
   - no remote at all → tell the person their base lives on this machine only, so their phone
     cannot see any of it, and offer to fix it.
3. **Report in one line, in their words.** Never "pulled / pushed / merged / branch" — say what
   happened to *their* things: "picked up what you did on your computer", "saved — it's on your
   phone now".

## The family boundary

This is a family verb: its name covers everything installed under the Minder name, and today it
reaches exactly one of those things — this base. Anything else the person runs from the family,
Minder Memory included, keeps its own copy on its own schedule and is not carried between devices
by this command.

So the report says WHICH half moved. Never a bare "in step", never silence: one plain line that the
base is in step and that nothing else under the Minder name was part of it. Telling somebody their
devices agree, when only one of two things was checked, is the failure this whole command exists to
prevent.

## Not this command

- The person asks why two devices disagree → same steps, but answer the question first: the
  usual cause is work left unsaved on the other machine.
- Setting the base up for the first time → `/minder:harness:init`.
