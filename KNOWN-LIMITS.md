# What Minder Harness cannot do yet

> Engine-owned and honest. A limit that is written down is one an agent can work around and a person
> can decide about; one that is not is a surprise on somebody else's machine.

- **`install.ps1` has never been executed.** What stands behind it is a line-by-line audit and
  `WindowsInstallerTests` in `tools/tests/`, which guards what a read can prove — the
  byte-order mark, the file encodings, that no native command runs outside the error-handling
  helper, that every variable it reads is one it set, and that its prompts, health checks and
  engine-remote logic match the shell installer's exactly. None of that proves it runs. One
  run on a real Windows machine is the outstanding item.
- **Nothing removes what the installer placed.** There is no uninstaller: the links in
  `~/.claude/commands/minder/`, the managed blocks in the global agent entries, and the base itself
  are removed by hand. That directory is SHARED with sibling products under the same name, so
  removing it wholesale takes theirs with it — `.minder-harness-owned` lists the three files that
  are this engine's to delete.
- **A family command linked on Windows may be a copy, and a copy goes stale silently.** The
  installer links `/minder:update`, `/minder:sync` and `/minder:doctor` into
  `~/.claude/commands/minder/` so they work from any folder. A symbolic link needs Developer Mode
  or an elevated shell on Windows, so where that fails the installer copies instead and says so.
  A copy does not follow the base, so an update that changes one of those three leaves it behind
  until the installer is run again — which now refreshes it, because a record of what the installer
  placed (`.minder-harness-owned`) is what tells its own copy apart from somebody else's file.
  Nothing detects the drift in between.
- **What counts as disposable is a fixed list of NAMES.** Both passes that can destroy something
  of the person's ask whether anything of theirs is in the way — a retirement, because it deletes
  the whole path; an adoption, because the engine's version is written straight over whatever is
  sitting there. Both consult untracked AND ignored content rather than trusting the ignore rule,
  because `.gitignore` says "do not version this" and never "this is disposable". What is skipped
  is a literal list — `__pycache__`, `.DS_Store`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`,
  `.pyc`, `.pyo`, `settings.local.json` — so a tool that leaves some other regenerable artefact at
  one of those paths refuses the update on every run until the list learns the name, and the base
  cannot converge meanwhile. Widening the list is a deliberate edit, never a default inherited
  from a flag.
- **An engine path the person edited and COMMITTED is replaced without warning.** The updater compares
  the working tree, so it catches an unsaved edit and stops; an edit that is already in their
  history reads as clean and is overwritten, or deleted if the path is retired. It is recoverable —
  it is in their own history, and the update names every path it drops — but nothing announces at
  the time that what went was theirs. Editing an engine path is the underlying mistake
  (`doctrine/engine-ownership.md`), and this is what it costs.

- **Nothing here knows what a secret is, and the base pushes on its own.** `rules/device-sync.md`
  has the agent saving small and often — on its own authority where nobody is there to ask — into
  a repository that is private but is still a remote. A key, a token or a connection string
  written into `knowledge/` or a project note goes out with everything else, and no gate, rule or
  tool looks for one. The private-by-default repository is the only thing standing between that
  and a public leak, and "private" is a setting somebody can change later.

  This is a deliberate gap, not an oversight: secret hygiene is being designed separately. Until
  it lands, treat the base as somewhere secrets do not go, and say so plainly to anyone setting
  one up. A `.gitignore` entry for `.env` is NOT the fix and is deliberately absent — it would
  cover the one place a secret usually is not, and buy a false sense of protection for the many
  places it might be.
- **Deploying anything is out of scope.** The base holds what a person builds, and knows nothing
  about running it: no home for infrastructure facts (a VPS, a domain, an access path), no deploy
  flow, nothing that would let a non-technical person put a project online from their phone. That
  was in the original intent for this engine and is not in it. It is blocked on the same thing as
  the item above and for the same reason — infrastructure facts ARE credentials, mostly, so the
  home for them cannot be designed before the rule about what may be written down.
- **A change to a seed reaches nobody who already has it.** `template:` files are created when
  missing and never rewritten, which is what keeps a person's own rows safe. So the engine's half of a
  seed is frozen at their clone date. Every seed is therefore kept thin, with anything the engine needs
  to keep current living in an engine file the seed links to, and `check_engine.py --authoring` fails a
  release that edits a seed which already shipped.
- **Content inside the person's own files cannot be reshaped.** `migrations:` carries a path that
  has to move; it has no verb for rewriting what is in a file, because that is the person's writing
  and only they or their agent should touch it. An engine change that needs it is the trigger to design
  that verb, not to improvise one.
- **Global agent wiring is reported, not repaired.** An update detects a runtime whose global entry
  no longer names this base and says so; re-running the installer for that runtime is a person's
  decision, because it writes outside the folder they chose.
- **`--self-heal` repairs an updater that still loads, not one that will not parse.** It is a
  mode inside `tools/update.py`, so a corruption severe enough to break the file — a half-written
  save, a merge conflict left in place — crashes before the flag is ever read, and the person sees
  a python traceback they cannot act on. The recovery for that case needs no python and no working
  updater: `git fetch https://github.com/S1lash/minder-harness main` then
  `git checkout FETCH_HEAD -- tools/update.py tools/lib .engine-manifest.yml`, run in that order
  and immediately — the fetch is what puts the engine within reach of the checkout, any other fetch
  in between replaces what `FETCH_HEAD` names, and the two lines overwrite those three paths. An agent
  present in the session runs it; the boundary is stated here because nothing in the traceback
  says which side of it you are on.
- **Nothing can guarantee a save before an ephemeral session is reclaimed.** A `SessionEnd` hook
  now saves whatever is still unsent, which covers the endings a session announces — closed,
  cleared, signed out. A container reclaimed on inactivity, a dropped connection, a crashed tab
  announce nothing, and no hook fires there; the documented budget for `SessionEnd` starts at 1.5
  seconds. So the rule carries the weight it always did: on a surface whose copy does not survive,
  save as you go rather than at the end. The hook is the floor under that habit, not a replacement
  for it — and in a runtime with no hooks at all, it is only the habit.
- **Two capabilities exist for Claude Code and for nobody else.** The session-start catch-up and
  the daily update check are `.claude/settings.json` hooks; the six `/minder:*` procedures are
  commands only there. `rules/multi-agent.md` now tells every other runtime to run the two scripts
  itself and to read the command files as procedures — but that is an instruction an agent
  follows, not a mechanism, and nothing detects a Codex session that never did. A skill has the
  same shape: `.claude/skills/<name>/SKILL.md` is a readable procedure everywhere and an invocable
  capability in one place.
- **Cursor is wired by hand, once.** It has no scriptable global rules file, so both installers
  write a ready-to-paste snippet and print a manual step. The snippet points at `AGENTS.md`, so a
  rule added later still reaches it — but a base whose owner never pasted it is canon-free in
  Cursor, and nothing detects that. Claude Code and Codex are wired automatically.
- **The portability gate reads code, so it can be fooled by code that hides.** It is a static
  scanner, and three shapes are deliberately out of reach rather than accidentally missed: a
  construct split mid-word across a shell continuation (`map\` + newline + `file`), a command name
  assembled at runtime from a variable, and a path built by string interpolation
  (`f"/home/{user}/base"` — usually not the hardcoded case at all). Chasing any of them would cost
  more precision than it buys, and the honest limit is that a green gate means "nothing recognisable
  is wrong", not "this is portable". A person's own review is still the outer layer.
- **A shipped file the tokenizer cannot parse falls back to line-by-line reading.** A `.py` that
  will not tokenize is a bigger problem than this gate, and it degrades to the weaker analysis
  rather than silently scanning nothing — but its docstrings are then matched as code, which shows
  up as false findings and not as silence. That is the intended direction to fail in.
- **Nothing runs the gates on its own.** There is no CI: the tests, `check_engine.py` and
  `check_portability.py` run when a person or an agent runs them, and the discipline that they get
  run before a release lives in `doctrine/engine-ownership.md` and in `/minder:doctor`. Every gate
  here is therefore only as good as the habit of invoking it, and a release pushed without one is
  refused by nothing.
- **`tools/mcp-wrapper.js` has no behavioural test.** It is the one shipped executable nothing
  exercises — the suite is python, and the wrapper only matters against a real MCP server holding
  a real child process. It is read by the portability scanner and by nothing else.
