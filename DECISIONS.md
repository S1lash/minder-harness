# Decisions — the durable choices behind Minder Harness

> Why Minder Harness is built the way it is: what was chosen, what else was considered, and why this
> one. Engine-owned, so an update carries it to everyone and it never freezes at somebody's clone date.
>
> The PERSON's decisions live in their own `knowledge/decisions.md`, which no update touches. Two
> files because they have two owners — an engine fact in a person's file is a copy no update can ever
> correct (`doctrine/engine-ownership.md`).
>
> **Present-not-history EXCEPTION** (`rules/present-not-history.md`): the evolution and rationale of
> a decision IS the content here. Everywhere else states only the current state and links here.

## 2026-09-08 — The updater replaces itself before the passes that delete

**Chosen:** an update fetches, then brings `tools/update.py` and `tools/lib/` to the release,
re-executes itself once, and only then runs the passes that replace, move and delete. The
re-executed process carries a hidden flag so the refresh happens at most once per run.

**The manifest is deliberately NOT handed over.** It is the thing being compared: the run reads the
incoming manifest and measures it against the one this base still has, and that difference is how a
path the release ADDS is recognised as new and adopted in the same run. Replacing it first makes
both sides the same document, every addition reads as "already here", and the release lands half
applied while reporting success. `--self-heal` still restores it, because a base being repaired by
hand has no comparison left to protect.

**Alternatives considered:** leaving the previous version to carry out the new release's
declarations, with `--self-heal` as the manual repair; importing the new modules into the running
process instead of re-executing; refreshing only when the release says the machinery changed.

**Why:** the manifest read is the INCOMING one, and the code reading it is whatever is on disk. So
`retired:` and `migrations:` — the two passes that DELETE and MOVE a person's paths — were carried
out by the version BEFORE the one that declared them. A fix for either reached a base one run after
the release that needed it, which is the run after the damage. Python holds the modules it already
imported, so a fresh process is the only way the new code actually runs; the flag is what makes it
a handover rather than a loop.

Three edges, each answered rather than discovered:

- **Their edits come first.** The machinery is made of engine paths like any other, so the dirt
  check for those paths runs BEFORE the refresh. Without it the refresh would destroy an
  uncommitted edit one step ahead of the check that exists to catch it.
- **A release whose updater will not parse is refused whole.** Landing it would leave a base that
  cannot update again and cannot repair itself — `--self-heal` fetches the same release. Nothing
  is changed instead, and the person is told the release is what is broken.
- **A preview previews.** `--dry-run` never rewrites the machinery, and says so, because the run
  it describes is the one the CURRENT updater would perform.

What this does NOT fix, so nobody looks for it here: an updater corrupted badly enough not to parse
never reaches any of this — python fails on import, before a flag is read. That is `--self-heal`,
run by hand, and it stays.

## 2026-09-07 — Commands sit at two levels, and only this engine ships the upper one

**Chosen:** `.claude/commands/minder/` holds the verbs that answer for everything under the Minder
name — `update`, `sync`, `doctor`; `.claude/commands/minder/harness/` holds the ones about this base
alone — `init`, `add-skill`, `project-init`. The installer links the upper three into the person's
`~/.claude/commands/minder/`, one file at a time. **Only this engine ships that upper level.** A
person who runs a sibling product and not this one has no family verbs at all, and that asymmetry is
deliberate.

**Alternatives considered:** mirroring the sibling's shape, so every product owns `product:verb` and
nothing sits above them; keeping all six under `minder/harness/` and adding the family level later;
having each product ship the family level so whoever is installed provides it.

**Why:** the path IS the command's name, and a name is a value other systems store — a person's
habit, a link, somebody else's document. Moving one after installations exist is a break nobody can
repair from here, which is the same reasoning that made the address the engine's only movable
identity. With no installed base, this is the one moment the layout is free.

- **Not a mirror of the sibling**, because the products are not peers in use. A person lives in
  their base and reaches into memory without opening it, so the verb they run daily should be the
  short one. A mirrored scheme charges length for the common case and leaves the "do all of it"
  action with no name at all.
- **Not shipped by both**, because `~/.claude/commands/minder/` is one directory shared by every
  product under the name. Two products writing `minder/update.md` into it means the second install
  wins, silently. One owner, and the directory itself is never linked or replaced — only the three
  files, so a sibling's own subdirectory in there survives.
- **The upper verbs reach one thing today, and say so.** Each carries a "family boundary" section
  and a test that fails if it is missing or names a sibling command that does not exist. A verb
  whose name promises everything and delivers half is only honest if it says which half ran.

**Detection is deliberately absent.** Nothing here scans for what else is installed, keeps a
registry, or reads a sibling's files. Any such registry becomes a second source of truth about a
thing it does not own, and diverges without a word. The seam where detection will attach is the
family boundary section of each of the three commands: today it states the limit in prose, and it is
where a real answer replaces a fixed one. Whoever builds it owns the question of what a cloud
session — which never loads `~/.claude/` — can see at all.

## 2026-09-07 — What the engine may treat as an identity, and what it may not

**Chosen:** the engine identifies itself by exactly one value an update can move — the address
`engine_remote:` declares. Three values that look like identities are treated as labels it never
depends on: the local NAME of the engine's git remote, the marker on the managed block in a person's
global agent entry, and the marketplace name.

**Alternatives considered:** treating the remote's configured name as the contract; adding a
`migrations:` verb able to rewrite a marker in a file outside the base; carrying a table of former
values inside the engine so that any of them could be moved later.

**Why:** a value another system stores and looks you up by cannot be moved by shipping anything. The
remote's name lives in each base's git config; the block marker lives in `~/.claude/CLAUDE.md` and
`~/.codex/AGENTS.md`, outside every repository; the marketplace name lives in a registry the engine
does not own. No update reaches any of them. So each is either a label — cosmetic, and replaced only
when the person re-runs the installer — or a contract that can never be corrected once bases exist.
It cannot be both, and choosing "contract" is choosing a break nobody can repair from here.

- **The address moves.** It is the one identity the engine publishes, and a base is reconciled to it
  at the end of a successful update.
- **The remote's local name does not.** `resolve_remote` matches each configured remote's URL
  against the declared address, and falls back to a name only when the manifest declares no address
  at all. Where an address IS declared and nothing matches it, the answer is "no engine remote
  here" — never "try a name". Picking by name is how somebody's own repository gets checked out over
  their engine paths and reported as a success.
- **The block marker does not.** Only the installer writes those files, and `rules/safety.md` puts
  changing anything outside the base behind the person's say-so. An update REPORTS a global entry
  that no longer names this base, and edits none.
- **A `migrations:` verb for any of this was rejected.** Its one verb moves paths, and none of these
  is a path; and an unknown verb refuses the whole update on every base that has not yet received
  the code defining it — a hard failure paid by everyone, to move a cosmetic value.

**What this cost, which is the part worth keeping.** Holding that line exposed the updater ignoring
`git checkout`'s exit status: it counted a path as replaced, and the retirement pass then deleted the
copy that was still in place, leaving a base with neither and an update that reported success. It
stops at the first failure now, before anything is deleted, and says what is in the way.

## 2026-08-30 — The engine is identified by its address, never by a name

**Chosen:** `tools/update.py` finds the remote to update from by comparing each configured
remote's URL against `engine_remote:` in the manifest, falling back to the conventional name only
when the manifest declares no address. `install.sh` and `install.ps1` already did the same when
deciding which remote is the engine's.

**Alternatives considered:** keeping the remote's NAME as the contract; declaring a rename as
a `migrations:` operation; asking the person to re-run the installer after a rename.

**Why:** the remote's name lives in each base's git config. No manifest section reaches it and no
clone carries it, so it cannot be changed by shipping anything — which means a name used as the
contract can never be corrected once bases exist. Renaming the engine as a product would have cut
off every base already in the world, and the repair could only travel through the channel it had
just broken. `migrations:` cannot express it either: its one verb moves paths, and a remote is not
a path. Asking the person to re-run an installer puts a structural chore on them, which the
stewardship rule forbids outright.

An address is the one identifier the engine publishes and can move on purpose — `reconcile_engine_remote`
already stages exactly that, one release ahead of the move.

The part that took the design work is not the rename at all: **every base has two remotes, and one
of them is the person's own private copy.** Matching an address loosely, or picking the first
remote configured, replaces a base's engine paths out of the person's own repository — which looks
like a successful update and silently corrupts the standard. So the comparison normalises the two
spellings git actually produces (a trailing `.git`, a trailing slash, case) and matches nothing
else, and the test is written with the engine under `upstream` so that git lists the person's
`origin` first.

**What this does NOT solve, on purpose.** The engine's own *name* is still written into the plugin
manifest and the `/harness-*` command filenames. Both are `engine:` paths, so a rename ships as an
ordinary replacement plus `retired:` lines. Only the remote needed a mechanism, because only the
remote lives somewhere an update cannot reach.

## 2026-08-30 — Portable scope is read from the manifest, not judged

**Chosen:** `rules/cross-platform.md` derives its two tiers from `.engine-manifest.yml`. Tier 1 is
`engine:` plus `template:` — exactly what an update writes onto somebody else's disk — held to the
letter and gated by `tools/check_portability.py`. Tier 2 is everything the person wrote, held to the
spirit and never gated.

`template:` beats `exclude:` where they overlap. A seed that lands inside the person's space is
still something the engine ships: `update.py` seeds every template regardless of `exclude:`, so reading
the overlap the other way would let one manifest mean two different things to its two readers — and
the files it ships would reach strangers unchecked. Where a seed lands says nothing about who wrote
it.

**Alternatives considered:** a hand-kept list of "files that must be portable"; a marker comment in
each file declaring its tier; holding the whole repository to one standard.

**Why:** the distinction that matters is already recorded, and recording it twice is two truths that
diverge. A second list would need updating in the same edit as the manifest and would silently not
be; a marker comment puts the answer in the file being judged, which is exactly where a wrong answer
is least visible. Holding everything to one standard is the failure both directions: gate the
person's own scratch script and the gate becomes noise they route around, exempt the engine's installer
and the rule stops covering the only files that reach a stranger.

The consequence worth naming: adding a path to `engine:` silently widens what the gate checks. That
is intended — the manifest entry IS the decision to ship it — but it means a release can fail on a
file the author never thought of as shipped. That failure is correct and is the point.

## 2026-08-30 — Canon clauses have IDs, not section numbers

**Chosen:** the machine-checkable clauses of `rules/cross-platform.md` are named `[CP-1]`..`[CP-6]`
in the prose, cited by every rule in `tools/lib/portability.py`, and bound in both directions by
`check_clause_ids` in `tools/lib/enginechecks.py`: a clause the canon defines that no mechanism enforces fails,
and a gate rule citing a clause nobody wrote fails.

**Alternatives considered:** citing section headings; citing section numbers; citing nothing and
letting each gate message stand alone.

**Why:** a gate has to be able to say which promise was broken, or the person reading the failure
has only a regex and no contract. Headings and numbers both move — `present-not-history.md` requires
rewriting a rule whole, so paragraphs are expected to move — and a citation that rots points
confidently at the wrong paragraph, which is worse than none. An ID is a name the rewrite carries
along.

The half that is easy to miss is the reverse direction. Enforcement drifting out from under a clause
is the failure nobody notices: the rule still reads as guarded, the gate still passes, and the only
evidence is a check that no longer exists. Binding both ways makes deleting a rule from the scanner
a release failure until the clause is deleted from the canon too.

**Not generalized further on purpose.** Only `cross-platform.md` carries IDs today, because only its
clauses are machine-checkable. A rule about judgement gains nothing from a citable name and would
gain a maintenance obligation.

## 2026-08-30 — No symlinks in the engine, except where a copy cannot do the job

**Chosen:** the installers create exactly one kind of symbolic link — the three family commands into
`~/.claude/commands/minder/` — and nothing else. Global agent wiring is a text block written into the
runtime's own entry point (`~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, Cursor user rules) naming the
base by path; everything else is a copy.

The exception exists because a copy there cannot be kept current by anything: the updater replaces
engine paths inside the BASE, and those three files live outside it, so a copy would be stale from
the first update and nothing would ever notice. It is bounded by the mitigations the rationale below
demands — the link is verified to BE a link after creation (Git Bash writes a text stub and exits 0),
a copy is the fallback when it is not, a record of what the installer placed is what allows that copy
to be refreshed later, and the shared `minder/` directory is never followed, replaced or removed.

**Alternatives considered:** linking the entry points at the base, which is what the engine did;
linking on POSIX and copying on Windows; keeping the link and documenting the Git Bash environment
variable that makes it real.

**Why:** a symlink is four different objects. Git Bash writes a text stub containing a path unless
`MSYS=winsymlinks:nativestrict` is set, so the file looks right and reads as garbage. Windows needs
Developer Mode or elevation to create one at all. `Test-Path` answers True for a link whose target
is gone — it reads the link's own attributes and never resolves it — so a dangling link passes as
present and whatever reads it gets nothing. `Remove-Item` on a directory link deletes the directory
it points at. Each of those is a silent
half-install on a machine the author cannot see, and the person hits it as "my agent stopped knowing
about my base" with nothing to read.

The thing given up is real and small: an edit to a linked file used to be live everywhere at once,
and a copy has to be rewritten by the updater. That is what the updater is for — it replaces engine
paths wholesale on every run — so the property was already being delivered by another mechanism.
A platform-agnostic engine does not get to depend on the one filesystem primitive that means something
different on each platform.

## 2026-08-23 — Safety is a sibling of git-safety, and authority does not relax it

**Chosen:** `rules/safety.md` — a hot rule covering irreversible and outward-facing actions that
are not git's: reading is free, look at the target before acting, deletions are confirmed, changing
anything outside the base needs approval, an external system is never touched without confirmation,
and an approval covers only what it covered. It names `git-safety.md` for the git half and is named
by it; neither repeats the other.

**Alternatives considered:** folding these into `git-safety.md`; leaving them scattered across
`harness-stewardship.md` and `working-method.md`, which is where they were.

**Why:** the discriminator in `harness-stewardship.md` already said "external or irreversible → ask"
and then never said what that meant, so it was a rule an agent could believe it was following while
deleting something. Folding it into git-safety would put two subjects in one file and make the
force list harder to find; scattering is what we had, and scattered safety is read as advisory.

The part worth arguing: an agent that owns a base holds the owner's authority
(`rules/device-sync.md`), so the asking steps become deciding steps — but three things do not
relax. Look-first binds because it is not a courtesy, it is how you discover the instruction was
written blind. Scope binds because authority over a base is not authority over everything the base
can reach. And an outward-facing action is never made free by the absence of a witness — the
absence is exactly what makes it unreviewable, which is why the autonomous owner records it in the
save message instead.

## 2026-08-23 — Offering discipline, but no catalog of capabilities

**Chosen:** the concierge pillar in `rules/harness-stewardship.md` gains how to offer — by
judgement, never by keyword; silence beats an offer that adds ceremony to work that did not need
it; one line, never a menu. No catalog file listing what the agent can do.

**Alternatives considered:** a `tool-suggestions.md`-style rule carrying a table of capabilities,
which is what the harness this was taken from does and does well.

**Why:** the table works there because one person maintains it against the skills they installed.
In an engine it would be a second source of truth for something the runtime already knows exactly — the
agent's own capabilities are in its context, and a shipped list would be wrong on the first base
that installs anything. The engine's own canon forbids precisely this. What generalises is not the
catalog but the trigger: the discipline moved, the table did not.

## 2026-08-23 — One canon list, in AGENTS.md; CLAUDE.md imports it

**Chosen:** `AGENTS.md` carries the canon list and is the contract every runtime reads.
`CLAUDE.md` is one `@AGENTS.md` import plus Claude-only notes. Installers point each runtime's
global entry at `AGENTS.md` rather than enumerating rules.

**Alternatives considered:** keeping full twins and checking them for parity, as before; making
`CLAUDE.md` the source and `AGENTS.md` the derived copy.

**Why:** the harness is agent-agnostic, so the agnostic file is the source and the runtime-specific
one is the adapter — not the other way round. The parity check existed only because we had written
the list twice; removing the duplicate removes the failure it was watching for, which is better
than watching for it. Claude Code reads `CLAUDE.md` and not `AGENTS.md`, and its own documented
answer to that is an import rather than a copy. A side effect worth having: relative imports resolve
from the file that contains them, so a global entry pointing at `AGENTS.md` picks up every rule
automatically and adding a rule no longer means re-running the installer anywhere.

## 2026-08-23 — An update replaces the engine's paths; it never merges

**Chosen:** `.engine-manifest.yml` declares every path as the engine's or the person's, and
`tools/update.py` checks out only the engine's, from the remote whose URL matches the declared address. Paths the engine dropped
are listed as `retired:` and deleted from every base on every update. Written in python rather than
shell.

**Alternatives considered:** merging from an upstream remote; a `.template`-suffix seed contract
extracted by a release step; a bash updater mirroring the engine this is modelled on.

**What replacement and retirement still cannot express, and what carries it instead:** a path in
the person's space that must move is declared under `migrations:`; the engine's own address is
reconciled from the manifest on every update, so moving the engine is staged rather than sudden; and
global agent wiring is detected and reported. What remains genuinely out of reach is content
INSIDE the person's files, and the frozen engine-half of a seed — both in `KNOWN-LIMITS.md`.

**Why:** the people running this will not track the engine's repository and cannot resolve a merge
overlap in a file they did not write. Replacing a declared set of paths makes an update an ordinary
save in their own base — revertible, explainable, and unable to conflict. Retirement is the half a
copy cannot express: the updater copies what the engine HAS, so without it every file the engine ever
removed sits on every base forever, offering a contract nothing honours. The `.template` suffix and
its release step exist to extract a public skeleton out of a live private instance; this engine is
authored public, so its seeds ship pristine under their live names and the whole extraction step is
unnecessary. Python over shell because the engine it copies had to defend a python-to-bash boundary
against CRLF-mangled paths and Windows rewriting `<ref>:<path>` — both of which turned a broken
update into a silent success. Removing the boundary removes the class, and one file runs everywhere
a shell pair would have to be kept in step.

## 2026-08-23 — Migrations are declared data, convergent, and have one verb

**Chosen:** a `migrations:` section in the manifest, currently one verb — `move <from> -> <to>`,
optionally carrying a note for the person. It runs after the checkout on every update, is
idempotent by construction, and refuses a verb it does not recognise. No ordered chain, no ledger.
Alongside it, two reconciliations that are not migrations at all: the engine's remote is set to the
address the manifest publishes, and stale global agent wiring is reported.

**Alternatives considered:** the ordered chain with `structural`/`heal` kinds and a ledger that the
engine this engine is modelled on uses; putting the logic in `update.py` as code; doing nothing and
forbidding the engine from ever moving anything in the person's space.

**Why:** the updater replaces itself mid-run while its old copy is already in memory, so code added
to it takes effect one update late — the manifest is re-read from disk after the checkout, so data
lands in the same run it ships in. A ledger needs a valid starting point that a base cloned long
ago has never had, and an ordered chain is strictly worse for a base that has been dark for a year;
re-running idempotent declarations converges from any version. One verb because a move is the case
that actually exists, and refusing an unknown verb rather than skipping it means an engine that adds a
second one never silently believes a change landed. Doing nothing was the previous position, and it
made "the engine must never rename anything a person owns" a permanent constraint rather than a choice.

## 2026-08-23 — Every project carries its own contract, written by the agent

**Chosen:** each project has `AGENTS.md` (the contract), a `CLAUDE.md` importing it, and its own
`<project>/.claude/knowledge/` and `<project>/.claude/decisions.md`. The agent writes it when the project is born and
repairs it when it drifts, unasked. It holds only what the code cannot tell you.

**Alternatives considered:** relying on the base's knowledge home for project facts; twin
CLAUDE.md/AGENTS.md files; asking the person whether they want documentation.

**Why:** a project is opened cold — a phone, a fresh clone, a headless run — with no history to
lean on. The person will never write this, will not notice it missing, and will not connect a bad
session to its absence. Keeping project facts in the base instead scatters them away from the code
they describe and makes them invisible to anyone who has only the project. The import bridge rather
than twins because Claude Code reads `CLAUDE.md` and other runtimes read `AGENTS.md`, and two
copies of one contract drift. The what-the-code-cannot-tell-you filter is what keeps the file from
becoming a stale restatement of the layout, which is worse than nothing because it gets believed.

## 2026-08-23 — The base is one repository, and everything built lives inside it

**Chosen:** a single repository whose root is the base. `projects/` sits inside it. A project moves
to its own repository only when the person asks, and `projects/_index.md` records that.

**Alternatives considered:** projects as a sibling folder outside the base (the previous layout);
git submodules; symlinks into separate repositories.

**Why:** a session opened from a fresh clone — a phone, a web session, an agent on a server — gets
exactly one repository and nothing else. Anything outside it does not exist there. Submodules leave
a non-technical owner stranded in a detached checkout the first time anything moves, and symlinks
survive neither a clone nor Windows. The cost is accepted knowingly: one history for the base and
the apps together, and a project cannot be made public without the base.

## 2026-08-23 — The base has one branch

**Chosen:** the person's base carries a single long-lived branch and no others. Branch-per-change
discipline stays, but only for repositories of code.

**Alternatives considered:** the general branch-first rule applied everywhere, as before.

**Why:** a branch is invisible on a phone and meaningless to someone who does not know the word.
Every extra branch in the base is a future "why is my phone showing something different", and the
person cannot diagnose it. Merges in the base are markdown the agent can read and reconcile, so the
protection a branch buys is not needed here.

## 2026-08-23 — Saving is proposed, not requested

**Chosen:** the agent brings the base up to date silently at session start, and proposes saving in
one plain sentence at the end of a chunk of work. After the first yes it keeps saving silently for
that session. Where nobody is in the loop, it saves on its own.

**Alternatives considered:** save only when the person asks (the previous rule); save fully
automatically with no consent at all.

**Why:** the owner of a base does not know the words for any of this and will not ask. Asking every
time is nagging; never asking takes the decision away from them. Splitting the two directions
resolves it — bringing changes in is not a choice anybody would make differently, so it is not a
question; sending work out is visible to them and stays theirs to allow. On a surface whose copy is
destroyed when the session ends, an unsaved session is simply lost work, which is what makes the
proposal urgent rather than polite.

## 2026-08-23 — The engine stays updatable; the line is drawn by path

**Chosen:** paths are owned either by the engine or by the person (`doctrine/engine-ownership.md`). An
update replaces engine paths wholesale and never touches person paths. The engine's own remote is kept under
its own name; `origin` is the person's private copy. Installing never deletes history.

**Alternatives considered:** fork-and-own with no upstream at all (the previous stance); merging
updates from an upstream remote.

**Why:** the engine is handed to people who will not track its repository and cannot resolve a merge
overlap in a file they did not write. Replacing a known set of paths turns an update into an
ordinary save in their own base — reversible, explainable, and impossible to conflict. Deleting
history at install destroyed the only link back to the engine and, on a second device, the person's
own past.
