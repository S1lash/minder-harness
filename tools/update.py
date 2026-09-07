#!/usr/bin/env python3
"""Bring the engine half of this base up to the version the engine ships.

An update is a REPLACEMENT, not a merge. `.engine-manifest.yml` says which
paths belong to the engine and which belong to the person; the engine's paths are
checked out from the engine remote, the person's are not touched, and the result
is one ordinary save in their own base — reversible like any other. Nobody is
ever asked to resolve an overlap in a file they did not write.

Written in python rather than shell on purpose. The engine this is modelled on
had to defend a python-to-bash boundary against CRLF-mangled paths and against
Windows rewriting a `<ref>:<path>` argument — both of which turned a broken
update into a silent success that exited 0 having applied nothing. Removing the
boundary removes the whole class, and one file runs on every platform instead of
a shell pair that has to be kept in step.

Modes
  (default)    fetch, replace the engine's paths, retire what it dropped, verify
  --dry-run    show what would change, change nothing
  --check      report whether a newer version exists; changes nothing
  --self-heal  restore the updater itself from the remote first, then re-run

The updater ships THROUGH the update, so a base carrying a broken copy can
never receive its own repair by the normal path. `--self-heal` is that path —
for a copy that still LOADS. A file python cannot even parse fails before the
flag is read, and no mode inside this file can help. That one is recovered
without python at all, and the command is the whole of it:

    git fetch https://github.com/S1lash/minder-harness main
    git checkout FETCH_HEAD -- tools/update.py tools/lib .engine-manifest.yml

Run those two in order and immediately: the fetch is what puts the engine within reach of the
checkout, and any other fetch in between replaces what FETCH_HEAD points at. They overwrite
those three paths, which is the point — nothing else is touched.
"""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple

if hasattr(signal, "SIGPIPE"):
    # Piping this into `head` closes the pipe early. That is the reader's
    # business, not a failure of the update — die quietly rather than dumping a
    # traceback over a report the person is reading.
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import gitrun  # noqa: E402
from lib import manifest as manifest_lib  # noqa: E402
from lib import migrate as migrate_lib  # noqa: E402
from lib import retire as retire_lib  # noqa: E402

DEFAULT_REMOTE = "minder-harness"
DEFAULT_BRANCH = "main"
NETWORK_TIMEOUT_SECONDS = 120
VERSION_FILE = "VERSION"
# Inside .git/, so no manifest section reaches it and nothing else can clean it up.
CHECK_CACHE = "minder-harness-update-check"
# Restored before the updater is trusted to read anything. Everything the
# update mechanism itself is made of.
SELF_HEAL_PATHS = ("tools/update.py", "tools/lib", ".engine-manifest.yml")
#: What the automatic handover brings forward: the CODE, and deliberately not the manifest.
#: The manifest is the thing being compared — the run reads the incoming one and measures it
#: against the one this base still has, and that is how a path the release ADDS is recognised as
#: new. Replacing it before the comparison makes both sides the same document, and every addition
#: reads as "already here". `--self-heal` still restores it, because a base being repaired by hand
#: has no comparison left to protect.
HANDOVER_PATHS = ("tools/update.py", "tools/lib")
MANAGED_BLOCK_MARKER = "MINDER-HARNESS"
PREFIX = "[minder-harness-update]"
# The line an agent is required to act on. One spelling, in one place: it is the contract
# between these scripts and whatever is reading their output.
DIRECTIVE = "YOU MUST:"


def git(*args, root: Path, timeout=None):
    """Run git in `root`. One binding of `gitrun.run`, so every call here shares its contract."""
    return gitrun.run(root, *args, timeout=timeout)


def git_ok(*args, root: Path, timeout=None):
    """Output when git succeeded, else None. Only where empty and failed mean the same thing."""
    return gitrun.ok(root, *args, timeout=timeout)


def ref_has_path(ref: str, relpath: str, root: Path) -> bool:
    return git("cat-file", "-e", "%s:%s" % (ref, relpath), root=root)[0] == 0


def ref_read_path(ref: str, relpath: str, root: Path):
    return git_ok("show", "%s:%s" % (ref, relpath), root=root)


def read_local_version(root: Path) -> str:
    path = root / VERSION_FILE
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def fail(message: str, *followups: str) -> int:
    print("%s %s" % (PREFIX, message), file=sys.stderr)
    for line in followups:
        print("  %s" % line, file=sys.stderr)
    return 2


def resolve_remote(remote: str, root: Path):
    """(name, url) of the remote this base updates from — found by ADDRESS, then by name.

    The name is a convenience, never the contract. The installer already identifies the engine by the
    address the manifest declares rather than by whether a name contains a particular word, and
    this is the other half of that: a base whose engine remote was set up under some other name, or
    whose engine is renamed as a product, still updates. Only the address is stable — it is the one
    thing the engine itself publishes and can move deliberately (`reconcile_engine_remote`).

    Falls back to the configured name ONLY when the manifest declares no address at all — a base
    whose contract predates `engine_remote:`, or one whose remote is a local path used for testing.
    Where an address IS declared and nothing matches it, the answer is "no engine remote here", not
    "try a name": the caller says so and names the one command that fixes it.
    """
    declared = manifest_lib.read_engine_remote(root)
    if declared:
        for name in (git_ok("remote", root=root) or "").split():
            url = git_ok("remote", "get-url", name, root=root)
            if manifest_lib.same_repository(url, declared):
                return name, url
        # Declared addresses and none of them matched. Selecting a remote by NAME here is what
        # the address check exists to prevent: a person whose own repository happens to carry
        # this name would have their base's engine paths checked out of their OWN repository, which
        # reports success and silently replaces the standard with whatever they keep there.
        return remote, None
    url = git_ok("remote", "get-url", remote, root=root)
    return (remote, url) if url else (remote, None)


# ---------------------------------------------------------------------------
# modes
# ---------------------------------------------------------------------------

def mode_check(root: Path, remote: str, branch: str, max_age: int) -> int:
    """Is a newer engine version out? Cheap, cached, and silent when there is nothing to say."""
    cache = root / ".git" / CHECK_CACHE
    if max_age > 0 and cache.exists():
        try:
            if time.time() - json.loads(cache.read_text(encoding="utf-8"))["at"] < max_age:
                return 0
        except (ValueError, KeyError, OSError):
            pass  # unreadable cache is not a reason to skip the check

    remote, url = resolve_remote(remote, root)
    if not url:
        return 0  # a base with no engine remote has nothing to check against

    if git("fetch", "--quiet", remote, branch, root=root,
           timeout=NETWORK_TIMEOUT_SECONDS)[0] != 0:
        return 0  # offline is not news

    try:
        cache.write_text(json.dumps({"at": time.time()}), encoding="utf-8")
    except OSError:
        pass

    here = read_local_version(root)
    there = (ref_read_path("%s/%s" % (remote, branch), VERSION_FILE, root) or "").strip()
    if there and here and there != here:
        print("%s a newer version of the engine is out: %s (this base is on %s)"
              % (PREFIX, there, here))
        print(DIRECTIVE + " mention it once, in one plain sentence, and offer to bring it in "
              "with /minder:update. Do not explain versions unless they ask.")
    return 0


def mode_self_heal(root: Path, remote: str, branch: str, argv: list) -> int:
    remote, url = resolve_remote(remote, root)
    if not url:
        # Apply refuses a remote that matches no declared engine address; self-heal must refuse the
        # same shape or it is the way around the refusal. It overwrites the updater, `tools/lib`
        # and the manifest — so fetching those from a remote that only happens to carry the
        # expected NAME replaces the machinery out of somebody's own repository.
        return fail(
            "no remote here points at the engine, so there is nothing safe to repair from.",
            "A remote named %r exists only if the person made one; the engine is recognised by the"
            % remote,
            "address `engine_remote:` declares, and none of the configured remotes matches it.",
            "Connect it first:",
            "  git remote add %s %s"
            % (DEFAULT_REMOTE, manifest_lib.read_engine_remote(root) or "<the engine's repository>"),
        )
    print("%s self-heal: restoring the updater from %s/%s" % (PREFIX, remote, branch))
    if git("fetch", remote, branch, root=root, timeout=NETWORK_TIMEOUT_SECONDS)[0] != 0:
        return fail("could not reach the engine remote to repair from.")
    ref = "%s/%s" % (remote, branch)
    for relpath in SELF_HEAL_PATHS:
        if ref_has_path(ref, relpath, root):
            git("checkout", ref, "--", relpath, root=root)
            print("  + %s" % relpath)
    print("%s self-heal: re-running the repaired updater" % PREFIX)
    rerun = [a for a in argv if a != "--self-heal"]
    return subprocess.run([sys.executable, str(Path(__file__).resolve())] + rerun).returncode


class Incoming(NamedTuple):
    """What the manifest being SHIPPED declares. Named so a typo is an error, not an empty list."""
    engine: list
    template: list
    exclude: list
    migrations: list
    retired: list


def incoming_sections(ref: str, root: Path) -> Incoming:
    """What the manifest being SHIPPED declares, not what this base already knew.

    The manifest is itself one of the paths an update replaces, so anything a release declares —
    a new engine path, a move, a retirement, a seed — is invisible to a run that only reads the
    copy on disk. Falls back to the local manifest when the ref carries none, which is the shape
    of a base whose engine remote points at something that is not the engine.
    """
    text = ref_read_path(ref, manifest_lib.MANIFEST_NAME, root)
    sections = {}
    for name in Incoming._fields:
        entries = (manifest_lib.parse_section(name, text) if text
                   else manifest_lib.read_section(name, root))
        sections[name] = [p.rstrip("/") for p in entries] if name == "engine" else list(entries)
    return Incoming(**sections)


#: What a tool regenerates and nobody grieves — every one of them a name the engine's own
#: `.gitignore` already declares. Narrow and explicit ON PURPOSE: everything NOT here is somebody's,
#: including things they told git to ignore. `.gitignore` says "do not version this", never "this is
#: disposable" — a key, a local config or a scratch draft is exactly the shape that lives under an
#: ignore rule and exists in no history anywhere.
DISPOSABLE_NAMES = ("__pycache__", ".DS_Store", ".venv", ".pytest_cache", ".mypy_cache",
                    ".ruff_cache", "settings.local.json")
DISPOSABLE_SUFFIXES = (".pyc", ".pyo", ".log")


def _is_disposable(entry: str) -> bool:
    """A path a tool regenerates, judged by name — never by whether git was told to ignore it."""
    parts = [part for part in entry.replace("\\", "/").split("/") if part]
    if any(part in DISPOSABLE_NAMES for part in parts):
        return True
    return bool(parts) and parts[-1].endswith(DISPOSABLE_SUFFIXES)


def their_loose_files(root: Path, relpath: str):
    """Every file under this path that exists in NO history — untracked or ignored — or None.

    The question `git diff` cannot answer: it compares tracked content, so a file the person made
    and never added is invisible to it. That file is the least recoverable thing in the base — not
    in the engine, not in their own history, nowhere — and both destructive passes below can reach
    it. `None` means nothing could answer, which is never the same as "there is nothing here".

    Ignored content is consulted and then filtered by NAME against `DISPOSABLE_NAMES`, because
    `.gitignore` says "do not version this" and never "this is disposable" — a key, a local config
    or a scratch draft is exactly the shape that lives under an ignore rule.
    """
    result = git("-c", "core.quotePath=false", "status", "--porcelain",
                 "--untracked-files=all", "--ignored=matching", "--", relpath, root=root)
    if result[0] != 0:
        # An older git without `--ignored=matching`. Ask the question it does understand rather
        # than treating an unanswered one as "clean".
        result = git("-c", "core.quotePath=false", "status", "--porcelain",
                     "--untracked-files=all", "--ignored", "--", relpath, root=root)
    if result[0] != 0:
        return None
    loose = []
    for line in (result[1] or "").splitlines():
        if not line.strip():
            continue
        if line[:2] not in ("??", "!!"):
            continue           # tracked: `git diff` answers for that, and answers it better
        entry = line[3:].strip().strip('"')
        if _is_disposable(entry):
            continue
        if not entry.endswith("/"):
            loose.append(entry)
            continue
        # git reports an untracked or ignored DIRECTORY as one line and says nothing about what is
        # in it, so an empty one and one holding somebody's key look identical here.
        for child in sorted((root / entry.rstrip("/")).rglob("*")):
            if child.is_file():
                child_relpath = child.relative_to(root).as_posix()
                if not _is_disposable(child_relpath):
                    loose.append(child_relpath)
    return loose


def retired_path_is_dirty(root: Path, relpath: str) -> bool:
    """Anything of the person's under a path about to be DELETED — tracked, untracked or ignored.

    The retirement pass removes the path with `rmtree`, so the question is the widest one there is:
    is ANYTHING of theirs under it. That is what makes this different from the engine-path question
    below, where the destructive act is a `checkout` and reaches far less.

    Tracked content is asked with `git diff`, which compares CONTENT: it applies the same
    `.gitattributes` conversion on both sides, so a working tree checked out with CRLF reads as
    unchanged — which it is. `git status` calls that file modified, and believing it refuses every
    update forever on a Windows checkout while `git diff` shows the person nothing at all.
    """
    if git("diff", "--quiet", "--", relpath, root=root)[0] != 0:
        return True
    if git("diff", "--cached", "--quiet", "--", relpath, root=root)[0] != 0:
        return True
    loose = their_loose_files(root, relpath)
    if loose is None:
        # Nothing could answer. A path about to be deleted is never assumed empty of their work.
        return True
    return bool(loose)


def their_files_the_checkout_would_write_over(root: Path, ref: str, relpath: str) -> list:
    """Their loose files that the engine's own version would land on top of.

    Narrower than the retirement question ON PURPOSE, and the difference is the destructive act:
    `git checkout <ref> -- <path>` writes the paths the REF holds and leaves everything else where
    it is, while `rmtree` takes the whole directory. So a file of theirs sitting inside an engine
    directory that the ref does not have survives an update untouched, and refusing over it would
    deadlock every base that ever collected a stray note under `rules/`.

    What it does NOT survive is sharing a path with the release — the shape that arrives the moment
    a release ADOPTS a path: until this run the path was the person's own space, so whatever is
    sitting there is theirs, and the checkout overwrites it with no diff to show and nothing said.
    """
    loose = their_loose_files(root, relpath)
    if loose is None:
        return [relpath]
    if not loose:
        return []
    listing = git("ls-tree", "-r", "--name-only", ref, "--", relpath, root=root)
    if listing[0] != 0:
        return []
    shipped = {line for line in (listing[1] or "").splitlines() if line}
    return sorted(set(loose) & shipped)


def dirty_engine_paths(root: Path, ref: str, engine_paths: list,
                       retired: list | None = None) -> list:
    """Engine paths carrying uncommitted local edits.

    A path whose working tree already MATCHES the remote holds no customisation
    — there is nothing there to lose — so it is not an abort. Without that
    carve-out a self-heal deadlocks the updater against itself: the repair makes
    those paths dirty, and the very next run refuses to proceed past them.

    A path this release RETIRES is excluded from that comparison, and without it the same
    deadlock returns by another door. An update that is interrupted between the checkout and
    the retirement pass leaves the new files in place and the withdrawn ones still sitting
    beside them — so the directory differs from the ref, and the difference is entirely files
    that are about to be deleted. Read as an edit, it makes the next run refuse, and a base
    interrupted once can never finish on its own. Convergence is the whole promise of running
    every declared change on every update; it has to survive the run being killed.
    """
    retired = retired or []
    dirty = []
    # The exclusion below cannot tell an interrupted update's untouched residue from a file the
    # person has been editing — both are "present here, absent from the ref". So each retired
    # path is asked directly FIRST, and only the clean ones are excluded. Getting this wrong
    # deletes work that is not in their history yet and cannot be recovered from anywhere.
    clean_residue = []
    for relpath in retired:
        if not (root / relpath).exists():
            continue
        if retired_path_is_dirty(root, relpath):
            dirty.append(relpath)
        else:
            clean_residue.append(relpath)
    excludes = [":(exclude)%s" % relpath for relpath in clean_residue]
    for relpath in engine_paths:
        # Asked FIRST, and deliberately outside the carve-out below. That carve-out reads "the
        # working tree already matches the ref, so there is nothing here to lose" — true of tracked
        # content and meaningless for a file in no history at all: it cannot match a ref it is not
        # in, and `git diff ref` never mentions it either way. Left to the carve-out, their file
        # would be waved through and then written over.
        if their_files_the_checkout_would_write_over(root, ref, relpath):
            dirty.append(relpath)
            continue
        unstaged = git("diff", "--quiet", "--", relpath, root=root)[0] != 0
        staged = git("diff", "--cached", "--quiet", "--", relpath, root=root)[0] != 0
        if not (unstaged or staged):
            continue
        if git("diff", "--quiet", ref, "--", relpath, *excludes, root=root)[0] == 0:
            continue
        dirty.append(relpath)
    return dirty


def reconcile_engine_remote(root: Path, remote: str) -> str:
    """Point the engine remote at the address the engine now publishes.

    The remote lives in git config, which no manifest section reaches and no clone carries. If the
    engine ever moves, a base still pointed at the old address cannot fetch the update that would have
    told it the new one — the repair ships only through the channel that is broken. Publishing the
    new address one release BEFORE the move closes that: every base adopts it while the old address
    still works.
    """
    declared = manifest_lib.read_engine_remote(root)
    current = git_ok("remote", "get-url", remote, root=root)
    if not declared or not current or declared == current:
        return ""
    if git("remote", "set-url", remote, declared, root=root)[0] != 0:
        return ""
    return declared


def stale_global_wiring(root: Path) -> list:
    """Global agent config that no longer names this base. Reported, never edited.

    `install.sh` writes a marked block into each runtime's global entry. Nothing re-runs it, so a
    base that moved, or one wired before the contract became `AGENTS.md`, keeps a block pointing
    somewhere else — and the canon then reaches that runtime from the wrong place, or not at all.
    """
    home = Path.home()
    expected = "@%s/AGENTS.md" % root
    stale, conflicting = [], []
    for relpath in (".claude/CLAUDE.md", ".codex/AGENTS.md"):
        entry = home / relpath
        try:
            text = entry.read_text(encoding="utf-8")
        except OSError:
            continue
        opened = text.count("BEGIN %s" % MANAGED_BLOCK_MARKER)
        if opened == 0:
            continue
        if opened > 1:
            # Two of our blocks in one file. The installer refuses this shape outright, and until
            # somebody resolves it the canon is in there twice with nothing to say which copy is
            # live — so it must not be the one state that passes here in silence.
            conflicting.append(str(entry))
        elif expected not in text and str(root) not in text:
            stale.append(str(entry))
    return stale, conflicting


def seed_missing_templates(root: Path, ref: str, declared: list) -> list:
    """Create the seed files this base never received; never touch one it already has.

    A template seeds at clone time and an update leaves it alone — that is what keeps a person's
    own rows safe. But a template ADDED after their clone therefore reaches them never, while the
    canon arriving in the same update names it as though it were there. Creating only what is
    absent keeps both properties: nothing of theirs is overwritten, and the file the rules point
    at exists.

    `declared` is the template list from the manifest being SHIPPED, not the one on disk. Reading
    the local copy made the promise above false in its own headline case: a seed introduced by
    this release is not in the manifest the base still has, so it arrived one update late — while
    the dry-run, which already read the incoming list, promised it now.
    """
    created = []
    for relpath in declared:
        if (root / relpath).exists() or not ref_has_path(ref, relpath, root):
            continue
        git("checkout", ref, "--", relpath, root=root)
        if (root / relpath).exists():
            created.append(relpath)
    return created


def enclosing_repository(root: Path):
    """The repository this base sits inside, when the base is not one itself.

    `git -C <base>` answers for whichever repository encloses the base, so a base with no `.git`
    of its own silently borrows another one — and an update would then check engine paths out over
    that repository's worktree and delete from it.
    """
    code, toplevel = git("rev-parse", "--show-toplevel", root=root)[:2]
    if code != 0 or not toplevel:
        return None
    return None if Path(toplevel).resolve() == root.resolve() else toplevel


def preview(root: Path, ref: str, engine_paths: list, incoming: Incoming,
            protected_before: list, version_before: str, version_upstream: str) -> int:
    """What an update WOULD do, said in the terms the real run uses.

    Extracted from `mode_apply`, where it was a second program inside the first — its own
    output vocabulary, its own refusal handling and its own early return, reachable only by
    spawning the script against a configured remote.
    """
    print("%s dry-run — would replace these from %s:" % (PREFIX, ref))
    for relpath in sorted(set(engine_paths) | set(incoming.engine)):
        if not ref_has_path(ref, relpath, root):
            continue
        # `-R` reverses the direction: without it this reads ref -> here,
        # so everything the update ADDS renders as a deletion.
        stat = git_ok("diff", "--stat", "-R", ref, "--", relpath, root=root)
        print("  - %s%s" % (relpath, "" if not stat else "\n      " + stat.replace("\n", "\n      ")))
    for relpath in incoming.template:
        if not (root / relpath).exists() and ref_has_path(ref, relpath, root):
            print("  + add %s (a seed this base never received)" % relpath)
    # The guards inside these two read `engine:`/`exclude:` from the manifest on disk, which
    # a real run reads only AFTER the replacement. A release that moves a path between
    # sections and migrates or retires under it in the same release would therefore preview
    # against one manifest and apply against another; a refusal is reported as a refusal
    # rather than crashing the preview.
    try:
        for move in migrate_lib.run(root, dry_run=True, entries=incoming.migrations):
            print("  > move %s to %s" % (move.source, move.destination))
    except migrate_lib.MigrationRefused as refusal:
        print("  ! a declared move cannot be previewed from this base yet: %s" % refusal)
    try:
        removed = retire_lib.run(
            root, dry_run=True, entries=incoming.retired,
            protected=sorted(set(protected_before) | set(incoming.exclude)))
    except retire_lib.RetirementRefused as refusal:
        print("  ! a declared removal names paths this base calls its own: %s"
              % ", ".join(refusal.trespassing))
        removed = []
    for relpath in removed:
        print("  - drop %s (the engine no longer has it)" % relpath)
    print("%s dry-run: %s -> %s. Nothing applied." % (PREFIX, version_before or "?",
                                                      version_upstream or "?"))
    return 0



def report(root: Path, remote: str, resolved: int, changed: int, absent: int,
           changed_paths: list, added_paths: list, seeded: list, removed: list,
           carried: list, version_before: str, version_after: str) -> int:
    """Say what happened, path by path, and what the agent must do with it.

    An overwrite the person cannot see is one they cannot object to, so this names every
    path rather than a count. Extracted for the same reason as `preview`: reporting is a
    different job from deciding.
    """
    moved_address = reconcile_engine_remote(root, remote)
    print("%s %d engine path(s) checked, %d changed, %d absent, %d added, %d dropped — %s -> %s"
          % (PREFIX, resolved, changed, absent, len(seeded), len(removed),
             version_before or "?", version_after or "?"))
    # Name every path, never just a count: an overwrite the person cannot see is one they cannot
    # object to, and `.claude/settings.json` is an engine path they may well have edited.
    for relpath in changed_paths:
        print("  ~ replaced %s" % relpath)
    for relpath in added_paths:
        print("  ~ replaced %s (an engine path this release introduced)" % relpath)
    for relpath in seeded:
        print("  + added %s (a seed this base never received)" % relpath)
    for relpath in removed:
        print("  - dropped %s" % relpath)
    if removed:
        # These are engine paths, so the engine withdrawing them is not a loss — unless the person had
        # edited one, which nothing here can see once the edit is committed. Say where it went
        # rather than leaving them to discover it.
        print("    (anything the person had changed in those is still in this base's own history)")
    for move in carried:
        print("  > moved %s to %s%s"
              % (move.source, move.destination, " — %s" % move.note if move.note else ""))
    if moved_address:
        print("  = the engine now lives at %s; this base follows it from the next update"
              % moved_address)
    stale, conflicting = stale_global_wiring(root)
    for entry in stale:
        print("  ! %s still points somewhere else — that runtime is not reading this base" % entry)
    for entry in conflicting:
        print("  ! %s carries this engine's block TWICE" % entry)
    if conflicting:
        print(DIRECTIVE + " tell the person plainly: that file holds two copies of the canon and "
              "nothing says which is live. They open it, keep the one block that points at this "
              "base, delete the other. The installer refuses to touch it until they do, and "
              "nothing here will edit a file outside the base on its own.")
    if not changed and not removed and not seeded and not carried:
        print(DIRECTIVE + " nothing arrived — the base was already current. Say so in one short "
              "line only if the person asked; otherwise say nothing.")
        return 0
    print(DIRECTIVE + " read CHANGELOG.md for what landed between those two versions, tell the "
          "person in one or two plain sentences what it means for THEM — not what changed in "
          "the engine — and save (python3 tools/sync.py save \"...\"). If none of it touches how "
          "they work, say that plainly and save anyway.")
    return 0


#: Passed to the process this one re-executes, so a refresh can happen at most once per run.
#: Not documented for people: it is machinery talking to itself, and a person typing it would
#: only be turning off the thing that protects them.
REFRESHED_FLAG = "--engine-refreshed"


def present_files(root: Path, relpaths: list) -> set:
    """Every file that exists under these paths right now, as posix relatives to the base."""
    found = set()
    for relpath in relpaths:
        target = root / relpath
        if target.is_file():
            found.add(relpath)
        elif target.is_dir():
            found |= {child.relative_to(root).as_posix()
                      for child in target.rglob("*") if child.is_file()}
    return found


def python_sources(root: Path, relpaths: list) -> list:
    """Every `.py` under these paths — the whole of what a re-execution will import.

    Checking only `update.py` covers the file that is re-executed and not the modules it imports
    at the top of itself, unguarded. A release with a broken module in `tools/lib` therefore passed
    the check, landed, and killed the base: the import fails before `argparse` is reached, so every
    later run dies at the same line and `--self-heal` — declared below those imports — cannot be
    reached to repair it.
    """
    sources = []
    for relpath in relpaths:
        target = root / relpath
        if target.is_file() and target.suffix == ".py":
            sources.append(target)
        elif target.is_dir():
            sources.extend(child for child in target.rglob("*.py") if child.is_file())
    return sources


def refresh_self(root: Path, ref: str, argv: list, dry_run: bool):
    """Bring the updater and its library — never the manifest — to the release, then hand over.

    Returns None to carry on in this process, or an exit code when it re-executed.

    WHY this is first. The manifest read is the INCOMING one, but the code executing it is whatever
    is on disk — so `retired:` and `migrations:` from a new release are carried out by the previous
    release's passes. Those are the two that DELETE and MOVE, and a fix shipped for either of them
    reaches the base one run after the release that needed it. Refreshing first closes that: the
    release's own declarations are executed by the release's own code.

    WHY NOT the manifest, which is the part that looks like an oversight and is not. The manifest is
    the thing being COMPARED: this run reads the incoming one and measures it against the one the
    base still has, and a path present in the incoming and absent from the base's is `adopted` — a
    path that was the PERSON's space until this release claimed it, and which is therefore guarded
    on the way in. Replace the manifest first and both sides become the same document: `adopted` is
    empty, the path is still checked out, and it lands over their file with no guard and no word.
    Not half a release — a silent overwrite of something that was theirs. `--self-heal` still
    restores the manifest, because a base being repaired by hand has no comparison left to protect.

    What this does NOT fix, so nobody looks for it here: an updater corrupted badly enough not to
    parse never reaches this function — python fails on import, before any flag is read. That case
    is `--self-heal`, run by hand, and it stays.
    """
    if dry_run:
        print("%s dry-run: the machinery is left as it is, so this preview is what the CURRENT "
              "updater would do." % PREFIX)
        return None
    if REFRESHED_FLAG in argv:
        return None

    changed = [p for p in HANDOVER_PATHS
               if ref_has_path(ref, p, root) and git("diff", "--quiet", ref, "--", p,
                                                     root=root)[0] != 0]
    if not changed:
        return None

    # Asked BEFORE anything is written. These are engine paths like any other, and replacing one
    # the person has been editing — without the check that exists to catch exactly that — would
    # destroy it a step before the check runs.
    dirty = dirty_engine_paths(root, ref, list(HANDOVER_PATHS))
    if dirty:
        print("%s the machinery here has local edits (%s), so it was left alone; the check below "
              "will say what to do about them." % (PREFIX, ", ".join(dirty)))
        return None

    # Recorded before anything is written: a rollback has to remove what THIS function added, and
    # nothing else. An untracked file of the person's under these paths is invisible to the dirt
    # check above, so "delete whatever HEAD lacks" would take it with it.
    was_here = present_files(root, changed)
    print("%s bringing the updater itself up to date first: %s" % (PREFIX, ", ".join(changed)))
    for relpath in changed:
        if git("checkout", ref, "--", relpath, root=root)[0] != 0:
            return fail("could not put %s in place, so nothing further was attempted." % relpath,
                        "Nothing has been changed. Say what is in the way, in plain words.")

    # A release that ships an updater which will not parse would otherwise replace a working one
    # with a broken one and then try to run it — and `--self-heal` would fetch the same file again.
    # Checked here, while the previous version is still one `git checkout` away.
    broken = None
    for source in sorted(python_sources(root, changed)):
        try:
            compile(source.read_text(encoding="utf-8"), str(source), "exec")
        except (SyntaxError, ValueError, OSError) as problem:
            broken = "%s: %s" % (source.relative_to(root).as_posix(), problem)
            break
    if broken:
        for relpath in changed:
            git("checkout", "HEAD", "--", relpath, root=root)
        # `checkout` restores what HEAD holds and never removes what it lacks, so a module the
        # release ADDED survives both the working tree and the INDEX — where checking the path out
        # of the ref staged it. Left there, every later run reads the path as the person's own
        # unsaved work and refuses, which is a base broken by its own repair. Removed one file at a
        # time, and only files this function put there: a whole-path unstage would be a wider
        # instrument than the situation needs.
        for path in sorted(present_files(root, changed) - was_here):
            git("rm", "--cached", "--quiet", "--", path, root=root)
            (root / path).unlink()
        # Refused whole, not carried on with. Continuing would let the main pass write that same
        # unparseable file at the end anyway — leaving a base that cannot update again and cannot
        # repair itself, since `--self-heal` fetches the same release. Nothing lands instead.
        return fail(
            "the machinery this release ships will not parse, so nothing was changed: %s" % broken,
            "This base is untouched and still works. It is the RELEASE that is broken, not",
            "anything here — say that plainly, and try again when a newer one is out.",
        )

    print("%s re-running with it" % PREFIX)
    rerun = [a for a in argv if a != REFRESHED_FLAG] + [REFRESHED_FLAG]
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve())] + rerun).returncode


def mode_apply(root: Path, remote: str, branch: str, dry_run: bool,
               confirmed: bool = False) -> int:
    enclosing = enclosing_repository(root)
    if enclosing:
        return fail(
            "this base has no history of its own — it sits inside %s." % enclosing,
            "Every path below would be written into THAT repository, and the retirement pass",
            "would delete from it. Nothing has been touched. The base has to be its own thing",
            "before it can be updated: tell the person in their words, then set it up.",
        )
    remote, url = resolve_remote(remote, root)
    if not url:
        address = manifest_lib.read_engine_remote(root)
        return fail(
            "this base is not connected to the repository it came from, so it cannot be updated.",
            "This is normal on a device that only ever cloned their base: the connection is",
            "machine-local and no clone carries it. Tell the person in their words, then:",
            "  git remote add %s %s" % (remote, address or "<the engine's repository>"),
        )

    ref = "%s/%s" % (remote, branch)
    print("%s fetching %s ..." % (PREFIX, ref))
    if git("fetch", remote, branch, root=root, timeout=NETWORK_TIMEOUT_SECONDS)[0] != 0:
        return fail("could not reach the engine remote. Nothing changed.")

    handed_over = refresh_self(root, ref, sys.argv[1:], dry_run)
    if handed_over is not None:
        return handed_over

    engine_paths = [p.rstrip("/") for p in manifest_lib.read_section("engine", root)]
    if not engine_paths:
        if manifest_lib.declares_section("engine", root):
            # Declared empty: a base that shares no paths with the engine. Not a fault — its own
            # canon is its own, and adopting an engine path is a decision made one path at a time.
            print("%s this base shares no paths with the engine, so an update has nothing to "
                  "replace." % PREFIX)
            print(DIRECTIVE + " say nothing unless asked. Adopting an engine path is a deliberate "
                  "choice — read the manifest's header before adding one to engine:.")
            return 0
        return fail("the manifest has no engine: section — nothing could be updated safely.",
                    "Either it is corrupt or it was never written. An update that replaces",
                    "nothing and reports success is indistinguishable from one that worked.")

    # Read the manifest being SHIPPED before anything is touched. Everything below — what to
    # guard, what to seed, what to replace — is decided by what the RELEASE declares, not by what
    # this base still happens to hold.
    incoming = incoming_sections(ref, root)
    # Read BEFORE the checkout replaces the manifest. What the base already treats as the
    # person's space cannot be revoked by the release doing the replacing.
    protected_before = manifest_lib.read_section("exclude", root)

    # A path this release ADDS to engine: has to be guarded BEFORE it is replaced, and it is the
    # likeliest of all of them to collide: until this run it was the person's own space, so
    # whatever is sitting there is theirs. Computing it here rather than at the checkout loop is
    # the whole point — the one pass whose job is preventing loss cannot run after the loss.
    adopted = [p for p in incoming.engine if p not in engine_paths]
    dirty = dirty_engine_paths(root, ref, engine_paths + adopted, incoming.retired)
    if dirty:
        return fail(
            "these engine paths have unsaved local edits and would be overwritten:",
            *(["  %s" % p for p in dirty]
              + ["Save or undo them first. Editing an engine path is itself the problem:",
                 "it survives exactly until the next update (doctrine/engine-ownership.md)."]),
        )

    version_before = read_local_version(root)
    version_upstream = (ref_read_path(ref, VERSION_FILE, root) or "").strip()


    if dry_run:
        return preview(root, ref, engine_paths, incoming,
                       protected_before, version_before, version_upstream)

    seeded = seed_missing_templates(root, ref, incoming.template)
    resolved, absent, changed = 0, 0, 0
    changed_paths, added_paths = [], []

    # A path this release ADDS to engine: is not in the list read from the manifest that was on
    # disk when the run began — that manifest is itself one of the paths being replaced. Without
    # this the new file lands one whole update late, and the run that ships it says nothing.
    for relpath in engine_paths + adopted:
        if not ref_has_path(ref, relpath, root):
            absent += 1
            continue
        if git("diff", "--quiet", ref, "--", relpath, root=root)[0] != 0:
            changed += 1
            (added_paths if relpath in adopted else changed_paths).append(relpath)
        # A checkout can fail for reasons no preflight sees — a file sitting where the release
        # needs a directory, a permission, a name that two paths collide on under a
        # case-insensitive filesystem. Ignoring the status here counted the path as replaced and
        # then let the retirement pass below delete the OLD copy, which is how a base ends up
        # with neither and an update that reports success.
        code = git("checkout", ref, "--", relpath, root=root)[0]
        if code != 0:
            return fail(
                "could not put %s in place, so nothing further was attempted." % relpath,
                "Every engine path before this one is already replaced; nothing has been deleted",
                "and nothing of the person's has moved. Something is occupying that path —",
                "look at it, clear it, and run the update again.",
            )
        resolved += 1

    # A run that resolves nothing is a broken update, not an up-to-date base, and without this
    # check the two are indistinguishable: an engine that applies nothing reports success.
    if resolved == 0:
        return fail(
            "not one of the %d engine paths was found in %s."
            % (len(engine_paths) + len(adopted), ref),
            "That is never the shape of an up-to-date base — the engine would have to have",
            "deleted itself. Something mangled the paths before git saw them.",
            "Recover with: python3 tools/update.py --self-heal",
        )

    # `rules/safety.md` and `rules/git-safety.md` both require a deletion to be confirmed before
    # it runs. An update that silently deletes and moves on the strength of a file it just
    # fetched breaks the engine's own hard rule, so anything destructive stops here the first time
    # and names itself. Replacement is not affected: an update with nothing to delete or move
    # runs exactly as before, which is almost all of them.
    # A refusal here is reported by the real pass below, which knows how to say it; this
    # preview only decides whether the person has to see the moves first.
    try:
        pending_moves = migrate_lib.run(root, dry_run=True)
    except migrate_lib.MigrationRefused:
        pending_moves = []
    # Retirement is the other half of replacement — the engine withdrawing its own path, already
    # fenced off from the person's space by a protection that can only widen. So it runs here,
    # BEFORE the gate below: holding the engine's own withdrawal behind a confirmation that is
    # about the person's files leaves every declared deletion undone for as long as an
    # unrelated move stays unconfirmed, and nothing in the output would say so.
    carried, removed, blocked = [], [], []
    try:
        removed = retire_lib.run(
            root, protected=sorted(set(protected_before) | set(incoming.exclude)))
    except retire_lib.RetirementRefused as refusal:
        blocked.append("refusing to drop paths that belong to the person, not the engine: %s"
                       % ", ".join(refusal.trespassing))

    # A MOVE is different in kind: `migrations:` exists precisely to rearrange the person's own
    # space, so it is the one thing here that changes their files rather than the engine's, and
    # `rules/safety.md` requires it to be seen before it runs.
    if pending_moves and not confirmed and not blocked:
        print("%s this update wants to move things in the person's own space:" % PREFIX)
        for move in pending_moves:
            print("  > move %s to %s%s"
                  % (move.source, move.destination, " — %s" % move.note if move.note else ""))
        print("%s the engine paths above are already replaced%s. Nothing of the person's has moved."
              % (PREFIX, ", and what the engine withdrew is gone" if removed else ""))
        print(DIRECTIVE + " tell the person in plain words what is about to move and what it means "
              "for them — these are their own files, not the engine's — then run the same command "
              "with --confirm once they are content.")
        return 0

    # The two passes are independent, so one refusing must not cancel the other: returning on the
    # first refusal leaves every declared deletion undone for as long as an unrelated move stays
    # blocked, and says nothing about it.
    try:
        carried = migrate_lib.run(root)
    except migrate_lib.MigrationRefused as refusal:
        blocked.append("a declared change could not be carried out: %s" % refusal)

    if blocked:
        return fail(*(blocked + [
            "The engine paths above are already in place and anything that COULD be carried out was.",
            "Nothing was moved or deleted that is named here; running the update again is safe.",
        ]))

    version_after = read_local_version(root)
    if version_upstream and version_after != version_upstream:
        return fail(
            "%s reads '%s' after the update but the engine ships '%s'."
            % (VERSION_FILE, version_after or "?", version_upstream),
            "The checkout did not land what it reported. Nothing was rolled back;",
            "inspect with: git status",
        )

    return report(root, remote, resolved, changed, absent, changed_paths, added_paths,
                  seeded, removed, carried, version_before, version_after)


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(description="Update the engine half of this base")
    parser.add_argument("--remote", default=DEFAULT_REMOTE)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true",
                        help="report whether a newer version exists; change nothing")
    parser.add_argument("--max-age", type=int, default=0,
                        help="with --check: stay silent if the last check is younger than this")
    parser.add_argument("--self-heal", action="store_true")
    # Machinery talking to itself: set on the process this one re-executes after refreshing
    # its own code, so a refresh can happen at most once per run. Hidden because a person
    # typing it would only be switching off the step that protects them.
    parser.add_argument(REFRESHED_FLAG, action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--confirm", action="store_true",
                        help="proceed with declared deletions and moves after seeing them")
    args = parser.parse_args(argv[1:])

    root = manifest_lib.repo_root()
    if git_ok("rev-parse", "--is-inside-work-tree", root=root) != "true":
        return fail("this base is not tracked, so there is nothing to update from.")

    if args.self_heal:
        return mode_self_heal(root, args.remote, args.branch, argv[1:])
    if args.check:
        return mode_check(root, args.remote, args.branch, args.max_age)
    return mode_apply(root, args.remote, args.branch, args.dry_run, args.confirm)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except (manifest_lib.ManifestMissing, manifest_lib.UnsafeEntry) as problem:
        # A base whose contract is gone or untrustworthy is exactly the base that needs a
        # recovery command, and a traceback is not one.
        sys.stderr.write(manifest_lib.explain_refusal(problem))
        sys.exit(2)

