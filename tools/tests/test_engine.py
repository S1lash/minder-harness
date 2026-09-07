#!/usr/bin/env python3
"""Tests for the machinery a person's base runs on its own.

Everything here was verified by hand once, which is worth exactly one session. These are the
same checks, re-runnable: the manifest reader, the retirement guard, and the updater driven
end to end against a real git remote — including the shapes that must FAIL, because a broken
update that exits 0 is indistinguishable from an up-to-date base.

Run:  python3 -m unittest discover -s tools/tests
"""

from __future__ import annotations

import os
import ast
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE_ROOT / "tools"))

from lib import gitrun  # noqa: E402
from lib import manifest as manifest_lib  # noqa: E402
from lib import migrate as migrate_lib  # noqa: E402
from lib import portability  # noqa: E402
from lib import enginechecks  # noqa: E402
import update as update_module  # noqa: E402
from lib import retire as retire_lib  # noqa: E402

TOOL_FILES = ("update.py", "check_engine.py")
MANIFEST = """version: 1.0.0

engine:
  - rules/
  - VERSION
  - .engine-manifest.yml   # inline note the reader must drop

template:
  - seed.md

exclude:
  - mine/

retired:
  - old/gone.md
"""


def git(root, *args, check=True):
    done = subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        + list(args),
        capture_output=True, text=True,
    )
    if check and done.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), done.stderr))
    return done


def write(root: Path, relpath: str, text: str):
    target = root / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


class TempCase(unittest.TestCase):
    """A throwaway directory per test, cleaned up whichever way the test ends.

    The same three lines were copy-pasted into sixteen setUps, which is sixteen chances to
    forget the cleanup and one leaked tree per omission.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmpdir = Path(self.tmp.name)


def install_tools(root: Path):
    """Put the real code under test into a fake base, the way a real base carries it."""
    (root / "tools").mkdir(parents=True, exist_ok=True)
    for name in TOOL_FILES:
        shutil.copy2(ENGINE_ROOT / "tools" / name, root / "tools" / name)
    # Never the bytecode. The engine's own `.gitignore` keeps `__pycache__` out of every real
    # base; copying it here makes a fixture that COMMITS `.pyc`, python rewrites them on the next
    # import, and the path then reads as the person's own unsaved edit — a fixture manufacturing
    # the exact state the checks under test are meant to detect.
    shutil.copytree(ENGINE_ROOT / "tools" / "lib", root / "tools" / "lib", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))


def run_tool(base: Path, tool: str, *args, cwd: Path = None, env: dict = None):
    """Run one of the engine's tools out of a base, the way a session runs it."""
    return subprocess.run([sys.executable, str(base / "tools" / tool), *args],
                          capture_output=True, text=True, env=env,
                          cwd=None if cwd is None else str(cwd))


def engine_text(relpath: str) -> str:
    """Read a file of this engine as text. UTF-8 is stated because Windows would not assume it."""
    return (ENGINE_ROOT / relpath).read_text(encoding="utf-8")


def engine_source(destination: Path) -> Path:
    """A throwaway copy of this engine to point the installer at, never the live tree.

    `install.sh` reads a filled `profile.md` as "this IS your base" and installs IN PLACE, which
    on a person's base means it stages and rewrites their own repository. The installer tests
    skip there — see `AUTHOR_SIDE` — and this is the second line of that defence: if the
    judgement is ever wrong, what gets installed over is a copy in a temporary directory.
    """
    shutil.copytree(ENGINE_ROOT, destination, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    # A fresh clone of the engine, which is what the installer is entitled to assume it was run
    # from: it reads the engine's address off this repository's `origin` to leave the new base a
    # remote it can be updated through. History is not copied — only the address matters.
    init_repo(destination)
    subprocess.run(["git", "-C", str(destination), "remote", "add", "origin",
                    manifest_lib.read_engine_remote(ENGINE_ROOT)], check=True)
    return destination


def this_checkout_is_the_engine() -> bool:
    """True only where the engine is authored, false on a base somebody installed it into.

    `tools/tests/` is an `engine:` path, so this suite ships and `/minder:doctor` runs it on
    every base. Most of it belongs there — it proves the MACHINERY that base runs, which is the
    same everywhere. Two kinds of test do not, and both go behind `AUTHOR_SIDE`:

    - the installer end to end, which needs a pristine engine to point at — a base is not one and
      cannot be made into one, and its owner has already installed;
    - anything asserting that THIS TREE's content is coherent. On a base that content is partly
      the person's: `AGENTS.md` is a file their agent is told to edit, `rules/` may hold a rule
      of their own, and a rule they added is not yet in the list until the session that notices
      repairs it. `check_engine.py` reports every one of those conditions already, in the register
      that fits — a base with something to fix. A test failing says something else entirely,
      because `/minder:doctor` reads it as broken machinery and a risk of lost work.

    The engine's own remote is the honest discriminator, and it is the same question
    `check_engine_remote_is_this_repository` asks.
    """
    declared = manifest_lib.read_engine_remote(ENGINE_ROOT)
    origin = gitrun.run(ENGINE_ROOT, "remote", "get-url", "origin")
    if not declared or origin.failed or not origin.out.strip():
        return False
    return manifest_lib.same_repository(declared, origin.out)


_AUTHORING_HERE = this_checkout_is_the_engine()
if not _AUTHORING_HERE:
    # Say it out loud. A skip is invisible in a green run — unittest reports a count and never a
    # reason — so a mismatch between `engine_remote:` and `origin` silently removes every check that
    # only means anything here, and the run still prints OK. That is the shape of a release
    # verified by a suite that quietly declined to look, and it is worth one line on stderr.
    sys.stderr.write(
        "\n[test_engine] author-side checks are NOT running: `engine_remote:` says %r and this "
        "checkout's origin is %r.\n"
        "           On a base that is correct and expected. If this IS the engine, the two have "
        "drifted and the checks that\n"
        "           guard a release just went silent — reconcile them before trusting a green "
        "run.\n\n"
        % (manifest_lib.read_engine_remote(ENGINE_ROOT),
           (gitrun.run(ENGINE_ROOT, "remote", "get-url", "origin").out or "").strip() or None))

AUTHOR_SIDE = unittest.skipUnless(
    _AUTHORING_HERE,
    "asked where the engine is authored — this checkout is a base, and what it holds is partly "
    "the person's; check_engine.py is what reports on a base")


def code_strings(source: str) -> set:
    """What this code could pass as a git argument. Comments and docstrings are not in the tree.

    A substring scan of the file text cannot tell an argument from prose, and these files explain
    in their own words that they never force or rebase — quoting the banned flags is how they say
    it. The syntax tree has no comments in it at all, and a docstring is recognisable, so the
    question becomes what the code passes rather than what it says.

    A whole literal counts (`"--force"`, `"rebase"`), and so does a FLAG inside a joined one
    (`"push --force"`), which a search for a quoted token misses. A bare word inside a sentence
    does not: `"…or restore it:"` is something a person reads, not something git receives.
    """
    tree = ast.parse(source)
    prose = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            prose.add(id(body[0].value))
    passed = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in prose:
            passed.add(node.value)
            passed |= {word for word in node.value.split() if word.startswith("-")}
    return passed


def git_argument_pairs(source: str) -> set:
    """Every adjacent pair of literal arguments this code assembles, however it assembles them.

    `checkout` is how an update replaces an engine path — `checkout <ref> -- <path>` writes what the
    ref holds. With nothing between the two it is the opposite operation, and it throws away
    whatever the person has not saved. Only the adjacency separates them.

    Both spellings count: arguments passed positionally, and a list literal built to be handed
    to `subprocess`. Reading only the first would leave the check depending on which idiom a
    future author happened to reach for.
    """
    pairs = set()

    def literals(nodes):
        return [n.value if isinstance(n, ast.Constant) and isinstance(n.value, str) else None
                for n in nodes]

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            values = literals(node.args)
        elif isinstance(node, (ast.List, ast.Tuple)):
            values = literals(node.elts)
        else:
            continue
        for first, second in zip(values, values[1:]):
            if first is not None and second is not None:
                pairs.add((first, second))
    return pairs


def run_installer(source: Path, home: Path, answers: str, cwd: Path):
    """Run `install.sh` against a throwaway HOME, with the answers fed on stdin.

    `MINDER_HARNESS_ANSWERS_ON_STDIN` is not decoration: without it the installer refuses piped
    answers, because a question that quietly took a default is indistinguishable in the
    output from one somebody actually answered.
    """
    return subprocess.run(["bash", str(source / "install.sh")], input=answers,
                          capture_output=True, text=True, cwd=str(cwd),
                          env={**os.environ, "HOME": str(home),
                               "MINDER_HARNESS_ANSWERS_ON_STDIN": "1"})


def path_with(directory: Path) -> dict:
    """This environment, with one directory put ahead of PATH.

    The engine shells out to `git` and `gh`; a stub in front of PATH is how a test drives what
    those answer without a network.
    """
    return {**os.environ, "PATH": "%s%s%s" % (directory, os.pathsep, os.environ.get("PATH", ""))}


def run_update(base: Path, *args):
    return run_tool(base, "update.py", "--branch", "main", *args)


def bare_remote(path: Path) -> Path:
    """A remote the way every surface expects one: HEAD already on `main`.

    A bare repository takes HEAD from whatever `init.defaultBranch` happens to be, so a clone
    of one can land on `master` while the base pushes `main`. The two surfaces then never share
    a branch, and a test about them diverging passes without the divergence ever happening.
    """
    subprocess.run(["git", "init", "-q", "--bare", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "symbolic-ref", "HEAD", "refs/heads/main"], check=True)
    return path


def clone(remote: Path, path: Path) -> Path:
    subprocess.run(["git", "clone", "-q", str(remote), str(path)], check=True)
    return identify(path)


def identify(path: Path) -> Path:
    """Give a fixture repository an identity of its OWN.

    The `git()` helper passes one per invocation, which covers the commits it makes and nothing
    else: `sync.py` and `update.py` run as separate processes and read the repository's config.
    A machine with no global identity is the ordinary case on a person's base — the installer
    writes one base-local — and there these tools reported the missing name instead of whatever
    the test was about.
    """
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@example.invalid"],
                   check=True)
    return path


def init_repo(path: Path) -> Path:
    """A fixture repository on `main`, with an identity, in one place so none can forget."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init", "-q", "-b", "main"], check=True)
    return identify(path)


class ManifestReaderTests(TempCase):
    def setUp(self):
        super().setUp()
        self.root = self.tmpdir
        write(self.root, ".engine-manifest.yml", MANIFEST)

    def test_sections_are_read_in_order(self):
        self.assertEqual(manifest_lib.read_section("engine", self.root),
                         ["rules/", "VERSION", ".engine-manifest.yml"])
        self.assertEqual(manifest_lib.read_section("template", self.root), ["seed.md"])
        self.assertEqual(manifest_lib.read_section("retired", self.root), ["old/gone.md"])

    def test_inline_comment_is_not_part_of_the_path(self):
        # A trailing note reaching a caller as part of the path names a file that never exists,
        # and every consumer reads that as "absent".
        self.assertIn(".engine-manifest.yml", manifest_lib.read_section("engine", self.root))

    def test_version_is_read(self):
        self.assertEqual(manifest_lib.read_version(self.root), "1.0.0")

    def test_unknown_section_is_refused(self):
        with self.assertRaises(ValueError):
            manifest_lib.read_section("nonsense", self.root)


class SilentDivergenceTests(TempCase):
    """Two states the base could be in while reporting that everything was fine."""

    def setUp(self):
        super().setUp()
        self.base = Path(self.tmp.name) / "base"
        (self.base / "projects").mkdir(parents=True)
        write(self.base, "knowledge/note.md", "theirs\n")
        install_tools(self.base)
        shutil.copy2(ENGINE_ROOT / "tools" / "sync.py", self.base / "tools")
        init_repo(self.base)

    def run_sync(self, *args):
        return run_tool(self.base, "sync.py", *args, cwd=self.base)

    def test_a_project_that_is_its_own_repository_is_named(self):
        """A gitlink records a commit id and no content, so a clone gets an empty folder.

        The base's whole promise is that what is inside it travels. Nothing said otherwise: the
        save reported success, and the phone found nothing there.
        """
        app = self.base / "projects" / "myapp"
        app.mkdir()
        write(app, "main.py", "print('hi')\n")
        init_repo(app)
        git(app, "add", "-A")
        git(app, "commit", "-qm", "the app")
        # A base with no remote has a louder problem, and its directive correctly wins. Give it
        # one so the nested-repository directive is the one under test.
        remote = Path(self.tmp.name) / "their-remote.git"
        bare_remote(remote)
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "their base")
        git(self.base, "remote", "add", "origin", str(remote))
        git(self.base, "push", "-q", "-u", "origin", "main")

        done = self.run_sync("status")
        self.assertIn("projects kept separately: projects/myapp", done.stdout)
        self.assertIn("do NOT travel with this base", done.stdout)
        self.assertIn("does not travel with the base", done.stdout, "the directive must say so")

    def test_a_base_with_no_nested_repository_says_nothing_about_it(self):
        done = self.run_sync("status")
        self.assertNotIn("projects kept separately", done.stdout)

    def test_a_session_that_ends_with_unsaved_work_saves_it(self):
        """The floor under save-out, so the case the design exists for has a mechanism.

        Without it, work done on a phone whose session evaporates rests entirely on the agent
        remembering to save. This is the floor under that rule, not a replacement for it.
        """
        remote = Path(self.tmp.name) / "end.git"
        bare_remote(remote)
        write(self.base, "seed.md", "x\n")
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "start")
        git(self.base, "remote", "add", "origin", str(remote))
        git(self.base, "push", "-q", "-u", "origin", "main")

        write(self.base, "knowledge/from-the-phone.md", "what we worked out\n")
        done = self.run_sync("session-end")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

        elsewhere = Path(self.tmp.name) / "elsewhere"
        clone(remote, elsewhere)
        self.assertTrue((elsewhere / "knowledge" / "from-the-phone.md").exists(),
                        "the session ended and the work never left the machine")

    def test_a_session_that_ends_with_nothing_to_save_says_nothing(self):
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "everything recorded")
        done = self.run_sync("session-end")
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stdout.strip(), "", "it spoke when there was nothing to say")

    def test_a_session_ending_with_nowhere_to_send_says_what_is_lost(self):
        write(self.base, "knowledge/only-here.md", "theirs\n")
        done = self.run_sync("session-end")
        self.assertEqual(done.returncode, 0)
        self.assertIn("stays on this machine only", done.stdout)

    def test_a_branch_with_no_tracking_still_notices_the_remote_moved(self):
        """The base reported "in step" while the remote was genuinely ahead.

        `refresh_remote_counts` returned early when no upstream was configured, leaving both
        counters at zero — so `status`, `session-start` and `pull` all said the same wrong thing,
        and a read-only session never self-corrects because nothing pushes to be refused.
        """
        remote = Path(self.tmp.name) / "shared.git"
        bare_remote(remote)
        write(self.base, "f.md", "v1\n")
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "one")
        git(self.base, "remote", "add", "origin", str(remote))
        git(self.base, "push", "-q", "-u", "origin", "main")

        other = Path(self.tmp.name) / "other"
        clone(remote, other)
        self.assertEqual(
            subprocess.run(["git", "-C", str(other), "rev-parse", "--abbrev-ref", "HEAD"],
                           capture_output=True, text=True).stdout.strip(), "main",
            "the second surface is not on the branch under test")
        write(other, "f.md", "v2\n")
        git(other, "add", "-A")
        git(other, "commit", "-qm", "two")
        git(other, "push", "-q")

        # The tracking link is what a fresh or hand-made checkout most often lacks.
        git(self.base, "branch", "--unset-upstream")
        done = self.run_sync("status")
        self.assertNotIn("in step with the remote", done.stdout,
                         "it reported in step while the remote was ahead")
        self.assertIn("origin/main", done.stdout)
        self.assertIn("1 change(s) elsewhere are not here yet", done.stdout)
        self.assertIn("not linked to the remote", done.stdout,
                      "the reason the comparison is indirect has to be said")

    def _visibility_state(self, answer, url="https://github.com/someone/theirs"):
        """What `read_state` makes of a remote, with `gh` answering `answer`.

        In-process through a subprocess rather than a sync MODE, because every mode fetches, and a
        GitHub-shaped URL — which is the whole point, since the probe is now only asked where it
        can be answered — would put a real network call inside the suite.
        """
        fake_bin = Path(self.tmp.name) / ("bin-" + (answer or "none"))
        fake_bin.mkdir(exist_ok=True)
        gh = fake_bin / "gh"
        gh.write_text("#!/bin/sh\n%s\n" % ("exit 1" if answer is None else "echo " + answer),
                      encoding="utf-8")
        gh.chmod(0o755)
        git(self.base, "remote", "remove", "origin", check=False)
        git(self.base, "remote", "add", "origin", url)
        probe = (
            "import sys; sys.path.insert(0, %r); import sync; s = sync.read_state();"
            " print(s.remote_kind, s.remote_visibility)" % str(self.base / "tools"))
        done = subprocess.run([sys.executable, "-c", probe], cwd=str(self.base),
                              capture_output=True, text=True, env=path_with(fake_bin))
        self.assertEqual(done.returncode, 0, done.stderr)
        kind, _, visibility = done.stdout.strip().partition(" ")
        return kind, (None if visibility == "None" else visibility)

    def test_a_public_remote_stops_the_save(self):
        """"Private" was asserted once at creation and never checked again.

        A fork of a public repository is itself public, and its address does not match the engine's,
        so nothing moved it aside — the person's whole life then pushed somewhere anyone can
        read, while the installer and the doctor both reported a private place online on the
        sole evidence that a URL existed.
        """
        kind, visibility = self._visibility_state("public")
        self.assertEqual((kind, visibility), ("github", "public"))

        fake_bin = Path(self.tmp.name) / "bin-public"
        saving = run_tool(self.base, "sync.py", "save", "anything",
                          cwd=self.base, env=path_with(fake_bin))
        self.assertNotEqual(saving.returncode, 0, "it saved to a public remote")
        self.assertIn("PUBLIC", saving.stdout)
        self.assertIn("readable by anyone", saving.stdout)

    def test_a_private_remote_raises_no_alarm(self):
        # The other direction, and the one a false-positive would ruin: a base that IS private
        # must never be told it is public, or the warning stops meaning anything.
        self.assertEqual(self._visibility_state("private"), ("github", "private"))

    def test_a_visibility_that_cannot_be_established_is_not_called_public(self):
        """Unknown is not "private", and the answer has to survive the trip into the state."""
        self.assertEqual(self._visibility_state(None), ("github", None))

    def test_a_remote_nothing_can_ask_is_never_probed_at_all(self):
        """A GitLab remote would fail the probe every run — an answer nobody can act on."""
        kind, visibility = self._visibility_state("public", "https://gitlab.com/someone/theirs")
        self.assertEqual(kind, "network")
        self.assertIsNone(visibility, "a remote nothing can ask was probed anyway")
    def test_a_base_git_cannot_read_is_not_reported_as_clean(self):
        """`git_ok` returned None for a failure and for an empty result alike.

        `porcelain or ""` then made "cannot tell" identical to "nothing to save", and
        session-start would fast-forward on that reading.
        """
        (self.base / ".git" / "index").write_bytes(b"CORRUPT")
        done = self.run_sync("status")
        self.assertIn("UNREADABLE", done.stdout)
        self.assertIn("STOP", done.stdout)
        saving = self.run_sync("save", "anything")
        self.assertNotEqual(saving.returncode, 0, "it saved over a base it could not read")


@AUTHOR_SIDE
class InstallerSafetyTests(TempCase):
    """Two ways the installer reached past what it was pointed at.

    Both were demonstrated end to end: the legacy-projects migration absorbed the person's own
    `~/projects` — an ordinary folder name, nothing to do with this engine — and committed a live
    API key with it; and a blank email left a base with every file staged and no history while
    the installer printed thirteen OK lines and "Done".
    """

    def source(self):
        return engine_source(self.tmpdir / "src")

    def setUp(self):
        super().setUp()
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()

    def install(self, answers):
        return run_installer(self.source(), self.home, answers, cwd=self.tmpdir)

    def test_an_ordinary_projects_folder_is_left_alone(self):
        # The trigger is a marker an old harness leaves, never the folder's name.
        theirs = self.home / "projects" / "client-work"
        theirs.mkdir(parents=True)
        (theirs / ".env").write_text("STRIPE_KEY=sk_live_real\n", encoding="utf-8")
        done = self.install("%s\nharness\nEnglish\nn\nn\nn\nn\nElena\ne@example.invalid\nn\n"
                            % self.home)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn("an earlier harness left it there", done.stdout)
        self.assertTrue((theirs / ".env").exists(), "the person's own folder was absorbed")
        # And it must not have been committed into the base either.
        tracked = subprocess.run(["git", "-C", str(self.home / "harness"), "ls-files"],
                                 capture_output=True, text=True).stdout
        self.assertNotIn("client-work", tracked, "the person's unrelated work was committed")

    def test_a_former_harness_projects_folder_is_offered_and_defaults_to_no(self):
        legacy = self.home / "projects"
        legacy.mkdir(parents=True)
        (legacy / "_index.md").write_text("# projects\n", encoding="utf-8")
        # A name the base does not already carry: `_index.md` exists on both sides, so the
        # migration skips it and it can never show whether the move happened.
        (legacy / "old-work.md").write_text("from the previous base\n", encoding="utf-8")
        # The migration question comes BEFORE the language one; an empty answer takes the
        # default, and the default has to be "leave it where it is".
        done = self.install("%s\nharness\n\nEnglish\nn\nn\nn\nn\nElena\ne@example.invalid\nn\n"
                            % self.home)
        self.assertIn("an earlier harness left it there", done.stdout)
        self.assertIn("It holds:", done.stdout, "it must show what it would move")
        self.assertTrue((legacy / "old-work.md").exists(),
                        "an empty answer moved the folder — the default is not no")

    def test_wiring_codex_is_verified_the_way_wiring_claude_is(self):
        """Asserting the check EXISTS is not asserting it runs.

        Every runtime's block is verified after install. Checking one and not another lets a
        person finish an install believing their runtime is set up when nothing confirmed it.
        """
        done = self.install("%s\nharness\nEnglish\ny\ny\nn\nn\nElena\ne@example.invalid\nn\n"
                            % self.home)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("Codex global wiring", done.stdout,
                      "Codex was wired and never checked")
        self.assertIn("Claude Code global wiring", done.stdout)
        self.assertTrue((self.home / ".codex" / "AGENTS.md").exists())

    def test_an_ordinary_install_records_the_base(self):
        done = self.install("%s\nharness\nEnglish\nn\nn\nn\nn\nElena\ne@example.invalid\nn\n"
                            % self.home)
        self.assertIn("OK   your work here is being recorded", done.stdout)
        head = subprocess.run(["git", "-C", str(self.home / "harness"), "log", "-1", "--format=%H"],
                              capture_output=True, text=True)
        self.assertTrue(head.stdout.strip(), "the base was left with no history")

    def test_a_base_that_could_not_record_anything_says_so(self):
        """A swallowed commit failure leaves every file staged, no history, and "Done".

        The reachable cause is a project repository with no commits of its own sitting under
        `projects/`: `git add -A` fails outright on it, and an installer that discards the
        failure prints its health check over a base that has recorded nothing.
        """
        source = self.source()
        nested = source / "projects" / "newapp"
        nested.mkdir(parents=True)
        (nested / "main.py").write_text("print('hi')\n", encoding="utf-8")
        init_repo(nested)
        done = run_installer(
            source, self.home,
            "%s\nharness\nEnglish\nn\nn\nn\nn\nElena\ne@example.invalid\nn\n" % self.home,
            cwd=self.tmpdir)
        base = self.home / "harness"
        head = subprocess.run(["git", "-C", str(base), "log", "-1", "--format=%H"],
                              capture_output=True, text=True).stdout.strip()
        if not head:
            self.assertIn("MISS your work here is being recorded", done.stdout,
                          "a base with no history was reported as fine")
            self.assertIn("PROBLEM", done.stdout)
        else:
            self.assertIn("OK   your work here is being recorded", done.stdout)


class EnclosingRepositoryTests(TempCase):
    """Being INSIDE a repository is not the same as BEING one.

    A base with no `.git` of its own, anywhere under another repository, makes `git -C <base>`
    answer for THAT repository. Unguarded, `save` stages the enclosing project's whole worktree —
    an unrelated `.env`, somebody's work-in-progress — commits it, pushes it to that project's
    remote, and reports "saved" in the plain language the rules require, with nothing in the
    output naming the repository it actually wrote to.
    """

    def setUp(self):
        super().setUp()
        self.company = Path(self.tmp.name) / "company"
        (self.company / "src").mkdir(parents=True)
        write(self.company, ".env", "DB_PASSWORD=s3cr3t\n")
        write(self.company, "src/wip.py", "half-finished\n")
        init_repo(self.company)
        git(self.company, "add", "-A")
        git(self.company, "commit", "-qm", "the company's repository")

        self.base = self.company / "harness"      # no .git of its own
        self.base.mkdir()
        write(self.base, "knowledge/note.md", "the person's note\n")
        install_tools(self.base)
        shutil.copy2(ENGINE_ROOT / "tools" / "sync.py", self.base / "tools")

    def run_sync(self, *args):
        return run_tool(self.base, "sync.py", *args, cwd=self.base)

    def test_saving_refuses_and_names_the_repository_it_would_have_written_to(self):
        done = self.run_sync("save", "write down what we decided")
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("NOT ITS OWN", done.stdout)
        self.assertIn(str(self.company), done.stdout)
        # Nothing staged: the enclosing repository is exactly as it was.
        staged = git(self.company, "diff", "--cached", "--name-only").stdout.strip()
        self.assertEqual(staged, "", "the enclosing repository was staged")

    def test_status_says_so_before_anything_else(self):
        done = self.run_sync("status")
        self.assertIn("NOT ITS OWN", done.stdout)
        self.assertIn("STOP", done.stdout)

    def test_a_base_that_is_its_own_repository_is_unaffected(self):
        init_repo(self.base)
        done = self.run_sync("status")
        self.assertNotIn("NOT ITS OWN", done.stdout)

    def test_the_updater_refuses_too(self):
        done = run_tool(self.base, "update.py", "--dry-run", cwd=self.base)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("no history of its own", done.stdout + done.stderr)


class GitHelperTests(TempCase):
    """The contract every tool but `sync.py` now shares, pinned so it cannot drift back."""

    def setUp(self):
        super().setUp()
        self.root = Path(self.tmp.name)
        init_repo(self.root)

    def test_leading_whitespace_survives(self):
        """Porcelain encodes state in columns 1 and 2.

        Stripping stdout once cost every path in a report its first character. `sync.py` reads
        porcelain today and does not use this helper, so nothing would notice the regression —
        which is exactly why the contract is pinned here rather than left to a caller.
        """
        write(self.root, "tracked.md", "one\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "one")
        write(self.root, "tracked.md", "two\n")
        result = gitrun.run(self.root, "status", "--porcelain")
        self.assertTrue(result.out.startswith(" M "), repr(result.out))

    def test_a_failure_is_a_result_not_an_exception(self):
        result = gitrun.run(self.root, "rev-parse", "--verify", "does-not-exist")
        self.assertTrue(result.failed)
        self.assertTrue(result.err, "stderr was discarded — the reason is the useful half")
        self.assertIsNone(gitrun.ok(self.root, "rev-parse", "--verify", "does-not-exist"))

    def test_missing_git_is_named_rather_than_traced(self):
        # A machine without git cannot be simulated by running git, so the call is replaced.
        def absent(*args, **kwargs):
            raise FileNotFoundError("git")
        real = gitrun.subprocess.run
        gitrun.subprocess.run = absent
        self.addCleanup(setattr, gitrun.subprocess, "run", real)
        with self.assertRaises(gitrun.GitMissing):
            gitrun.run(self.root, "status")


class ContainmentTests(TempCase):
    """A manifest entry becomes a filesystem operation, so containment is the manifest's job.

    A guard downstream compares strings against `exclude:`, and a string comparison cannot see
    that `../x` leaves the base or that an absolute path is not in it. Without containment at the
    parser, a `retired:` entry deletes a file outside the base and the parent-pruning walks UP the
    filesystem removing every directory it empties, and `./knowledge/x` deletes the person's space
    that `exclude: knowledge/` exists to protect.
    """

    def setUp(self):
        super().setUp()
        self.root = self.tmpdir / "base"
        (self.root / "knowledge").mkdir(parents=True)
        write(self.root, ".engine-manifest.yml",
              "version: 1.0.0\n\nengine:\n  - rules/\n\nexclude:\n  - knowledge/\n")

    def test_a_missing_manifest_names_the_recovery_instead_of_a_traceback(self):
        """The base that most needs `--self-heal` is the one whose manifest is gone.

        One reader, so the absence has a single place to be handled. A reader per tool raises
        FileNotFoundError at a person who cannot act on one, and `update.py` dies inside
        `resolve_remote` before it ever reaches the carefully worded refusal below it.
        """
        bare = Path(self.tmp.name) / "no-manifest"
        bare.mkdir()
        with self.assertRaises(manifest_lib.ManifestMissing):
            manifest_lib.read_section("engine", bare)
        # The tools resolve their base from their OWN location, so they have to be run from
        # inside the manifest-less base rather than pointed at it.
        install_tools(bare)
        shutil.copy2(ENGINE_ROOT / "tools" / "check_portability.py", bare / "tools")
        # A tracked base, so `update.py` reaches the manifest read rather than stopping earlier
        # on "not tracked" — the manifest-less case is what is under test here.
        init_repo(bare)
        for tool in ("update.py", "check_engine.py", "check_portability.py"):
            done = run_tool(bare, tool, cwd=bare)
            self.assertEqual(done.returncode, 2, tool + ": " + done.stdout + done.stderr)
            self.assertIn("self-heal", done.stderr, tool)

    def test_a_contract_that_cannot_be_trusted_names_the_recovery_too(self):
        """The refusal is right; a traceback is not how it reaches the person.

        Both broken-contract states carry a recovery command. Without one, the state where the
        engine is actively refusing to touch a person's disk reaches them as a stack trace. The
        remedy differs from the missing case — the file is there and one line of it is wrong —
        so it is said differently.
        """
        base = Path(self.tmp.name) / "unsafe"
        base.mkdir()
        install_tools(base)
        shutil.copy2(ENGINE_ROOT / "tools" / "check_portability.py", base / "tools")
        write(base, ".engine-manifest.yml",
              "version: 1.0.0\n\nengine:\n  - rules/\n  - ../outside/evil.py\n")
        init_repo(base)
        # `update.py` reaches the manifest only after resolving and fetching its engine remote, so
        # it needs one that exists — without it the arm is never entered and the guard is a
        # guard over nothing.
        engine = Path(self.tmp.name) / "engine.git"
        bare_remote(engine)
        seed = clone(engine, Path(self.tmp.name) / "engine-seed")
        write(seed, "VERSION", "1.0.0\n")
        git(seed, "add", "-A")
        git(seed, "commit", "-qm", "the engine")
        git(seed, "push", "-q", "-u", "origin", "main")
        git(base, "remote", "add", "minder-harness", str(engine))
        for tool in ("check_engine.py", "check_portability.py", "update.py"):
            done = run_tool(base, tool, cwd=base)
            self.assertEqual(done.returncode, 2, tool + ": " + done.stdout + done.stderr)
            self.assertIn("cannot be trusted", done.stderr, tool)
            self.assertIn("../outside/evil.py", done.stderr, tool)
            self.assertNotIn("Traceback", done.stderr, tool)

    def test_an_entry_that_leaves_the_base_is_refused_at_the_parser(self):
        for entry in ("../outside/x", "/etc/passwd", "~/secrets", "C:/Windows", "..", "."):
            with self.assertRaises(manifest_lib.UnsafeEntry, msg=entry):
                manifest_lib.safe_entry(entry, "retired")

    def test_a_dot_slash_entry_cannot_slip_past_the_persons_space(self):
        # `"./knowledge/x".startswith("knowledge/")` is False, so every guard in the engine missed it.
        self.assertEqual(manifest_lib.safe_entry("./knowledge/x", "retired"), "knowledge/x")
        self.assertTrue(manifest_lib.covers(["knowledge/"],
                                            manifest_lib.safe_entry("./knowledge/x")))

    def test_a_directory_entry_keeps_its_trailing_slash(self):
        self.assertEqual(manifest_lib.safe_entry("knowledge/"), "knowledge/")
        self.assertEqual(manifest_lib.safe_entry("./a/b/"), "a/b/")

    def test_retirement_refuses_a_path_that_resolves_outside_the_base(self):
        # Defence in depth behind the parser: a symlink inside the base can still point out.
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (outside / "victim.txt").write_text("theirs\n", encoding="utf-8")
        (self.root / "link").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(retire_lib.RetirementRefused):
            retire_lib.run(self.root, entries=["link/victim.txt"])
        self.assertTrue((outside / "victim.txt").exists())

    def test_pruning_empty_parents_never_climbs_out_of_the_base(self):
        """The second rubber band, tested directly because the first one now stops the caller.

        The stop condition is containment, not inequality: `directory != root` is never true for
        a path that starts above the base, so one escaping entry walks UP the filesystem removing
        every directory it empties.
        """
        outside = Path(self.tmp.name) / "outside" / "a" / "b"
        outside.mkdir(parents=True)
        retire_lib._prune_empty_parents(self.root, outside)
        self.assertTrue((Path(self.tmp.name) / "outside").exists(),
                        "pruning climbed out of the base")

        # Inside the base it still does its job: an emptied directory is not left behind.
        inner = self.root / "knowledge" / "gone"
        inner.mkdir(parents=True)
        retire_lib._prune_empty_parents(self.root, inner)
        self.assertFalse(inner.exists())
        self.assertTrue(self.root.exists(), "it removed the base itself")

    def test_a_move_may_not_reach_outside_the_base_in_either_direction(self):
        # Outbound loses the person's file; INBOUND drags an arbitrary file into a repository the
        # next save commits and pushes, which is an exfiltration primitive, not a misplaced file.
        for entry in ("move ../outside/id_rsa -> knowledge/harmless.md | tidy",
                      "move knowledge/secret.md -> ../exfil/secret.md | tidy"):
            with self.assertRaises(migrate_lib.MigrationRefused, msg=entry):
                migrate_lib.run(self.root, entries=[entry])


class CoverageRuleTests(unittest.TestCase):
    def test_directory_entry_covers_everything_beneath(self):
        self.assertTrue(manifest_lib.covered_by("rules/", "rules/a/b.md"))

    def test_file_entry_matches_only_itself(self):
        self.assertTrue(manifest_lib.covered_by("VERSION", "VERSION"))
        self.assertFalse(manifest_lib.covered_by("VERSION", "VERSION.bak"))

    def test_star_slash_covers_subdirectories_but_not_files_beside_them(self):
        # Reading the star as a plain prefix looks cautious and is not: it swallows sibling
        # files into the covered set, and a guard built on it refuses the work it exists to allow.
        self.assertTrue(manifest_lib.covered_by("roles/*/", "roles/alice/state.md"))
        self.assertFalse(manifest_lib.covered_by("roles/*/", "roles/_run-frame.md"))


class RetirementTests(TempCase):
    def setUp(self):
        super().setUp()
        self.root = self.tmpdir

    def test_listed_path_is_removed_and_its_empty_parent_pruned(self):
        write(self.root, ".engine-manifest.yml", MANIFEST)
        write(self.root, "old/gone.md", "dead")
        removed = retire_lib.run(self.root)
        self.assertEqual(removed, ["old/gone.md"])
        self.assertFalse((self.root / "old").exists())

    def test_absent_path_is_not_reported_as_removed(self):
        write(self.root, ".engine-manifest.yml", MANIFEST)
        self.assertEqual(retire_lib.run(self.root), [])

    def test_dry_run_deletes_nothing(self):
        write(self.root, ".engine-manifest.yml", MANIFEST)
        write(self.root, "old/gone.md", "dead")
        self.assertEqual(retire_lib.run(self.root, dry_run=True), ["old/gone.md"])
        self.assertTrue((self.root / "old" / "gone.md").exists())

    def test_a_retired_path_in_the_persons_space_refuses_the_whole_sweep(self):
        write(self.root, ".engine-manifest.yml",
              MANIFEST.replace("  - old/gone.md", "  - mine/notes.md"))
        write(self.root, "mine/notes.md", "theirs")
        with self.assertRaises(retire_lib.RetirementRefused):
            retire_lib.run(self.root)
        self.assertTrue((self.root / "mine" / "notes.md").exists(),
                        "a refused sweep must delete nothing at all")


class CommandNamespaceGateTests(TempCase):
    """The gate that keeps every shipped command answering to the name the documents promise.

    Two levels, and a file in neither answers to a name no document names.
    """

    #: The verbs that cover everything under the Minder name, not this base alone.
    FAMILY = ("doctor", "sync", "update")
    #: The verbs that are about this base and nothing else.
    BASE = ("add-skill", "init", "project-init")

    def test_the_engine_as_it_stands_ships_every_command_at_its_level(self):
        report = enginechecks.Report()
        enginechecks.check_commands_namespaced(ENGINE_ROOT, report)
        self.assertEqual([f.where + " " + f.what for f in report], [])

        # A gate that only asks "is anything misplaced?" is satisfied by shipping nothing at all,
        # which is exactly what a dropped subtree looks like to it.
        commands = ENGINE_ROOT / enginechecks.COMMAND_ROOT
        for level, expected in ((enginechecks.COMMAND_FAMILY, self.FAMILY),
                                (enginechecks.COMMAND_BASE, self.BASE)):
            found = sorted(p.stem for p in (commands / level).glob("*.md"))
            self.assertEqual(found, sorted(expected),
                             "%s does not hold the commands every document names" % level)

    def test_a_command_at_neither_level_is_a_finding(self):
        base = self.tmpdir / "outside"
        write(base, ".claude/commands/minder/update.md", "# family\n")
        write(base, ".claude/commands/minder/harness/init.md", "# base\n")
        write(base, ".claude/commands/stray.md", "# neither\n")
        report = enginechecks.Report()
        enginechecks.check_commands_namespaced(base, report)
        self.assertEqual([f.where for f in report], [".claude/commands/stray.md"])

    def test_a_command_deeper_than_a_level_is_a_finding(self):
        """`minder/harness/admin/doctor.md` answers to `/minder:harness:admin:doctor`."""
        base = self.tmpdir / "deep"
        write(base, ".claude/commands/minder/harness/admin/doctor.md", "# too deep\n")
        report = enginechecks.Report()
        enginechecks.check_commands_namespaced(base, report)
        self.assertEqual([f.where for f in report],
                         [".claude/commands/minder/harness/admin/doctor.md"])

    def test_no_commands_directory_is_not_a_finding(self):
        """A base that ships no commands is not thereby broken."""
        report = enginechecks.Report()
        enginechecks.check_commands_namespaced(self.tmpdir, report)
        self.assertEqual(len(report), 0)


class FamilyCommandBoundaryTests(unittest.TestCase):
    """A family verb covers a name, not a product — so it has to say what it does NOT reach.

    `/minder:update` reads as "update everything under this name" and today moves one thing. The
    gap is closed by saying so, in the command itself, every time it reports. Left unsaid, the
    person hears "done" about a setup that only half moved — the same defect class as an updater
    that counts a failed checkout as a replacement.
    """

    HEADING = "## The family boundary"
    FAMILY = ("doctor", "sync", "update")

    def test_every_family_command_states_what_it_does_not_reach(self):
        for name in self.FAMILY:
            with self.subTest(name):
                body = (ENGINE_ROOT / ".claude" / "commands" / "minder"
                        / ("%s.md" % name)).read_text(encoding="utf-8")
                self.assertIn(self.HEADING, body,
                              "%s does not say what it leaves out" % name)
                section = body.split(self.HEADING, 1)[1].split("\n## ", 1)[0]
                self.assertIn("Minder Memory", section,
                              "%s does not name the sibling it does not reach" % name)
                # A heading with nothing under it satisfies a substring check and says nothing.
                self.assertGreater(len(section.split()), 40,
                                   "%s has the heading and no statement under it" % name)

    def test_every_family_command_resolves_the_base_before_it_runs_anything(self):
        """A global command that runs `python3 tools/x.py` runs whatever the CURRENT folder holds.

        These three are linked into the person's own command directory, so they fire from inside
        any project. Another repository with a file of the same name would be executed under this
        command's name — so the base has to be established before the first invocation, not assumed
        from the working directory.
        """
        for name in self.FAMILY:
            with self.subTest(name):
                body = (ENGINE_ROOT / ".claude" / "commands" / "minder"
                        / ("%s.md" % name)).read_text(encoding="utf-8")
                self.assertIn("HARNESS HOME", body,
                              "%s never says how to find the base it acts on" % name)
                first_run = body.find("python3 tools/")
                if first_run == -1:
                    continue
                self.assertLess(body.index("HARNESS HOME"), first_run,
                                "%s invokes a tool before establishing where to run it" % name)

    def test_no_family_command_promises_a_verb_that_does_not_exist(self):
        """Sending somebody to `/minder:mem:update` is worse than saying nothing: it does not exist.

        The sibling ships `recap` and `search` and no counterpart for these three, so any pointer
        of that shape is invented — and an invented pointer reads exactly like a real one.
        """
        for name in self.FAMILY:
            with self.subTest(name):
                body = (ENGINE_ROOT / ".claude" / "commands" / "minder"
                        / ("%s.md" % name)).read_text(encoding="utf-8")
                for invented in ("/minder:mem:update", "/minder:mem:sync", "/minder:mem:doctor"):
                    self.assertNotIn(invented, body,
                                     "%s points at %s, which the sibling does not ship"
                                     % (name, invented))


class RepositoryAddressTests(unittest.TestCase):
    """One repository has several spellings, and three files have to agree on which."""

    FORMS = ("https://github.com/S1lash/minder-harness",
             "https://github.com/S1lash/minder-harness.git",
             "git@github.com:S1lash/minder-harness.git",
             "ssh://git@github.com/S1lash/minder-harness.git")

    def test_every_spelling_of_one_repository_compares_equal(self):
        for form in self.FORMS:
            self.assertTrue(manifest_lib.same_repository(self.FORMS[0], form), form)

    def test_a_different_repository_never_compares_equal(self):
        self.assertFalse(manifest_lib.same_repository(
            self.FORMS[0], "https://github.com/S1lash/someone-elses-base"))
        self.assertFalse(manifest_lib.same_repository("/tmp/engine", "/tmp/other"))

    def test_a_local_path_is_left_alone(self):
        self.assertTrue(manifest_lib.same_repository("/tmp/engine", "/tmp/engine"))

    def test_the_bash_twin_canonicalises_identically(self):
        """[CP-4] install.sh decides which remote is the engine's; a twin that disagrees strips
        somebody's origin, or fails to recognise the engine and never sets one up."""
        if os.name == "nt":
            self.skipTest("no bash here")
        body = re.search(r"^canon_repo\(\) \{.*?^\}", engine_text("install.sh"), re.M | re.S)
        self.assertIsNotNone(body, "install.sh no longer defines canon_repo")
        script = body.group(0) + "\n" + "\n".join('canon_repo "%s"; echo' % f for f in self.FORMS)
        done = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([line for line in done.stdout.split("\n") if line],
                         [manifest_lib._canonical_repository(f) for f in self.FORMS])


class UpdateEndToEndTests(TempCase):
    """The updater against a real remote, on a base that shares no history with the engine."""

    def setUp(self):
        super().setUp()
        root = self.tmpdir
        self.engine, self.base = root / "engine", root / "base"

        self.engine.mkdir()
        write(self.engine, ".engine-manifest.yml", MANIFEST)
        write(self.engine, "rules/canon.md", "new canon\n")
        write(self.engine, "rules/added.md", "arrived with this version\n")
        write(self.engine, "seed.md", "pristine seed\n")
        write(self.engine, "VERSION", "1.0.0\n")
        init_repo(self.engine)
        git(self.engine, "add", "-A")
        git(self.engine, "commit", "-qm", "engine")

        # A base created by copying, then `git init` — no commit in common with the engine.
        self.base.mkdir()
        write(self.base, ".engine-manifest.yml", MANIFEST)
        write(self.base, "rules/canon.md", "old canon\n")
        write(self.base, "seed.md", "pristine seed\nwhat the person added\n")
        write(self.base, "old/gone.md", "the engine stopped shipping this\n")
        write(self.base, "mine/notes.md", "theirs\n")
        write(self.base, "VERSION", "0.9.0\n")
        install_tools(self.base)
        init_repo(self.base)
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "their base")
        git(self.base, "remote", "add", "minder-harness", str(self.engine))

    def test_an_unsaved_edit_to_a_withdrawn_path_stops_the_update(self):
        """The exclusion that lets an interrupted update finish must never hide a real edit.

        Ignoring retired paths when deciding whether an engine path carries local changes is what
        makes convergence possible — but "present here, absent from the release" is equally the
        shape of a file the person is in the middle of editing. Retirement DELETES it, and an
        unsaved edit is in no history anywhere, so getting this wrong destroys work that cannot
        be recovered from anything.
        """
        retiring = MANIFEST.replace("retired:\n  - old/gone.md",
                                    "retired:\n  - old/gone.md\n  - rules/withdrawn.md")
        write(self.engine, ".engine-manifest.yml", retiring)
        git(self.engine, "add", "-A")
        git(self.engine, "commit", "-qm", "withdraw a rule")
        write(self.base, ".engine-manifest.yml", retiring)
        write(self.base, "rules/withdrawn.md", "the engine used to ship this\n")
        # The rest of `rules/` is brought level with the release ON PURPOSE. Leave any other
        # difference in there and the path is dirty for that reason instead, so the test passes
        # whatever the exclusion does — which is how it read green against the broken version.
        write(self.base, "rules/canon.md", "new canon\n")
        write(self.base, "rules/added.md", "arrived with this version\n")
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "carrying the withdrawn rule")

        write(self.base, "rules/withdrawn.md", "the engine used to ship this\nMY UNSAVED WORK\n")

        done = run_update(self.base)
        self.assertEqual(done.returncode, 2,
                         "the update proceeded over an unsaved edit to a path it deletes")
        self.assertIn("rules/withdrawn.md", done.stdout + done.stderr,
                      "it refused without naming the file that would have been lost")
        self.assertIn("MY UNSAVED WORK", (self.base / "rules/withdrawn.md").read_text(),
                      "the unsaved edit was destroyed")

    def test_self_heal_refuses_a_remote_that_is_not_the_engine(self):
        """`--self-heal` overwrites the updater, `tools/lib` and the manifest.

        Apply refuses a remote that matches no declared engine address; if self-heal does not, it is
        simply the way around that refusal — and it replaces the machinery itself out of whatever
        repository happens to carry the expected name.
        """
        declaring = MANIFEST.replace("version: 1.0.0",
                                     "version: 1.0.0\nengine_remote: https://example.invalid/the-engine")
        write(self.base, ".engine-manifest.yml", declaring)
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "declare an address this base does not have")

        done = run_update(self.base, "--self-heal")
        self.assertEqual(done.returncode, 2,
                         "self-heal fetched the machinery from a remote that is not the engine")
        self.assertIn("nothing safe to repair from", done.stdout + done.stderr)

    def test_an_update_interrupted_before_retirement_finishes_on_the_next_run(self):
        """Convergence has to survive the run being killed, or it is not convergence.

        Every declared change re-runs on every update precisely so a base at any version lands in
        the same place. That promise is worth nothing if the FIRST interruption strands the base:
        a run killed between the checkout and the retirement pass leaves the withdrawn paths
        sitting beside the new ones, so the engine directory differs from the ref by exactly the
        files that are about to be deleted. Read as a local edit, that makes the next run refuse
        — and nothing the person can do short of git surgery gets them out of it.
        """
        # The shape that actually deadlocks: a retired path INSIDE an engine DIRECTORY. A retired
        # file that sits outside every engine entry cannot reproduce it — the directory then
        # matches the ref, nothing reads as an edit, and the test passes whatever the code does.
        retiring = MANIFEST.replace("retired:\n  - old/gone.md",
                                    "retired:\n  - old/gone.md\n  - rules/withdrawn.md")
        write(self.engine, ".engine-manifest.yml", retiring)
        git(self.engine, "add", "-A")
        git(self.engine, "commit", "-qm", "withdraw a rule")
        write(self.base, ".engine-manifest.yml", retiring)
        write(self.base, "rules/withdrawn.md", "the engine used to ship this\n")
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "carrying the withdrawn rule")

        git(self.base, "fetch", "minder-harness", "main")
        # Exactly what the updater does before it reaches retirement, and nothing after it.
        git(self.base, "checkout", "minder-harness/main", "--", "rules", "VERSION")
        self.assertTrue((self.base / "rules/withdrawn.md").exists(),
                        "fixture is wrong: the withdrawn rule should still be here mid-flight")
        self.assertTrue((self.base / "old/gone.md").exists())

        done = run_update(self.base)
        self.assertEqual(done.returncode, 0,
                         "an interrupted update could not finish itself:\n"
                         + done.stdout + done.stderr)
        self.assertFalse((self.base / "rules/withdrawn.md").exists(),
                         "the withdrawn rule survived, so the run never reached retirement")
        self.assertFalse((self.base / "old").exists())
        self.assertEqual((self.base / "rules/canon.md").read_text(), "new canon\n")
        self.assertEqual((self.base / "mine/notes.md").read_text(), "theirs\n",
                         "the person's own space was touched while recovering")

    def test_update_replaces_the_engine_keeps_the_person_and_drops_what_was_retired(self):
        done = run_update(self.base)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

        self.assertEqual((self.base / "rules/canon.md").read_text(), "new canon\n")
        self.assertTrue((self.base / "rules/added.md").exists())
        self.assertEqual((self.base / "VERSION").read_text().strip(), "1.0.0")

        self.assertEqual((self.base / "seed.md").read_text(),
                         "pristine seed\nwhat the person added\n",
                         "a template seeds once and is never touched again")
        self.assertTrue((self.base / "mine/notes.md").exists())
        self.assertFalse((self.base / "old").exists(), "a retired path must be dropped")

    def test_the_engine_is_found_by_its_address_whatever_the_remote_is_called(self):
        """Renaming the product must not strand every base that already exists.

        The remote's NAME lives in each base's git config, which no manifest section reaches and
        no clone carries — so it cannot be changed by shipping anything. If the updater looked the
        engine up by name, renaming the engine would silently cut off every base already in the world,
        and the fix could only travel through the channel it had just broken. The address is the
        one identifier the engine itself publishes and can move on purpose.
        """
        declared = MANIFEST.replace("version: 1.0.0",
                                    "version: 1.0.0\n\nengine_remote: %s" % self.engine, 1)
        write(self.engine, ".engine-manifest.yml", declared)
        write(self.base, ".engine-manifest.yml", declared)
        git(self.engine, "add", "-A"); git(self.engine, "commit", "-qm", "declare the address")
        git(self.base, "add", "-A"); git(self.base, "commit", "-qm", "same address")

        # The base calls it something else entirely — an older name, or one the person chose.
        git(self.base, "remote", "remove", "minder-harness")
        git(self.base, "remote", "add", "some-other-name", str(self.engine))

        done = run_update(self.base)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((self.base / "rules/canon.md").read_text(), "new canon\n")

    def test_two_spellings_of_one_address_are_one_repository(self):
        """The same repository is written several ways, and all of them have to match.

        A manifest declares `https://host/owner/engine`; git config commonly holds
        `https://host/owner/engine.git` because that is what `git clone` records. Compared literally
        they differ, the engine is not recognised, and the base falls back to matching by name —
        which is exactly the fragility this replaced.
        """
        for a, b in (("https://h/o/engine", "https://h/o/engine.git"),
                     ("https://h/o/engine/", "https://h/o/engine"),
                     ("https://H/O/Engine", "https://h/o/engine")):
            self.assertTrue(manifest_lib.same_repository(a, b), "%s vs %s" % (a, b))
        for a, b in (("https://h/o/engine", "https://h/o/other"),
                     ("https://h/o/engine", ""), ("", "")):
            self.assertFalse(manifest_lib.same_repository(a, b), "%s vs %s" % (a, b))

    def test_the_persons_own_copy_is_never_mistaken_for_the_engine(self):
        """Every base has two remotes, and one of them is the person's private copy.

        `origin` is theirs and is listed first. Matching an address loosely — or not at all —
        makes the updater replace this base's engine paths out of the person's OWN repository, which
        looks like a successful update and is a silent corruption of the standard.
        """
        declared = MANIFEST.replace("version: 1.0.0",
                                    "version: 1.0.0\n\nengine_remote: %s" % self.engine, 1)
        write(self.engine, ".engine-manifest.yml", declared)
        write(self.base, ".engine-manifest.yml", declared)
        git(self.engine, "add", "-A"); git(self.engine, "commit", "-qm", "declare the address")

        # The person's own private copy, holding an older canon, added FIRST.
        theirs = Path(self.tmp.name) / "their-copy"
        theirs.mkdir()
        write(theirs, "rules/canon.md", "the person's stale copy\n")
        write(theirs, "VERSION", "0.0.1\n")
        write(theirs, ".engine-manifest.yml", declared)
        init_repo(theirs)
        git(theirs, "add", "-A"); git(theirs, "commit", "-qm", "their copy")

        # `upstream` is an ordinary name for it, and git lists remotes alphabetically — so the
        # person's own copy comes FIRST. Anything that picks a remote by position rather than by
        # address lands on theirs.
        git(self.base, "remote", "remove", "minder-harness")
        git(self.base, "remote", "add", "origin", str(theirs))
        git(self.base, "remote", "add", "upstream", str(self.engine))
        git(self.base, "add", "-A"); git(self.base, "commit", "-qm", "two remotes")

        done = run_update(self.base)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((self.base / "rules/canon.md").read_text(), "new canon\n",
                         "the update came from the person's own copy, not from the engine")
        self.assertEqual((self.base / "VERSION").read_text().strip(), "1.0.0")

    def test_a_seed_added_after_their_clone_still_reaches_them(self):
        # Templates never sync, so without seeding a seed introduced after somebody cloned
        # reaches them never — while the canon arriving in the same update names it as though it
        # were there. Absent is created; present is left exactly alone.
        (self.base / "seed.md").unlink()
        done = run_update(self.base)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((self.base / "seed.md").read_text(), "pristine seed\n")
        self.assertIn("a seed this base never received", done.stdout)

    def test_the_daily_check_stays_quiet_after_it_has_just_run(self):
        """`--max-age` is what `.claude/settings.json` runs at every session start.

        The other check-mode test passes no `--max-age`, so `max_age > 0` is never true there and
        the cache path — the flag's entire reason to exist — goes unexercised. A stuck cache makes
        the daily check silently permanent; a broken one announces the same version every session
        until the person stops reading it.
        """
        first = run_update(self.base, "--check", "--max-age", "86400")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertIn("a newer version of the engine is out", first.stdout)
        self.assertTrue((self.base / ".git" / "minder-harness-update-check").exists(),
                        "the check did not record that it ran")

        again = run_update(self.base, "--check", "--max-age", "86400")
        self.assertEqual(again.returncode, 0)
        self.assertEqual(again.stdout.strip(), "", "it spoke twice within the same window")

        # A window that has passed lets it speak again — a cache that never expires is the same
        # failure as no check at all.
        stale = run_update(self.base, "--check", "--max-age", "0")
        self.assertIn("a newer version of the engine is out", stale.stdout)

    def test_global_wiring_that_names_another_base_is_reported(self):
        """Reported, never edited — it is outside the base (`rules/safety.md`).

        Nothing re-runs the installer, so a base that moves keeps a block pointing at the path it
        no longer occupies, and the canon then reaches that runtime from the wrong place or not
        at all.
        """
        home = Path(self.tmp.name) / "fake-home"
        (home / ".claude").mkdir(parents=True)
        entry = home / ".claude" / "CLAUDE.md"
        original = Path.home

        entry.write_text("<!-- BEGIN MINDER-HARNESS -->\n@/somewhere/else/AGENTS.md\n",
                         encoding="utf-8")
        Path.home = staticmethod(lambda: home)
        self.addCleanup(setattr, Path, "home", original)
        self.assertEqual(update_module.stale_global_wiring(self.base)[0], [str(entry)])

        # Naming this base — by import or by plain path — is not stale.
        entry.write_text("<!-- BEGIN MINDER-HARNESS -->\n@%s/AGENTS.md\n" % self.base,
                         encoding="utf-8")
        self.assertEqual(update_module.stale_global_wiring(self.base)[0], [])
        # An entry this engine never wrote is none of its business.
        entry.write_text("something the person wrote themselves\n", encoding="utf-8")
        self.assertEqual(update_module.stale_global_wiring(self.base)[0], [])

    def test_two_blocks_of_ours_in_one_file_are_reported_not_passed_over(self):
        """The installer refuses this shape; the update must not be the one place it reads as fine.

        Our marker opening twice means an earlier install went wrong. The canon is in that file
        twice with nothing to say which copy is live, and the person will never look unless told.
        """
        home = self.tmpdir / "home"
        (home / ".claude").mkdir(parents=True)
        entry = home / ".claude" / "CLAUDE.md"
        entry.write_text(
            "<!-- BEGIN MINDER-HARNESS -->\n@%s/AGENTS.md\n<!-- END MINDER-HARNESS -->\n"
            "<!-- BEGIN MINDER-HARNESS -->\n@%s/AGENTS.md\n<!-- END MINDER-HARNESS -->\n"
            % (self.base, self.base), encoding="utf-8")
        original = Path.home
        try:
            Path.home = staticmethod(lambda: home)
            stale, conflicting = update_module.stale_global_wiring(self.base)
        finally:
            Path.home = original
        self.assertEqual(conflicting, [str(entry)], "a doubled canon was passed over in silence")
        self.assertEqual(stale, [])

    def test_a_dry_run_reports_a_refusal_instead_of_crashing(self):
        """A preview that raises tells the person nothing about what an update would do.

        The guards inside the migrate and retire passes read `engine:` and `exclude:` from the
        manifest on disk, which a real run reads only after the replacement — so a release that
        moves a path between sections can make the two disagree. Whatever else that produces, the
        preview has to come back with an answer.
        """
        declared = MANIFEST.replace("retired:", "retired:\n  - mine/notes.md")
        write(self.engine, ".engine-manifest.yml", declared)
        git(self.engine, "add", "-A")
        git(self.engine, "commit", "-qm", "retire a path this base calls its own")

        done = run_update(self.base, "--dry-run")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("dry-run", done.stdout)
        self.assertTrue((self.base / "mine/notes.md").exists(), "a dry run deleted something")

    def test_an_unreadable_check_cache_does_not_skip_the_check(self):
        cache = self.base / ".git" / "minder-harness-update-check"
        cache.write_text("not json at all", encoding="utf-8")
        done = run_update(self.base, "--check", "--max-age", "86400")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("a newer version of the engine is out", done.stdout)

    def test_unsaved_work_at_a_path_this_release_claims_stops_the_update(self):
        """The likeliest collision of all, and the one pass that must not run after the loss.

        Until this run the path was the person's own space, so whatever sits there is theirs.
        Guarding only the paths the LOCAL manifest calls the engine's replaced it silently: exit 0,
        no warning, unrecoverable — the one outcome `rules/git-safety.md` exists to prevent.
        """
        write(self.base, "NOTICE.md", "the person's own file\n")
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "their file")
        write(self.base, "NOTICE.md", "the person's own file\nwith unsaved edits\n")

        widened = MANIFEST.replace("  - rules/", "  - rules/\n  - NOTICE.md")
        write(self.engine, ".engine-manifest.yml", widened)
        write(self.engine, "NOTICE.md", "the engine's version\n")
        git(self.engine, "add", "-A")
        git(self.engine, "commit", "-qm", "claim NOTICE.md for the engine")

        done = run_update(self.base)
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("NOTICE.md", done.stdout + done.stderr)
        self.assertIn("with unsaved edits", (self.base / "NOTICE.md").read_text(),
                      "the update destroyed work it had never guarded")

    def test_a_release_cannot_unprotect_the_persons_space_and_then_delete_it(self):
        """The guard compared the incoming manifest against itself.

        `retire` read `exclude:` from disk, and by the time it ran the update had already
        replaced the manifest — so both sides of the comparison came from the release. A release
        shipping `exclude:` empty could name the person's own directories under `retired:` and
        have them deleted, then instruct the agent to save, propagating the deletion to their
        only backup. Protection may widen in an update; it may never narrow.
        """
        hostile = MANIFEST.replace("exclude:\n  - mine/", "exclude: []")
        hostile = hostile.replace("retired:\n  - old/gone.md", "retired:\n  - mine/")
        write(self.engine, ".engine-manifest.yml", hostile)
        git(self.engine, "add", "-A")
        git(self.engine, "commit", "-qm", "a release that unprotects the person's space")

        done = run_update(self.base)
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("belong to the person", done.stdout + done.stderr)
        self.assertTrue((self.base / "mine" / "notes.md").exists(),
                        "a release deleted the person's own space")

    def test_moving_the_persons_own_files_is_shown_before_it_happens(self):
        """`rules/safety.md` requires a deletion or move to be seen before it runs.

        Replacement is the engine's own space and needs no ceremony, but `migrations:` exists
        precisely to rearrange the PERSON's — and an update carried them out on the strength of a
        manifest it had just fetched, reporting them afterwards.
        """
        declared = MANIFEST.replace(
            "retired:", "migrations:\n  - move pointers -> knowledge/pointers | note\n\nretired:")
        write(self.engine, ".engine-manifest.yml", declared)
        git(self.engine, "add", "-A")
        git(self.engine, "commit", "-qm", "declare a move")
        write(self.base, "pointers/stack.md", "theirs\n")
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "their pointers")

        shown = run_update(self.base)
        self.assertEqual(shown.returncode, 0, shown.stdout + shown.stderr)
        self.assertIn("their own files, not the engine's", shown.stdout)
        self.assertTrue((self.base / "pointers" / "stack.md").exists(),
                        "the move happened without being confirmed")
        # The replacement half still ran: only the person's own space waits on them.
        self.assertEqual((self.base / "rules/canon.md").read_text(), "new canon\n")

        done = run_update(self.base, "--confirm")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue((self.base / "knowledge" / "pointers" / "stack.md").exists())

    def test_a_directory_the_release_adds_to_engine_is_matched_however_it_is_written(self):
        """`engine:` entries are compared against paths, so the trailing slash has to come off.

        The incoming list is read separately from the local one, and both readers strip it. With
        only the local one stripping, a release adding `doctrine/` rather than `doctrine` is
        compared as a path that does not exist and quietly counted as absent.
        """
        widened = MANIFEST.replace("  - rules/", "  - rules/\n  - extra/")
        write(self.engine, ".engine-manifest.yml", widened)
        write(self.engine, "extra/note.md", "a directory this release introduces\n")
        git(self.engine, "add", "-A")
        git(self.engine, "commit", "-qm", "widen engine with a directory")

        done = run_update(self.base)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue((self.base / "extra" / "note.md").exists(),
                        "a directory added to engine: this release did not land")
        # And a path the base ALREADY had must not be reported as newly introduced: the two
        # lists are read by different code paths, and only one of them stripped the slash, so
        # `rules/` and `rules` compared as different entries.
        self.assertNotIn("rules (an engine path this release introduced)", done.stdout)
        self.assertIn("extra (an engine path this release introduced)", done.stdout)

    def test_a_seed_this_release_introduces_lands_in_the_run_that_ships_it(self):
        """The asymmetry that hid this: the same case for `engine:` was tested and this was not.

        The existing seeding test deletes a seed the base's OWN manifest already declares, which
        never exercises a template the incoming release introduces — the headline case the
        seeding docstring promises. Preview and apply disagreed: the dry-run read the incoming
        list and said the seed would arrive, the run read the local one and did not deliver it.
        """
        widened = MANIFEST.replace("  - seed.md", "  - seed.md\n  - newseed.md")
        write(self.engine, ".engine-manifest.yml", widened)
        write(self.engine, "newseed.md", "a seed this release introduces\n")
        git(self.engine, "add", "-A")
        git(self.engine, "commit", "-qm", "introduce a seed")

        preview = run_update(self.base, "--dry-run")
        self.assertIn("newseed.md", preview.stdout, "the dry-run did not promise the seed")
        done = run_update(self.base)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue((self.base / "newseed.md").exists(),
                        "the dry-run promised a seed the run did not deliver")
        self.assertIn("newseed.md", done.stdout)

    def test_a_path_this_release_adds_to_engine_lands_in_the_run_that_ships_it(self):
        """The manifest is itself one of the paths being replaced.

        Read the engine list only from the copy on disk and a file the release introduces is
        invisible to the run that ships it: it appears one whole update late, and the run that
        should have carried it says nothing at all.
        """
        widened = MANIFEST.replace("  - rules/", "  - rules/\n  - GLOSSARY.md")
        write(self.engine, ".engine-manifest.yml", widened)
        write(self.engine, "GLOSSARY.md", "an engine path this release introduces\n")
        git(self.engine, "add", "-A")
        git(self.engine, "commit", "-qm", "widen engine")

        done = run_update(self.base)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue((self.base / "GLOSSARY.md").exists(),
                        "a newly declared engine path did not land in the run that shipped it")
        self.assertIn("an engine path this release introduced", done.stdout)

    def _release_adopting(self, relpath):
        widened = MANIFEST.replace("  - rules/", "  - rules/\n  - %s" % relpath)
        write(self.engine, ".engine-manifest.yml", widened)
        write(self.engine, relpath, "what the engine ships here\n")
        git(self.engine, "add", "-A")
        git(self.engine, "commit", "-qm", "adopt a path")

    def test_an_adopted_path_never_lands_on_top_of_something_they_never_saved(self):
        """The case the guard on adoption is FOR, and the one `git diff` cannot see.

        Until this run the path was the person's own space, so whatever is sitting there is theirs
        — and a file they made and never added is in no history anywhere. `git checkout <ref> --
        <path>` writes straight over it, with no diff to show afterwards and nothing said.
        """
        self._release_adopting("GLOSSARY.md")
        theirs = self.base / "GLOSSARY.md"
        theirs.write_text("MINE, never added to anything\n", encoding="utf-8")

        done = run_update(self.base)
        self.assertNotEqual(done.returncode, 0, "it wrote over a file that exists in no history")
        self.assertEqual(theirs.read_text(encoding="utf-8"), "MINE, never added to anything\n",
                         "their unsaved file was replaced by the engine's version")
        self.assertIn("GLOSSARY.md", done.stdout + done.stderr,
                      "the refusal does not name the path that is in the way")

    def test_an_adopted_path_covered_by_an_ignore_rule_is_still_theirs(self):
        """`.gitignore` says "do not version this", never "this is disposable"."""
        self._release_adopting("GLOSSARY.md")
        write(self.base, ".gitignore", "GLOSSARY.md\n")
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "their ignore rule")
        theirs = self.base / "GLOSSARY.md"
        theirs.write_text("MINE, and ignored\n", encoding="utf-8")

        done = run_update(self.base)
        self.assertNotEqual(done.returncode, 0, "an ignored file of theirs was treated as rubbish")
        self.assertEqual(theirs.read_text(encoding="utf-8"), "MINE, and ignored\n")

    def test_a_stray_file_inside_an_engine_directory_does_not_block_the_update(self):
        """The other direction, and the one that would deadlock every base that ever collected one.

        `git checkout <ref> -- <dir>` writes the paths the REF holds and leaves everything else
        alone, so a note of theirs under `rules/` that the engine does not ship survives an update
        untouched. Refusing over it would stop every future update to buy nothing.
        """
        stray = self.base / "rules" / "a-note-of-their-own.md"
        stray.write_text("mine, and in the way of nothing\n", encoding="utf-8")

        done = run_update(self.base)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(stray.read_text(encoding="utf-8"), "mine, and in the way of nothing\n",
                         "an update deleted a file the engine never ships")
        self.assertEqual((self.base / "rules" / "canon.md").read_text(encoding="utf-8"),
                         "new canon\n", "the update did not run")

    def test_a_regenerable_artefact_at_an_adopted_path_does_not_block_the_update(self):
        """The list of what is disposable is a fixed list of NAMES, and it has to still work."""
        self._release_adopting("GLOSSARY.md")
        junk = self.base / "__pycache__"
        junk.mkdir()
        (junk / "stale.pyc").write_text("bytecode", encoding="utf-8")

        done = run_update(self.base)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue((self.base / "GLOSSARY.md").exists(),
                        "the adopted path did not land")

    def test_a_dry_run_previews_what_the_release_declares_not_what_the_base_knows(self):
        """Moves and deletions are the two operations review-before-the-fact exists for."""
        declared = MANIFEST.replace(
            "retired:",
            "migrations:\n  - move pointers -> knowledge/pointers | note\n\nretired:")
        declared = declared.replace("retired:\n", "retired:\n  - old/gone.md\n", 1)
        write(self.engine, ".engine-manifest.yml", declared)
        git(self.engine, "add", "-A")
        git(self.engine, "commit", "-qm", "declare a move and a retirement")
        write(self.base, "pointers/stack.md", "theirs\n")
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "their pointers")

        done = run_update(self.base, "--dry-run")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("move pointers to knowledge/pointers", done.stdout)
        self.assertIn("drop old/gone.md", done.stdout)
        self.assertTrue((self.base / "pointers/stack.md").exists(), "a dry run changed something")

    def test_a_blocked_move_does_not_cancel_an_unrelated_deletion(self):
        """The two passes are independent, so one refusing must not silently skip the other.

        Returning on the first refusal leaves every declared deletion undone for as long as an
        unrelated move stays blocked, and says nothing about it.
        """
        declared = MANIFEST.replace(
            "retired:",
            "migrations:\n  - move pointers -> knowledge/pointers | note\n\nretired:")
        write(self.engine, ".engine-manifest.yml", declared)
        git(self.engine, "add", "-A")
        git(self.engine, "commit", "-qm", "declare the move")
        write(self.base, "pointers/stack.md", "theirs\n")
        write(self.base, "knowledge/pointers/already.md", "in the way\n")
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "a destination already occupied")

        done = run_update(self.base, "--confirm")
        self.assertNotEqual(done.returncode, 0, "a blocked move must not report success")
        self.assertTrue((self.base / "pointers/stack.md").exists(), "the move must not be forced")
        self.assertFalse((self.base / "old").exists(),
                         "the unrelated retirement was skipped because the move was blocked")

    def test_a_move_awaiting_confirmation_does_not_hold_back_a_retirement(self):
        """The engine withdrawing its own path needs nobody's permission, and waited for one anyway.

        A move rearranges the PERSON's files, so it is shown before it runs. Retirement is the
        other half of replacement and touches only what the engine owns. Gating the second on the
        first leaves every declared deletion undone for as long as the move stays unconfirmed —
        indefinitely, if the person never comes back to it — while the output says only that
        nothing has been moved.
        """
        declared = MANIFEST.replace(
            "retired:\n", "retired:\n  - old/gone.md\n", 1).replace(
            "retired:",
            "migrations:\n  - move pointers -> knowledge/pointers | note\n\nretired:")
        write(self.engine, ".engine-manifest.yml", declared)
        git(self.engine, "add", "-A")
        git(self.engine, "commit", "-qm", "declare a move and a retirement")
        write(self.base, "pointers/stack.md", "theirs\n")
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "their pointers")

        done = run_update(self.base)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("move pointers to knowledge/pointers", done.stdout)
        self.assertTrue((self.base / "pointers/stack.md").exists(),
                        "their files moved without being confirmed")
        self.assertFalse((self.base / "old").exists(),
                         "the retirement waited on a confirmation that was not about it")
        self.assertIn("what the engine withdrew is gone", done.stdout,
                      "it deleted something and said nothing had happened")

    def test_a_declared_move_is_carried_by_the_update_itself(self):
        # End to end: the engine declares it, the base takes the update, the path has moved. The
        # declaration is read from the manifest that arrives in the SAME run — which is why it is
        # data and not code in the updater, whose own new code would take effect an update late.
        declared = MANIFEST.replace(
            "retired:",
            "migrations:\n  - move pointers -> knowledge/pointers | your notes may name the old place\n\nretired:")
        write(self.engine, ".engine-manifest.yml", declared)
        git(self.engine, "add", "-A")
        git(self.engine, "commit", "-qm", "declare the move")
        write(self.base, "pointers/stack.md", "theirs\n")
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "their pointers")

        # Shown first: a move rearranges the person's own files, so they see it before it runs.
        shown = run_update(self.base)
        self.assertEqual(shown.returncode, 0, shown.stdout + shown.stderr)
        self.assertIn("move pointers to knowledge/pointers", shown.stdout)
        self.assertTrue((self.base / "pointers").exists(), "it moved without being confirmed")

        done = run_update(self.base, "--confirm")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse((self.base / "pointers").exists())
        self.assertEqual((self.base / "knowledge/pointers/stack.md").read_text(), "theirs\n")
        self.assertIn("may name the old place", done.stdout)

        # And it converges: a second update has nothing left to carry.
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "saved")
        again = run_update(self.base)
        self.assertNotIn("moved pointers", again.stdout)

    def test_the_base_follows_the_engine_when_the_engine_publishes_a_new_address(self):
        # The remote lives in git config, which no manifest section reaches. Publishing the new
        # address a release BEFORE the move is the only way a base can follow: by the time the engine
        # moves, everyone is already pointed at where it went.
        moved = MANIFEST.replace("version: 1.0.0",
                                 "version: 1.0.0\n\nengine_remote: https://example.invalid/moved")
        write(self.engine, ".engine-manifest.yml", moved)
        git(self.engine, "add", "-A")
        git(self.engine, "commit", "-qm", "publish the new address")

        done = run_update(self.base)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(
            git(self.base, "remote", "get-url", "minder-harness").stdout.strip(),
            "https://example.invalid/moved")
        self.assertIn("the engine now lives at", done.stdout)

    def test_a_second_run_changes_nothing_and_says_so(self):
        run_update(self.base)
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "saved")
        done = run_update(self.base)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("0 changed", done.stdout)
        self.assertIn("already current", done.stdout)

    def test_dry_run_applies_nothing(self):
        done = run_update(self.base, "--dry-run")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((self.base / "rules/canon.md").read_text(), "old canon\n")
        self.assertTrue((self.base / "old/gone.md").exists())

    def test_unsaved_edits_in_engine_space_stop_the_update(self):
        write(self.base, "rules/canon.md", "the person edited an engine path\n")
        done = run_update(self.base)
        self.assertEqual(done.returncode, 2)
        self.assertIn("unsaved local edits", done.stderr)
        self.assertEqual((self.base / "rules/canon.md").read_text(),
                         "the person edited an engine path\n", "nothing may be overwritten")

    def test_a_base_with_no_engine_remote_says_so_instead_of_failing_obscurely(self):
        git(self.base, "remote", "remove", "minder-harness")
        done = run_update(self.base)
        self.assertEqual(done.returncode, 2)
        self.assertIn("not connected to the repository it came from", done.stderr)

    def test_a_retired_path_reaching_the_persons_space_refuses_and_deletes_nothing(self):
        broken = MANIFEST.replace("  - old/gone.md", "  - mine/notes.md")
        write(self.engine, ".engine-manifest.yml", broken)
        git(self.engine, "add", "-A")
        git(self.engine, "commit", "-qm", "bad retirement")
        write(self.base, ".engine-manifest.yml", broken)
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "same manifest")

        done = run_update(self.base)
        self.assertEqual(done.returncode, 2)
        self.assertIn("belong to the person", done.stderr)
        self.assertTrue((self.base / "mine/notes.md").exists())

    def test_a_retired_directory_holding_untracked_work_refuses_and_deletes_nothing(self):
        """The least recoverable thing there is, and `git diff` cannot see it.

        A retired path is removed with `rmtree`. The dirt check has to answer about the whole path,
        and a file the person created and never added is invisible to `git diff` — it is in no
        history anywhere, including their own, so getting this wrong is not a stale file, it is
        work that is gone with nothing to restore it from.
        """
        retiring = MANIFEST.replace("  - old/gone.md", "  - legacy/")
        for repo in (self.engine, self.base):
            write(repo, ".engine-manifest.yml", retiring)
        write(self.base, "legacy/shipped.md", "engine content\n")
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "a base carrying the path about to be retired")
        git(self.engine, "add", "-A")
        git(self.engine, "commit", "-qm", "retire it")

        # Created, never added. `git diff` and `git diff --cached` both call this clean.
        theirs = self.base / "legacy" / "my-notes.md"
        theirs.write_text("WORK THAT EXISTS NOWHERE ELSE\n", encoding="utf-8")

        done = run_update(self.base)
        self.assertNotEqual(done.returncode, 0, "it proceeded over untracked work")
        self.assertTrue(theirs.exists(), "untracked work inside a retired path was deleted")
        self.assertEqual(theirs.read_text(encoding="utf-8"),
                         "WORK THAT EXISTS NOWHERE ELSE\n", "their file was rewritten")

    def test_ignored_content_is_judged_by_name_not_by_the_ignore_rule(self):
        """`.gitignore` says "do not version this", never "this is disposable".

        A key or a local config under an ignore rule is exactly the shape that exists in no history
        anywhere. Trusting the rule and deleting whatever it covers reads as prudent and is the
        most expensive way to be wrong. But the reverse deadlocks: a `__pycache__` nobody can be
        asked to clear would refuse the retirement on every run, forever.
        """
        write(self.base, "legacy/shipped.md", "engine content\n")
        write(self.base, ".gitignore", "*.pyc\nlegacy/private/\n")
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "a base with ignore rules")

        probe = update_module.retired_path_is_dirty
        self.assertFalse(probe(self.base, "legacy"), "a clean path was called dirty")

        (self.base / "legacy" / "private").mkdir(parents=True)
        self.assertFalse(probe(self.base, "legacy"),
                         "an EMPTY ignored directory blocks retirement forever")

        (self.base / "legacy" / "__pycache__").mkdir()
        (self.base / "legacy" / "__pycache__" / "a.pyc").write_text("junk", encoding="utf-8")
        self.assertFalse(probe(self.base, "legacy"),
                         "a regenerable artefact blocks retirement forever")

        (self.base / "legacy" / "private" / "recovery-key").write_text("SECRET", encoding="utf-8")
        self.assertTrue(probe(self.base, "legacy"),
                        "an irreplaceable file under an ignore rule was about to be deleted")

    def test_a_path_git_cannot_answer_about_is_never_assumed_clean(self):
        """The whole defence against a broken repository reading as "safe to delete".

        `git status` exits non-zero with empty output when the object store is unreadable. Taken at
        face value that is indistinguishable from "nothing of theirs is here", and the next step is
        `rmtree`.
        """
        write(self.base, "legacy/shipped.md", "engine content\n")
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "clean")
        self.assertFalse(update_module.retired_path_is_dirty(self.base, "legacy"))

        # Isolated on purpose. A broken repository fails the `git diff` probes too, so a test that
        # merely breaks one proves the property and leaves this line free to be deleted. Only the
        # status call is made to fail here, which is the shape it alone answers for.
        real = update_module.git

        def only_status_fails(*args, **kwargs):
            if "status" in args:
                return type(real("--version", root=self.base))(1, "", "boom")
            return real(*args, **kwargs)

        update_module.git = only_status_fails
        try:
            self.assertTrue(update_module.retired_path_is_dirty(self.base, "legacy"),
                            "a question nothing could answer was read as 'nothing of theirs here'")
        finally:
            update_module.git = real

        shutil.rmtree(self.base / ".git" / "objects")
        self.assertTrue(update_module.retired_path_is_dirty(self.base, "legacy"),
                        "a repository nothing could read was treated as holding nothing")

    def test_content_hidden_by_a_local_exclude_is_still_the_persons(self):
        """`.git/info/exclude` and `core.excludesFile` are invisible to a plain status.

        They are also where a person hides exactly the file they would never want published — so a
        retirement that asks only the default question deletes it without ever seeing it.
        """
        write(self.base, "legacy/shipped.md", "engine content\n")
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "clean")
        (self.base / ".git" / "info").mkdir(exist_ok=True)
        (self.base / ".git" / "info" / "exclude").write_text("legacy/vault/\n", encoding="utf-8")
        (self.base / "legacy" / "vault").mkdir(parents=True)
        (self.base / "legacy" / "vault" / "key").write_text("SECRET", encoding="utf-8")
        self.assertTrue(update_module.retired_path_is_dirty(self.base, "legacy"),
                        "a file hidden by a local exclude was about to be deleted unseen")

    def test_a_line_ending_conversion_is_not_an_edit(self):
        """`status` calls a CRLF checkout modified; `git diff` — which converts — does not.

        Believing `status` here refuses every update forever on a Windows checkout, and the person
        running `git diff` to find what they supposedly changed is shown nothing at all.
        """
        write(self.base, ".gitattributes", "* text=auto eol=lf\n")
        (self.base / "legacy").mkdir(exist_ok=True)
        (self.base / "legacy" / "a.md").write_bytes(b"engine line 1\nengine line 2\n")
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "lf in the index")
        (self.base / "legacy" / "a.md").write_bytes(b"engine line 1\r\nengine line 2\r\n")
        self.assertFalse(update_module.retired_path_is_dirty(self.base, "legacy"),
                         "a line-ending conversion was read as the person's edit")

    def test_a_retired_directory_that_is_genuinely_clean_is_not_called_dirty(self):
        """The other direction: refusing on a clean path deadlocks the base forever."""
        write(self.base, "legacy/shipped.md", "engine content\n")
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "clean")
        self.assertEqual(
            update_module.dirty_engine_paths(self.base, "HEAD", [], ["legacy"]), [],
            "a clean retired path was reported as carrying the person's work")

    def test_check_mode_reports_a_newer_version_and_changes_nothing(self):
        done = run_update(self.base, "--check")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("1.0.0", done.stdout)
        self.assertEqual((self.base / "rules/canon.md").read_text(), "old canon\n")


class UpdaterRefreshesItselfFirstTests(TempCase):
    """A release's declarations are carried out by that release's own code, not the previous one.

    The manifest read is the incoming one; the code executing it is whatever is on disk. So
    `retired:` and `migrations:` — the two passes that DELETE and MOVE — used to be run by the
    version before the one that declared them, and a fix shipped for either arrived one run after
    the release that needed it.
    """

    MANIFEST = ("version: 1.0.0\n\nengine:\n  - rules/\n  - VERSION\n"
                "  - .engine-manifest.yml\n  - tools/update.py\n  - tools/lib/\n\n"
                "template:\n  - seed.md\n\nexclude:\n  - mine/\n\nretired:\n")
    MARK = "# SHIPPED BY THE RELEASE UNDER TEST\n"

    def setUp(self):
        super().setUp()
        self.engine, self.base = self.tmpdir / "engine", self.tmpdir / "base"
        for repo in (self.engine, self.base):
            repo.mkdir()
            write(repo, ".engine-manifest.yml", self.MANIFEST)
            write(repo, "seed.md", "pristine seed\n")
            install_tools(repo)
        write(self.engine, "rules/canon.md", "new canon\n")
        write(self.engine, "VERSION", "1.0.0\n")
        write(self.base, "rules/canon.md", "old canon\n")
        write(self.base, "VERSION", "0.9.0\n")
        write(self.base, "mine/notes.md", "theirs\n")

    def _release(self, updater_text=None):
        if updater_text is not None:
            write(self.engine, "tools/update.py", updater_text)
        init_repo(self.engine)
        git(self.engine, "add", "-A")
        git(self.engine, "commit", "-qm", "engine")
        init_repo(self.base)
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "their base")
        git(self.base, "remote", "add", "minder-harness", str(self.engine))

    def _marked_updater(self):
        return self.MARK + (ENGINE_ROOT / "tools" / "update.py").read_text(encoding="utf-8")

    def test_the_new_updater_lands_and_runs_before_the_passes_that_delete(self):
        self._release(self._marked_updater())
        done = run_update(self.base)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn(self.MARK.strip(),
                      (self.base / "tools" / "update.py").read_text(encoding="utf-8"),
                      "the base is still carrying the previous updater")
        self.assertIn("bringing the updater itself up to date first", done.stdout)
        self.assertEqual(done.stdout.count("bringing the updater itself up to date first"), 1,
                         "it refreshed more than once — a loop, not a handover")
        self.assertEqual((self.base / "rules" / "canon.md").read_text(encoding="utf-8"),
                         "new canon\n", "the main pass did not run after the handover")

    def test_machinery_that_already_matches_is_not_re_executed(self):
        """Re-running the process on every update would double the cost of every single one."""
        self._release()
        done = run_update(self.base)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn("bringing the updater itself up to date", done.stdout)

    def test_a_dry_run_never_rewrites_the_machinery(self):
        """A preview that changes the thing doing the previewing is not a preview."""
        self._release(self._marked_updater())
        before = (self.base / "tools" / "update.py").read_text(encoding="utf-8")
        done = run_update(self.base, "--dry-run")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((self.base / "tools" / "update.py").read_text(encoding="utf-8"), before,
                         "a dry run replaced the updater on disk")
        self.assertIn("dry-run", done.stdout)

    def test_machinery_the_person_edited_is_not_overwritten_a_step_early(self):
        """These are engine paths like any other, and the check that catches an edit runs later.

        Refreshing before it would destroy their work one step before the thing that exists to
        notice it.
        """
        self._release(self._marked_updater())
        theirs = self.base / "tools" / "lib" / "manifest.py"
        theirs.write_text(theirs.read_text(encoding="utf-8") + "\n# mine\n", encoding="utf-8")
        done = run_update(self.base)
        self.assertIn("# mine", theirs.read_text(encoding="utf-8"),
                      "an uncommitted edit to the machinery was overwritten before the check")
        self.assertNotEqual(done.returncode, 0, "it proceeded over an edited engine path")

    def test_a_release_whose_updater_will_not_parse_changes_nothing(self):
        """Landing it would leave a base that cannot update again and cannot repair itself.

        `--self-heal` fetches the same release, so the broken file would come straight back.
        """
        self._release("def (this is not python\n")
        done = run_update(self.base)
        self.assertNotEqual(done.returncode, 0, "a release that cannot run was applied anyway")
        self.assertIn("will not parse", done.stdout + done.stderr)
        self.assertEqual((self.base / "rules" / "canon.md").read_text(encoding="utf-8"),
                         "old canon\n", "the base was changed by a release that cannot run")
        compile((self.base / "tools" / "update.py").read_text(encoding="utf-8"), "u", "exec")

    def test_a_release_with_a_broken_library_module_changes_nothing(self):
        """The half a check on `update.py` alone cannot see, and the costliest half.

        `update.py` imports `lib` at the top of itself, unguarded, so a release with a broken
        module there passes a check that reads only the entry file — then lands, and the
        re-execution dies at the import. Every later run dies at the same line, before `argparse`,
        so `--self-heal` (declared below those imports) can never be reached to repair it.
        """
        write(self.engine, "tools/lib/brand_new.py", "# a module this release adds\n")
        write(self.engine, "tools/lib/manifest.py", "def (this is not python\n")
        self._release()
        theirs = self.base / "tools" / "lib" / "scratch.txt"
        theirs.write_text("untracked, and mine\n", encoding="utf-8")

        done = run_update(self.base)
        self.assertNotEqual(done.returncode, 0, "a release that cannot be imported was applied")
        self.assertIn("will not parse", done.stdout + done.stderr)
        self.assertIn("tools/lib/manifest.py", done.stdout + done.stderr,
                      "the refusal does not say which file is broken")

        # Still a working base, not one that dies at the import from now on.
        compile((self.base / "tools" / "lib" / "manifest.py").read_text(encoding="utf-8"),
                "manifest", "exec")
        self.assertFalse((self.base / "tools" / "lib" / "brand_new.py").exists(),
                         "the rollback left behind a module the release added")
        self.assertEqual(theirs.read_text(encoding="utf-8"), "untracked, and mine\n",
                         "the rollback deleted an untracked file that was the person's")
        self.assertEqual((self.base / "rules" / "canon.md").read_text(encoding="utf-8"),
                         "old canon\n", "a release that cannot run still changed the base")

        again = run_update(self.base)
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("will not parse", again.stdout + again.stderr,
                      "the second run crashed instead of refusing — the base is broken")

    def test_an_update_interrupted_after_the_handover_converges_on_the_next_run(self):
        """New machinery, old content is a real state — a killed run leaves exactly that."""
        self._release(self._marked_updater())
        write(self.base, "tools/update.py", self._marked_updater())
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "as an interrupted run would leave it")
        done = run_update(self.base)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn("bringing the updater itself up to date", done.stdout)
        self.assertEqual((self.base / "rules" / "canon.md").read_text(encoding="utf-8"),
                         "new canon\n", "the second run did not finish what the first started")


class SyncTests(TempCase):
    """The tool every session runs, on a base of its own."""

    def setUp(self):
        super().setUp()
        self.base = self.tmpdir / "base"
        self.base.mkdir(parents=True)
        (self.base / "tools").mkdir()
        shutil.copy2(ENGINE_ROOT / "tools" / "sync.py", self.base / "tools" / "sync.py")
        init_repo(self.base)
        write(self.base, "note.md", "first\n")
        write(self.base, ".gitattributes", "* text=auto\n")
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "start")

    def run_sync(self, *args):
        return run_tool(self.base, "sync.py", *args)

    def test_a_base_with_no_remote_is_told_it_lives_on_one_machine(self):
        # This fixture has no remote, which is the loudest state there is — not a quiet one.
        done = self.run_sync("status")
        self.assertIn("unsaved here: none", done.stdout)
        self.assertIn("lives only on this machine", done.stdout)

    def test_a_base_in_step_says_nothing_at_all(self):
        """The branch that governs every ordinary session, and nothing covered it.

        A test whose fixture has no remote can never reach it: the tool correctly asks for a
        remote instead, so `unsaved here: none` passed while the directive said the opposite of
        the test's own name.
        """
        remote = Path(self.tmp.name) / "their-remote.git"
        bare_remote(remote)
        git(self.base, "remote", "add", "origin", str(remote))
        git(self.base, "push", "-q", "-u", "origin", "main")
        done = self.run_sync("status")
        self.assertIn("unsaved here: none", done.stdout)
        self.assertIn("nothing — the base is in step", done.stdout)

    def test_a_base_on_more_than_one_branch_is_reported(self):
        """What ARCHITECTURE names as holding invariant 2, and nothing tested.

        Reported rather than enforced on purpose — someone mid-experiment has a reason, and
        refusing to sync would strand them. But a report nothing checks is not a report.
        """
        before = self.run_sync("status")
        self.assertNotIn("branches:", before.stdout, "one branch should say nothing")
        git(self.base, "branch", "experiment")
        after = self.run_sync("status")
        self.assertIn("branches: 2", after.stdout)
        self.assertIn("invisible on a phone", after.stdout)

    def test_a_detached_head_is_named_before_anything_else(self):
        # Every later question — ahead, behind, which branch to push — is meaningless here, so
        # this has to be caught first rather than reported alongside them.
        head = git(self.base, "rev-parse", "HEAD").stdout.strip()
        git(self.base, "checkout", "-q", head)
        done = self.run_sync("status")
        self.assertIn("single branch", done.stdout)

    def test_a_changed_tracked_dotfile_keeps_its_leading_dot(self):
        # Porcelain encodes state in the first two columns, so a MODIFIED tracked file's line
        # begins with a space. Strip the output and that space goes with the first line's dot,
        # naming a file that does not exist. An untracked file starts with `??` and would not
        # reproduce it — the regression needs a tracked one, sorting first.
        write(self.base, ".gitattributes", "* text=auto eol=lf\n")
        done = self.run_sync("status")
        self.assertIn(".gitattributes", done.stdout)
        self.assertNotIn("(gitattributes", done.stdout)

    def test_save_records_the_work_and_says_why(self):
        write(self.base, "note.md", "second\n")
        done = self.run_sync("save", "Record why this exists")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("Record why this exists",
                      git(self.base, "log", "-1", "--format=%B").stdout)

    def test_save_without_a_reason_is_refused(self):
        write(self.base, "note.md", "third\n")
        done = self.run_sync("save")
        self.assertEqual(done.returncode, 2)
        self.assertIn("WHY", done.stdout)

    def test_a_base_with_nowhere_to_send_work_says_it_stayed_here(self):
        write(self.base, "note.md", "fourth\n")
        done = self.run_sync("save", "Keep it local")
        self.assertEqual(done.returncode, 0)
        self.assertIn("recorded on this machine", done.stdout)

    def test_session_start_never_fails_a_session(self):
        write(self.base, "note.md", "fifth\n")
        self.assertEqual(self.run_sync("session-start").returncode, 0)


class VisibilityIsThreeAnswersTests(unittest.TestCase):
    """"Could not check" is not "checked, and private" — and a boolean cannot hold both.

    On a machine with no `gh` the probe fails, and with two answers that failure reads as the safe
    one. Since `gh` is absent on a stock machine, that is the DEFAULT state, and the engine's first
    stated limit — that this base is nowhere for secrets — rests on this single check.
    """

    def setUp(self):
        sys.path.insert(0, str(ENGINE_ROOT / "tools"))
        import importlib
        self.sync = importlib.import_module("sync")

    def _state(self, visibility, kind="github"):
        state = self.sync.BaseState("/somewhere")
        state.is_repo = True
        state.remote_url = "https://github.com/someone/theirs"
        state.remote_kind = kind
        state.remote_visibility = visibility
        return state

    def test_the_probe_answers_none_when_nothing_could_establish_it(self):
        import subprocess as sp
        import types
        real = sp.run
        try:
            for label, fake in (
                    ("gh absent", lambda *a, **k: (_ for _ in ()).throw(OSError("no gh"))),
                    ("gh failed", lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="")),
                    ("gh failed loudly",
                     lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="public\n")),
                    ("gh mumbled", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="?\n")),
            ):
                sp.run = fake
                with self.subTest(label):
                    self.assertIsNone(self.sync.remote_visibility("https://x/y"),
                                      "%s came back as a definite answer" % label)
            sp.run = lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="PUBLIC\n")
            self.assertEqual(self.sync.remote_visibility("https://x/y"), "public")
            sp.run = lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="private\n")
            self.assertEqual(self.sync.remote_visibility("https://x/y"), "private")
        finally:
            sp.run = real

    def test_each_of_the_three_answers_reads_differently(self):
        """Not one `or` across the readers: unknown has to be visible as itself, not as either."""
        seen = {}
        for answer in ("public", "private", None):
            state = self._state(answer)
            seen[answer] = self.sync.describe(state, None, self.sync.directive_for(state))
        self.assertIn("PUBLIC", seen["public"])
        self.assertIn("NOT CHECKED", seen[None], "unknown said nothing at all")
        self.assertNotIn("NOT CHECKED", seen["private"], "a checked private base was warned about")
        self.assertNotIn("PUBLIC", seen[None], "unknown was reported as public")
        self.assertNotEqual(seen[None], seen["private"],
                            "could-not-check reads exactly like checked-and-private")

    def test_the_directive_itself_changes_when_nobody_could_check(self):
        """The body line is not enough: an agent acts on the DIRECTIVE.

        With only the body carrying it, the save is withheld and the one line the agent is told to
        act on can still be "nothing — the base is in step; say nothing about it".
        """
        unknown = self.sync.directive_for(self._state(None))
        private = self.sync.directive_for(self._state("private"))
        self.assertNotEqual(unknown, private,
                            "the directive is identical whether or not anyone could check")
        self.assertIn("private", unknown)
        # It is shared by four modes, so it may not assert that a save was attempted.
        for claim in ("recorded here", "was NOT sent out"):
            self.assertNotIn(claim, unknown,
                             "the shared directive claims a save happened; session-start does none")

    def test_a_remote_on_this_machine_is_not_nagged_about(self):
        """An unanswerable question asked every run buries the one case that matters."""
        state = self._state(None, kind="local")
        state.remote_url = "/var/folders/x/their-remote.git"
        text = self.sync.describe(state, None, self.sync.directive_for(state))
        self.assertNotIn("NOT CHECKED", text)
        self.assertNotIn("NOT CHECKABLE", text)

    def test_a_remote_nothing_can_ask_is_told_apart_from_one_nobody_asked(self):
        """GitLab is not "we failed to check" — it is "this cannot be checked from here".

        Collapsing them costs both ways: demanding `gh` for a remote it cannot read would leave
        that base unable to reach the person's own phone, and reporting it as a mere failure hides
        that no amount of installing anything will ever answer it.
        """
        unasked = self._state(None, kind="github")
        unaskable = self._state(None, kind="network")
        unaskable.remote_url = "https://gitlab.com/someone/theirs"
        first = self.sync.describe(unasked, None, self.sync.directive_for(unasked))
        second = self.sync.describe(unaskable, None, self.sync.directive_for(unaskable))
        self.assertIn("NOT CHECKED", first)
        self.assertIn("NOT CHECKABLE", second)
        self.assertNotEqual(first, second)

    def test_every_remote_form_lands_in_the_right_kind(self):
        """The forms that break a `://` shortcut are exactly the ones that matter."""
        for url, expected in (
                ("/abs/path", "local"), ("../relative", "local"), ("", "local"),
                ("file:///tmp/x.git", "local"), ("C:\\repos\\x", "local"),
                ("\\\\server\\share\\x", "network"), ("host:path", "network"),
                ("https://gitlab.com/a/b", "network"), ("git@gitlab.com:a/b.git", "network"),
                ("https://github.com/a/b", "github"), ("git@github.com:a/b.git", "github"),
                ("ssh://git@github.com/a/b", "github"),
                ("https://user:pw@github.com/a/b", "github")):
            with self.subTest(url):
                self.assertEqual(self.sync.remote_kind(url), expected)


class RefusalWordingTests(unittest.TestCase):
    """A refusal the person cannot read is worse than none."""

    def setUp(self):
        sys.path.insert(0, str(ENGINE_ROOT / "tools"))
        import importlib
        self.sync = importlib.import_module("sync")

    def test_a_private_email_refusal_becomes_an_offer(self):
        directive = self.sync.push_refusal_directive(
            "remote: error: GH007: Your push would publish a private email address.")
        self.assertIn("noreply", directive)
        self.assertNotIn("GH007", directive)

    def test_an_unknown_refusal_still_says_what_it_costs_them(self):
        directive = self.sync.push_refusal_directive("some brand new failure")
        self.assertIn("safe on this machine", directive)


class DivergenceAndOutageTests(TempCase):
    """The two shapes that lose work if they are handled wrong: both sides moved, and no network."""

    def setUp(self):
        super().setUp()
        root = self.tmpdir
        self.remote = root / "remote.git"
        bare_remote(self.remote)
        # Seed the remote first. Cloning an EMPTY repository twice gives each copy its own root
        # commit, which is a different situation entirely — covered by its own test below.
        seed = root / "seed"
        clone(self.remote, seed)
        write(seed, "base.md", "the base\n")
        git(seed, "add", "-A")
        git(seed, "commit", "-qm", "start")
        git(seed, "push", "-q", "origin", "main")
        self.phone = self._clone(root / "phone")
        self.laptop = self._clone(root / "laptop")

    def _clone(self, path: Path) -> Path:
        clone(self.remote, path)
        (path / "tools").mkdir(exist_ok=True)
        shutil.copy2(ENGINE_ROOT / "tools" / "sync.py", path / "tools" / "sync.py")
        return path

    def sync(self, base: Path, *args):
        return run_tool(base, "sync.py", *args)

    def test_work_on_two_sides_is_put_together_and_neither_is_dropped(self):
        write(self.laptop, "on-the-laptop.md", "written at the desk\n")
        self.assertEqual(self.sync(self.laptop, "save", "Laptop work").returncode, 0)

        write(self.phone, "on-the-phone.md", "written on the train\n")
        done = self.sync(self.phone, "save", "Phone work")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

        self.assertTrue((self.phone / "on-the-laptop.md").exists(),
                        "the other side's work must be picked up, not overwritten")
        self.assertTrue((self.phone / "on-the-phone.md").exists())
        landed = git(self.remote, "ls-tree", "-r", "--name-only", "main").stdout
        self.assertIn("on-the-laptop.md", landed)
        self.assertIn("on-the-phone.md", landed)

    def test_sync_depends_on_nothing_but_the_standard_library(self):
        """The one tool that must work when the machinery around it does not.

        `sync.py` runs at every session start and saves unsent work at every announced end, and
        `tools/lib/` is precisely what `--self-heal` exists to repair. Importing from it would
        make the rescue tool fail in the situation it exists for. I tried consolidating the three
        git helpers into one library and this is why only two of them moved.
        """
        source = engine_text("tools/sync.py")
        self.assertNotIn("from lib import", source)
        self.assertNotIn("import lib", source)
        for module in re.findall(r"^import (\w+)", source, re.M):
            self.assertIn(module, ("subprocess", "sys", "os", "json", "time", "re"),
                          "%s is not stdlib — sync.py must run with nothing installed" % module)

    def shipped_python(self):
        """Every python file the engine ships out of `tools/`, asked of the manifest.

        Naming the files instead was how this invariant came to cover three of eight: git moved
        behind `tools/lib/gitrun.py`, every tool started calling git through it, and the list
        stayed as it was. `tools/tests/` is the one exclusion, and only because these very
        assertions quote the banned arguments as literals — a scan of them reads as a violation
        of itself.
        """
        names = [p for p in portability.shipped_paths(ENGINE_ROOT)
                 if p.startswith("tools/") and p.endswith(".py")
                 and not p.startswith("tools/tests/")]
        # A guard whose input quietly shrank passes forever while covering less. Dropping a tool
        # from the manifest is caught by the release gate and not by the structural one, so the
        # scan asks the disk too and fails on anything the manifest stopped naming.
        on_disk = sorted(str(f.relative_to(ENGINE_ROOT)).replace("\\", "/")
                         for f in (ENGINE_ROOT / "tools").rglob("*.py")
                         if "tests" not in f.parts and "__pycache__" not in f.parts)
        self.assertEqual(sorted(names), on_disk,
                         "a python tool on disk that the manifest no longer ships is a tool this "
                         "invariant stopped covering")
        return names

    def test_no_force_or_rebase_is_ever_issued(self):
        # Every python file the engine ships, not the ones somebody remembered: the invariant is
        # about what the engine does to a person's repository, and it follows the code wherever the
        # code goes. Asked of the syntax tree, so what a file SAYS about forcing is not what it
        # is judged on — only what it passes.
        banned = {"--force", "-f", "-fd", "--hard", "rebase", "--force-with-lease",
                  # The quiet equivalents. `rules/git-safety.md` gives them the standing of
                  # `--force`: nothing announces the loss, and the file afterwards simply reads
                  # as it did before the work existed.
                  "restore", "clean", "-D"}
        for name in self.shipped_python():
            source = engine_text(name)
            found = banned & code_strings(source)
            self.assertEqual(found, set(),
                             "%s in %s disables the protection that makes divergence recoverable"
                             % (", ".join(sorted(found)), name))
            self.assertNotIn(("checkout", "--"), git_argument_pairs(source),
                             "%s discards uncommitted work with nothing to announce it" % name)

    def test_the_updater_replaces_and_never_merges(self):
        """The invariant the whole update design rests on.

        An update must never hand the person a conflict inside a file they did not write. That
        holds only because the update issues `checkout` and nothing else — a property nothing
        else states, so a merge added here ships green unless this catches it. It covers every
        pass that touches the person's files, not only the entry point: the move and the sweep
        write to their disk exactly as directly as the updater does.
        """
        banned = {"merge", "cherry-pick", "stash", "reset", "revert"}
        for name in self.shipped_python():
            # `merge` in `sync.py` is the one exception, by design rather than by oversight:
            # putting two sides together IS its job (`rules/device-sync.md` — never force, never
            # drop a side). The other four have no licence there either, and nothing on the
            # update path imports it.
            allowed = {"merge"} if name == "tools/sync.py" else set()
            found = (banned - allowed) & code_strings(engine_text(name))
            self.assertEqual(found, set(),
                             "%s in %s can leave the person adjudicating an engine file they never "
                             "wrote" % (", ".join(sorted(found)), name))

    def test_two_different_bases_pointed_at_one_place_are_named_not_merged(self):
        # A person who runs the installer again on a second machine as a NEW base, then points it
        # at the repository their real base already lives in. git calls it "unrelated histories";
        # the person must be told what it means for them, and nothing may be merged blindly.
        stranger = self.phone.parent / "stranger"
        stranger.mkdir()
        init_repo(stranger)
        (stranger / "tools").mkdir()
        shutil.copy2(ENGINE_ROOT / "tools" / "sync.py", stranger / "tools" / "sync.py")
        write(stranger, "fresh.md", "a brand new base\n")
        git(stranger, "add", "-A")
        git(stranger, "commit", "-qm", "fresh")
        git(stranger, "remote", "add", "origin", str(self.remote))
        git(stranger, "fetch", "-q", "origin", "main")
        git(stranger, "branch", "--set-upstream-to", "origin/main", "main")

        done = self.sync(stranger, "save", "Work on the second machine")
        self.assertEqual(done.returncode, 1)
        self.assertIn("DIFFERENT base", done.stdout)
        self.assertNotIn("fatal:", done.stdout, "raw git output must never reach the person")
        self.assertTrue((stranger / "fresh.md").exists(), "nothing of theirs may be lost")

    def test_an_unreachable_remote_keeps_the_work_and_says_where_it_stands(self):
        git(self.phone, "remote", "set-url", "origin", str(self.phone.parent / "gone.git"))
        write(self.phone, "note.md", "written while offline\n")
        done = self.sync(self.phone, "save", "Offline work")
        self.assertEqual(done.returncode, 1)
        self.assertIn("could not send it out", done.stdout)
        self.assertNotEqual(git(self.phone, "log", "-1", "--format=%s").stdout.strip(), "",
                            "the work must still be recorded locally")


class SelfHealTests(TempCase):
    """The updater ships through the update, so a broken one cannot repair itself normally."""

    def setUp(self):
        super().setUp()
        root = self.tmpdir
        self.engine, self.base = root / "engine", root / "base"

        self.engine.mkdir()
        write(self.engine, ".engine-manifest.yml", MANIFEST)
        write(self.engine, "rules/canon.md", "new canon\n")
        write(self.engine, "seed.md", "pristine seed\n")
        write(self.engine, "VERSION", "1.0.0\n")
        install_tools(self.engine)
        init_repo(self.engine)
        git(self.engine, "add", "-A")
        git(self.engine, "commit", "-qm", "engine")

        self.base.mkdir()
        write(self.base, ".engine-manifest.yml", "version: 0.9.0\n")  # nothing readable in it
        write(self.base, "rules/canon.md", "old canon\n")
        write(self.base, "seed.md", "pristine seed\n")
        write(self.base, "VERSION", "0.9.0\n")
        install_tools(self.base)
        init_repo(self.base)
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "their base")
        git(self.base, "remote", "add", "minder-harness", str(self.engine))

    def test_a_base_that_declares_no_engine_paths_is_not_treated_as_corrupt(self):
        """`engine: []` and a lost `engine:` key read the same and mean opposite things.

        A base can legitimately share no paths with the engine — its own canon, developed past the
        engine's, with the machinery present so that adopting a path later is a decision rather than
        a rebuild. Refusing that base with a corruption error every session teaches its owner to
        ignore the one message that would matter if the file really were damaged.
        """
        write(self.base, ".engine-manifest.yml",
              "version: 1.0.0\n\nengine: []\n\ntemplate: []\n\nexclude:\n  - mine/\n")
        git(self.base, "add", "-A")
        git(self.base, "commit", "-qm", "no engine paths adopted")
        done = run_update(self.base)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("shares no paths with the engine", done.stdout)
        self.assertNotIn("corrupt", done.stdout + done.stderr)

    def test_a_base_whose_manifest_is_unreadable_refuses_rather_than_doing_nothing(self):
        done = run_update(self.base)
        self.assertEqual(done.returncode, 2)
        self.assertIn("no engine: section", done.stderr)
        self.assertEqual((self.base / "rules/canon.md").read_text(), "old canon\n")

    def test_self_heal_restores_the_machinery_and_completes_the_update(self):
        done = run_update(self.base, "--self-heal")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((self.base / "rules/canon.md").read_text(), "new canon\n")
        self.assertEqual((self.base / "VERSION").read_text().strip(), "1.0.0")


@unittest.skipIf(shutil.which("bash") is None, "the shell installer needs bash")
@AUTHOR_SIDE
class InstallerTests(TempCase):
    """The installer, run the way a person runs it — once, on a machine that has nothing."""

    ANSWERS = ("{home}", "mybase", "Русский", "Y", "N", "N", "N",
               "Test Person", "test@example.invalid", "N")

    def setUp(self):
        super().setUp()
        self.home = self.tmpdir / "home"
        self.home.mkdir(parents=True)
        self.src = engine_source(self.tmpdir / "src")

    def install(self):
        answers = "\n".join(a.format(home=self.home) for a in self.ANSWERS) + "\n"
        return run_installer(self.src, self.home, answers, cwd=self.src)

    def _global_entry(self):
        return self.home / ".claude" / "CLAUDE.md"

    @AUTHOR_SIDE
    def test_our_block_is_replaced_in_place_and_a_foreign_one_is_left_alone(self):
        """The file is outside the base, so a second block can never be cleaned up by an update.

        A re-install has to find the block it wrote last time and replace it where it stands. If it
        appends instead, the canon is in there twice and nothing afterwards can tell which copy is
        live, in the one file every session reads. And the file is shared: another harness keeps its
        own block in it, which is not ours to touch.
        """
        entry = self._global_entry()
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text(
            "# my own notes\n\n"
            "<!-- BEGIN MINDER-HARNESS -->\nwired by an earlier run\n<!-- END MINDER-HARNESS -->\n\n"
            "<!-- BEGIN HARNESS-PERSONAL -->\nsomebody else's harness\n<!-- END HARNESS-PERSONAL -->\n",
            encoding="utf-8")
        done = self.install()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        wiring = entry.read_text(encoding="utf-8")

        self.assertEqual(wiring.count("BEGIN MINDER-HARNESS"), 1, "the canon is in there twice")
        self.assertNotIn("wired by an earlier run", wiring, "the stale block was left in place")
        self.assertIn("BEGIN HARNESS-PERSONAL", wiring,
                      "another harness's block was destroyed — this file is not ours alone")
        self.assertIn("somebody else's harness", wiring)
        self.assertIn("# my own notes", wiring, "the person's own text was lost")

    @AUTHOR_SIDE
    def test_a_malformed_or_nested_block_is_refused_and_the_file_is_left_alone(self):
        """Every shape that is not exactly one well-formed block, refused without writing.

        A first-BEGIN-to-first-END cut is the tempting implementation and it is the dangerous one:
        it takes whatever sits between those two points, including another harness's block that
        somebody's hand-editing left nested inside ours. This file is outside every repository, so
        there is no update that can give that back.
        """
        entry = self._global_entry()
        entry.parent.mkdir(parents=True, exist_ok=True)
        shapes = {
            "a foreign block nested inside ours":
                "<!-- BEGIN MINDER-HARNESS -->\nours\n"
                "<!-- BEGIN MINDER-MEMORY -->\nsomebody else's\n<!-- END MINDER-MEMORY -->\n"
                "<!-- END MINDER-HARNESS -->\n",
            "an opening with no close":
                "<!-- BEGIN MINDER-HARNESS -->\nnever closed\n",
            "the same marker twice":
                "<!-- BEGIN MINDER-HARNESS -->\na\n<!-- END MINDER-HARNESS -->\n"
                "<!-- BEGIN MINDER-HARNESS -->\nb\n<!-- END MINDER-HARNESS -->\n",
            "a close before its open":
                "<!-- END MINDER-HARNESS -->\ninverted\n<!-- BEGIN MINDER-HARNESS -->\n",
        }
        for what, body in shapes.items():
            with self.subTest(what):
                entry.write_text(body, encoding="utf-8")
                done = self.install()
                self.assertNotEqual(done.returncode, 0, "%s: it wrote instead of refusing" % what)
                self.assertIn("STOP", done.stdout + done.stderr, what)
                self.assertEqual(entry.read_text(encoding="utf-8"), body,
                                 "%s: the file was modified by a run that refused" % what)

    @AUTHOR_SIDE
    def test_the_family_commands_are_placed_where_they_work_from_any_folder(self):
        """A command inside the base is only found when the session is already open there.

        These three answer for everything under the Minder name, so a folder is not the answer —
        and the record of what was placed is what lets a later run refresh its own copy without
        touching anybody else's file.
        """
        done = self.install()
        self.assertEqual(done.returncode, 0, done.stdout[-2000:] + done.stderr[-2000:])
        base = self.home / "mybase"
        shared = self.home / ".claude" / "commands" / "minder"
        for verb in ("update", "sync", "doctor"):
            link = shared / ("%s.md" % verb)
            self.assertTrue(link.exists(), "/minder:%s is not reachable from another folder" % verb)
            self.assertEqual(link.resolve(),
                             (base / ".claude" / "commands" / "minder" / ("%s.md" % verb)).resolve(),
                             "/minder:%s does not point at this base" % verb)
        owned = (shared / ".minder-harness-owned").read_text(encoding="utf-8").split()
        self.assertEqual(sorted(owned), ["doctor.md", "sync.md", "update.md"],
                         "the installer did not record what it placed")
        self.assertIn("work from any folder", done.stdout)

    @AUTHOR_SIDE
    def test_the_shared_directory_is_never_taken_over(self):
        """`~/.claude/commands/minder/` belongs to the NAME, not to this engine.

        A sibling product keeps its own subdirectory in there, and a person may have written a
        command of their own. Replacing what we did not place, or the directory itself, is how the
        second install silently wins.
        """
        shared = self.home / ".claude" / "commands" / "minder"
        (shared / "mem").mkdir(parents=True)
        (shared / "mem" / "recap.md").write_text("a sibling's own\n", encoding="utf-8")
        theirs = shared / "update.md"
        theirs.write_text("somebody else's command\n", encoding="utf-8")

        done = self.install()
        self.assertEqual(done.returncode, 0, done.stdout[-2000:] + done.stderr[-2000:])
        self.assertEqual(theirs.read_text(encoding="utf-8"), "somebody else's command\n",
                         "a file the installer never placed was overwritten")
        self.assertTrue((shared / "mem" / "recap.md").exists(),
                        "the sibling's own subdirectory did not survive")
        self.assertIn("left alone", done.stdout)
        self.assertIn("2 of 3", done.stdout,
                      "a partial placement was reported as though all three had landed")

    def test_a_fresh_install_leaves_a_base_that_can_travel(self):
        done = self.install()
        self.assertEqual(done.returncode, 0, done.stdout[-2000:] + done.stderr[-2000:])
        base = self.home / "mybase"

        self.assertTrue((base / "projects" / "_index.md").exists(),
                        "what the person builds must live inside the base")
        self.assertTrue((base / "tools" / "sync.py").exists())
        self.assertTrue((base / ".claude" / "settings.json").exists())

        self.assertEqual(git(base, "symbolic-ref", "--short", "HEAD").stdout.strip(), "main",
                         "a base on another branch pushes to a second branch, and the phone "
                         "clones the default one and finds nothing")
        self.assertEqual(len(git(base, "log", "--oneline").stdout.strip().splitlines()), 1,
                         "the base starts with a history, not a pile of staged files")
        self.assertEqual(git(base, "status", "--porcelain").stdout.strip(), "")
        self.assertIn("minder-harness", git(base, "remote").stdout,
                      "without the engine remote the base can never receive a fix")

        profile = (base / "profile.md").read_text(encoding="utf-8")
        self.assertIn("**Language:** Русский", profile)

        wiring = (self.home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("BEGIN MINDER-HARNESS", wiring)
        self.assertIn("@%s/AGENTS.md" % base, wiring,
                      "the global entry points at the one contract, not at a copied rule list")

    def test_running_it_twice_does_not_stack_a_second_wiring_block(self):
        self.install()
        self.install()
        wiring = (self.home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertEqual(wiring.count("BEGIN MINDER-HARNESS"), 1)


class MigrationTests(TempCase):
    """The channel for a change replacement cannot express: a path in the person's space moving."""

    BASE_MANIFEST = MANIFEST

    def setUp(self):
        super().setUp()
        self.root = self.tmpdir

    def declare(self, *lines):
        body = "migrations:\n" + "".join("  - %s\n" % line for line in lines) if lines else "migrations: []\n"
        write(self.root, ".engine-manifest.yml", self.BASE_MANIFEST + "\n" + body)

    def test_a_declared_move_is_carried_out(self):
        self.declare("move pointers -> knowledge/pointers")
        write(self.root, "pointers/stack.md", "theirs\n")
        carried = migrate_lib.run(self.root)
        self.assertEqual(len(carried), 1)
        self.assertFalse((self.root / "pointers").exists())
        self.assertEqual((self.root / "knowledge/pointers/stack.md").read_text(), "theirs\n")

    def test_running_it_again_does_nothing(self):
        # Convergence is the whole design: every update re-runs every declaration, so a base at
        # any version — including one dark for a year — lands in the same place.
        self.declare("move pointers -> knowledge/pointers")
        write(self.root, "pointers/stack.md", "theirs\n")
        migrate_lib.run(self.root)
        self.assertEqual(migrate_lib.run(self.root), [])

    def test_a_base_that_never_had_the_old_path_is_untouched(self):
        self.declare("move pointers -> knowledge/pointers")
        self.assertEqual(migrate_lib.run(self.root), [])
        self.assertFalse((self.root / "knowledge/pointers").exists())

    def test_it_refuses_to_overwrite_what_the_person_already_has(self):
        self.declare("move pointers -> knowledge/pointers")
        write(self.root, "pointers/stack.md", "old\n")
        write(self.root, "knowledge/pointers/stack.md", "newer, theirs\n")
        with self.assertRaises(migrate_lib.MigrationRefused):
            migrate_lib.run(self.root)
        self.assertEqual((self.root / "knowledge/pointers/stack.md").read_text(), "newer, theirs\n")
        self.assertTrue((self.root / "pointers/stack.md").exists())

    def test_it_refuses_to_reach_into_the_engines_own_space(self):
        # Replacement and retirement already own that; a move there is an authoring mistake and
        # would fight the checkout that runs beside it.
        self.declare("move rules -> knowledge/rules")
        write(self.root, "rules/canon.md", "engine\n")
        with self.assertRaises(migrate_lib.MigrationRefused):
            migrate_lib.run(self.root)
        self.assertTrue((self.root / "rules/canon.md").exists())

    def test_a_verb_from_a_newer_engine_stops_the_run(self):
        # Silently skipping it would leave the engine believing a change landed that never did.
        self.declare("reshape knowledge/_index.md")
        with self.assertRaises(migrate_lib.MigrationRefused) as refusal:
            migrate_lib.run(self.root)
        self.assertIn("once more", str(refusal.exception))

    def test_a_note_rides_with_the_move(self):
        self.declare("move pointers -> knowledge/pointers | your own notes may name the old place")
        write(self.root, "pointers/stack.md", "theirs\n")
        carried = migrate_lib.run(self.root)
        self.assertIn("may name the old place", carried[0].note)

    def test_dry_run_moves_nothing(self):
        self.declare("move pointers -> knowledge/pointers")
        write(self.root, "pointers/stack.md", "theirs\n")
        self.assertEqual(len(migrate_lib.run(self.root, dry_run=True)), 1)
        self.assertTrue((self.root / "pointers/stack.md").exists())


class ReleaseGateTests(TempCase):
    """The authoring gates, on a repository shaped like the engine."""

    def setUp(self):
        super().setUp()
        self.root = self.tmpdir
        self.found = enginechecks.Report()

    def test_an_edited_seed_that_already_shipped_fails_the_release(self):
        write(self.root, "VERSION", "1.0.0\n")
        write(self.root, "seed.md", "as released\n")
        init_repo(self.root)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "release")
        write(self.root, "seed.md", "edited after the release\n")
        enginechecks.check_seeds_unchanged(self.root, ["seed.md"], "main", self.found)
        self.assertEqual(len(self.found), 1)
        self.assertIn("seed", self.found)

    #: An engine listing one file on its own, the shape a directory sweep cannot reach.
    SINGLE = "version: 1.0.0\n\nengine:\n  - rules/\n  - %s\n\ntemplate:\n\nexclude:\n\nretired:\n%s"

    def _release_then(self, shipped_file, now_manifest, extra=""):
        """A repository that shipped `shipped_file` as an individual engine path, then changed."""
        write(self.root, "VERSION", "1.0.0\n")
        write(self.root, ".engine-manifest.yml", self.SINGLE % (shipped_file, ""))
        write(self.root, "rules/canon.md", "canon\n")
        write(self.root, shipped_file, "the catalogue\n")
        init_repo(self.root)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "release")
        (self.root / shipped_file).unlink()
        write(self.root, ".engine-manifest.yml", now_manifest)
        if extra:
            write(self.root, extra, "the catalogue, renamed\n")

    def test_a_single_engine_path_removed_without_a_retired_line_fails_the_release(self):
        """The half the directory sweep cannot see.

        An engine path listed on its own vanishes from the manifest together with the file, so
        iterating what the manifest holds NOW never looks at it — and `git checkout <ref> -- <path>`
        never removes what the ref lacks. Both files then sit on every base, forever.
        """
        self._release_then("tools/_engine.md",
                           self.SINGLE % ("tools/_renamed.md", ""),
                           extra="tools/_renamed.md")
        enginechecks.check_removals_retired(
            self.root, ["rules/", "tools/_renamed.md"], [], "main", self.found)
        self.assertEqual([f.where for f in self.found], ["tools/_engine.md"],
                         "a renamed single-path engine file passed the removal gate")

    def test_the_same_removal_declared_in_retired_passes(self):
        """The gate asks for a declaration, not for the file to stay."""
        self._release_then("tools/_engine.md",
                           self.SINGLE % ("tools/_renamed.md", "  - tools/_engine.md\n"),
                           extra="tools/_renamed.md")
        enginechecks.check_removals_retired(
            self.root, ["rules/", "tools/_renamed.md"], ["tools/_engine.md"], "main", self.found)
        self.assertEqual(len(self.found), 0,
                         "a declared removal was reported anyway: %s" % list(self.found))

    def test_a_single_path_that_moved_under_a_watched_directory_is_not_a_finding(self):
        """It did not vanish — the directory sweep answers for it now, and would report it."""
        self._release_then("rules/extra.md", self.SINGLE % ("tools/_engine.md", ""))
        write(self.root, "tools/_engine.md", "back\n")
        enginechecks.check_removals_retired(
            self.root, ["rules/", "tools/_engine.md"], [], "main", self.found)
        self.assertEqual([f.where for f in self.found], ["rules/extra.md"],
                         "the directory sweep should own this one, and report it")

    def test_a_seed_added_since_the_release_is_fine(self):
        write(self.root, "VERSION", "1.0.0\n")
        init_repo(self.root)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "release")
        write(self.root, "new-seed.md", "arrived after\n")
        enginechecks.check_seeds_unchanged(self.root, ["new-seed.md"], "main", self.found)
        self.assertEqual(len(self.found), 0, "seeding delivers a seed that is merely new")

    def test_nothing_is_frozen_before_the_first_release(self):
        write(self.root, "seed.md", "as committed\n")  # no VERSION at the ref
        init_repo(self.root)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "unreleased")
        write(self.root, "seed.md", "still being written\n")
        enginechecks.check_seeds_unchanged(self.root, ["seed.md"], "main", self.found)
        self.assertEqual(len(self.found), 0)

    def test_the_engines_own_notes_in_the_persons_space_fail_the_release(self):
        # There is no extraction step: a clone carries the whole repository, so anything the engine's
        # author left under activities/ or knowledge/ lands in every base as though it were theirs.
        write(self.root, "activities/_index.md", "the seed\n")
        write(self.root, "activities/my-work-log.md", "the author's own notes\n")
        init_repo(self.root)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "engine")
        enginechecks.check_person_space_ships_pristine(
            self.root, ["activities/_index.md"], ["activities/"], self.found)
        self.assertEqual(len(self.found), 1)
        self.assertIn("my-work-log.md", self.found)

    def _released(self):
        """A release on `main` and the work on a branch — the shape a release is measured in.

        Commits made straight onto `main` leave `main..HEAD` empty, and a check over an empty
        range passes without looking at anything.
        """
        write(self.root, "VERSION", "1.0.0\n")
        init_repo(self.root)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "release 1.0.0")
        git(self.root, "switch", "-q", "-c", "work")

    def test_a_commit_authored_by_an_assistant_fails_the_release(self):
        """The rule existed and nothing held it, so only somebody reading git log stood in the way.

        Authorship is the canonical attribution field of a public repository, and after a merge
        it can be removed only by rewriting history — which needs the person's approval in the
        moment and is refused on a shared branch. Cheap while it is still a branch.
        """
        self._released()
        write(self.root, "later.md", "work\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "ordinary work",
            "--author=Claude <noreply@anthropic.com>")
        enginechecks.check_no_assistant_authorship(self.root, "main", self.found)
        self.assertIn("assistant address", self.found)

    def test_a_commit_committed_by_an_assistant_fails_the_release(self):
        # Author and committer are separate fields and either one carries the mark into the log.
        self._released()
        write(self.root, "later.md", "work\n")
        git(self.root, "add", "-A")
        subprocess.run(["git", "-C", str(self.root),
                        "-c", "user.name=Claude", "-c", "user.email=noreply@anthropic.com",
                        "commit", "-qm", "ordinary work"], check=True)
        enginechecks.check_no_assistant_authorship(self.root, "main", self.found)
        self.assertIn("assistant address", self.found)

    def test_an_assistant_mark_in_a_commit_message_fails_the_release(self):
        self._released()
        for mark in ("Co-Authored-By: Claude <noreply@anthropic.com>",
                     "Generated with [Claude Code]"):
            write(self.root, "later.md", mark)
            git(self.root, "add", "-A")
            git(self.root, "commit", "-qm", "ordinary work\n\n%s" % mark)
        enginechecks.check_no_assistant_authorship(self.root, "main", self.found)
        self.assertIn("in its message", self.found)
        self.assertEqual(len(self.found), 2, list(self.found))

    def test_ordinary_history_raises_no_authorship_alarm(self):
        # The direction a false positive would ruin: a gate that fires on every release teaches
        # its reader to skip the one line that matters.
        self._released()
        write(self.root, "later.md", "work\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "ordinary work")
        enginechecks.check_no_assistant_authorship(self.root, "main", self.found)
        self.assertEqual(len(self.found), 0, list(self.found))

    def test_a_release_that_does_not_move_version_fails(self):
        """The last check body nothing covered, and its failure is invisible by construction.

        `update.py --check` compares the engine's VERSION against the base's. A release that
        changes engine paths without moving it reads as "already current" on every base — nobody
        is ever told a new version exists, and no error is produced anywhere to notice.
        """
        write(self.root, "VERSION", "1.0.0\n")
        write(self.root, "rules/canon.md", "as released\n")
        write(self.root, "CHANGELOG.md", "as released\n")
        init_repo(self.root)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "release 1.0.0")
        write(self.root, "rules/canon.md", "changed, and VERSION did not move\n")
        enginechecks.check_version_moved(self.root, ["rules/"], "main", self.found)
        self.assertIn("VERSION", self.found)
        self.assertIn("still 1.0.0", self.found)

    def test_a_release_that_moves_version_but_not_the_changelog_fails(self):
        # The update tells each person what arrived by reading CHANGELOG.md. A version that
        # moved with nothing written down announces a change nobody can look up.
        write(self.root, "VERSION", "1.0.0\n")
        write(self.root, "rules/canon.md", "as released\n")
        write(self.root, "CHANGELOG.md", "as released\n")
        init_repo(self.root)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "release 1.0.0")
        write(self.root, "rules/canon.md", "changed\n")
        write(self.root, "VERSION", "1.1.0\n")
        enginechecks.check_version_moved(self.root, ["rules/"], "main", self.found)
        self.assertIn("CHANGELOG.md", self.found)

    def test_a_person_owned_file_shipping_with_content_fails_the_release(self):
        """A file under `exclude:` may ship, but only as an empty shape.

        A clone carries the whole repository, so a line the engine's author leaves in one of the
        person's own files arrives in every base as though they wrote it. Directory entries are
        walked with git; a single file needs asking directly, or it is watched by nothing.
        """
        write(self.root, "notes.jsonl", '{"the author": "left this"}\n')
        init_repo(self.root)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "engine")
        enginechecks.check_person_space_ships_pristine(self.root, [], ["notes.jsonl"], self.found)
        self.assertIn("notes.jsonl", self.found)

    def test_an_empty_person_owned_file_is_the_shape_and_ships(self):
        write(self.root, "notes.jsonl", "")
        init_repo(self.root)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "engine")
        enginechecks.check_person_space_ships_pristine(self.root, [], ["notes.jsonl"], self.found)
        self.assertEqual(len(self.found), 0, list(self.found))

    def test_the_seed_itself_is_allowed_to_ship(self):
        write(self.root, "activities/_index.md", "the seed\n")
        init_repo(self.root)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "engine")
        enginechecks.check_person_space_ships_pristine(
            self.root, ["activities/_index.md"], ["activities/"], self.found)
        self.assertEqual(len(self.found), 0)


class ReleaseGateWiringTests(TempCase):
    """The gate as an author actually runs it — a check that exists but is not wired runs never."""

    GATE_MANIFEST = """version: 1.0.0

engine_remote: https://example.invalid/engine

engine:
  - rules/
  - VERSION
  - AGENTS.md
  - CLAUDE.md
  - .engine-manifest.yml
  - .claude-plugin/
  - tools/check_engine.py
  - tools/update.py
  - tools/lib/

template:
  - seed.md

exclude: []

migrations: []

retired: []
"""

    def setUp(self):
        super().setUp()
        self.root = self.tmpdir
        write(self.root, ".engine-manifest.yml", self.GATE_MANIFEST)
        write(self.root, "VERSION", "1.0.0\n")
        write(self.root, ".claude-plugin/plugin.json", '{"version": "1.0.0"}\n')
        write(self.root, "rules/canon.md", "the rule\n")
        write(self.root, "AGENTS.md", "canon:\n@rules/canon.md\n")
        write(self.root, "CLAUDE.md", "@AGENTS.md\n")
        write(self.root, "seed.md", "as released\n")
        install_tools(self.root)
        init_repo(self.root)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "release 1.0.0")

    def gate(self, *args):
        return run_tool(self.root, "check_engine.py", *args, cwd=self.root)

    def test_a_coherent_engine_passes(self):
        done = self.gate("--authoring")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_editing_a_seed_that_already_shipped_fails_the_release(self):
        write(self.root, "seed.md", "edited after the release\n")
        done = self.gate("--authoring")
        self.assertEqual(done.returncode, 1)
        # Not the bare word "seed": the fixture's file IS `seed.md`, so half the gate's other
        # failures name it too and would satisfy a substring check identically.
        self.assertIn("already exists on every base, and it was edited", done.stderr)

    def test_a_rule_whose_name_hides_inside_another_is_still_caught(self):
        # The regression: `safety.md` is a substring of `git-safety.md`, so searching AGENTS.md for
        # the bare filename reported the rule as listed when nothing listed it. The gate said the
        # engine was ready to ship and the rule reached no runtime at all.
        write(self.root, "rules/git-canon.md", "the long one\n")
        write(self.root, "rules/canon.md", "the short one whose name hides in the long one\n")
        write(self.root, "AGENTS.md", "canon:\n@rules/git-canon.md\n")
        git(self.root, "add", "-A")
        done = self.gate()
        self.assertEqual(done.returncode, 1)
        self.assertIn("canon.md", done.stderr)

    def test_a_new_tool_declared_nowhere_fails_the_release(self):
        write(self.root, "tools/orphan.py", "print('reaches nobody')\n")
        git(self.root, "add", "-A")
        done = self.gate("--authoring")
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("orphan.py", done.stderr)

    def test_a_removal_with_no_retired_line_fails_the_release(self):
        # git ADDS and UPDATES on checkout and never deletes, so without the line the file lives
        # on every base forever, offering a contract nothing honours.
        released = git(self.root, "rev-parse", "HEAD").stdout.strip()
        (self.root / "rules" / "canon.md").unlink()
        write(self.root, "rules/other.md", "still here\n")
        write(self.root, "AGENTS.md", "canon:\n@rules/other.md\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "drop a rule without retiring it")
        done = self.gate("--authoring", "--since", released)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("canon.md", done.stderr)

    def test_changing_a_engine_path_without_moving_version_fails_the_release(self):
        released = git(self.root, "rev-parse", "HEAD").stdout.strip()
        write(self.root, "rules/canon.md", "the rule, revised\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "revise the rule")
        done = self.gate("--authoring", "--since", released)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("VERSION", done.stderr)

    def test_a_dead_section_pointer_fails_the_gate_as_an_author_runs_it(self):
        """Wired, not merely present. A check nobody calls runs never.

        Calling the function directly proves it works; only running the gate the way an author
        does proves it is reached — and detaching a check is invisible either way otherwise.
        """
        write(self.root, "rules/canon.md", "# The Rule\n\n## A Real Section\n\nbody\n")
        write(self.root, "AGENTS.md",
              'canon:\n@rules/canon.md\n\nSee `rules/canon.md` -> "A Section That Moved".\n')
        git(self.root, "add", "-A")
        done = self.gate()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("cites a section", done.stderr)

    def test_the_engines_own_notes_in_the_persons_space_fail_the_release(self):
        write(self.root, ".engine-manifest.yml",
              self.GATE_MANIFEST.replace("exclude: []", "exclude:\n  - notes/"))
        write(self.root, "notes/my-work-log.md", "the author's own notes\n")
        git(self.root, "add", "-A")
        done = self.gate("--authoring")
        self.assertEqual(done.returncode, 1)
        self.assertIn("my-work-log.md", done.stderr)

    def test_a_migration_into_the_engines_own_space_fails_the_release(self):
        write(self.root, ".engine-manifest.yml",
              self.GATE_MANIFEST.replace("migrations: []",
                                         "migrations:\n  - move rules -> elsewhere"))
        done = self.gate("--authoring")
        self.assertEqual(done.returncode, 1)
        self.assertIn("engine's own space", done.stderr)

    def test_every_check_that_exists_is_actually_wired(self):
        """A check nobody calls is a check that runs never, and it fails silently forever.

        The orchestration is one list in `enginechecks.run`, so a check can be written, tested
        directly, and left unconnected — every test of its BODY still passes. That is precisely
        the shape that ships green and protects nothing.
        """
        import ast
        import inspect
        called = {node.func.id for node in ast.walk(ast.parse(inspect.getsource(enginechecks.run)))
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        defined = [name for name in dir(enginechecks) if name.startswith("check_")]
        self.assertGreater(len(defined), 10, "the checks moved and this test found none")
        for name in defined:
            # Asked of the syntax tree, not of the text: a call commented out is not a call, and
            # a substring search cannot tell the difference.
            self.assertIn(name, called, "%s is never called — it runs on no base" % name)
        self.assertIn("scan", str(inspect.getsource(enginechecks.run)),
                      "the portability scan is what /minder:doctor gets on a person's base")

    def test_a_declared_path_that_is_not_there_fails_the_structural_half(self):
        write(self.root, ".engine-manifest.yml",
              self.GATE_MANIFEST.replace("  - VERSION\n", "  - VERSION\n  - never-written.md\n"))
        done = self.gate()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("never-written.md", done.stderr)

    def test_a_path_listed_twice_fails_the_structural_half(self):
        write(self.root, ".engine-manifest.yml",
              self.GATE_MANIFEST.replace("  - VERSION\n", "  - VERSION\n  - VERSION\n"))
        done = self.gate()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("twice", done.stderr)

    def test_a_retired_path_that_still_ships_fails_the_structural_half(self):
        write(self.root, "leftover.md", "still here\n")
        write(self.root, ".engine-manifest.yml",
              self.GATE_MANIFEST.replace("retired: []", "retired:\n  - leftover.md"))
        done = self.gate()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("leftover.md", done.stderr)

    def test_a_version_mirror_that_disagrees_fails_the_structural_half(self):
        write(self.root, ".claude-plugin/plugin.json", '{"version": "9.9.9"}\n')
        done = self.gate()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("VERSION", done.stderr)

    def test_the_portability_scan_runs_on_any_base_not_only_a_release(self):
        """The documented promise: `/minder:doctor` runs this gate and gets the scan with it.

        The scan is one call inside the structural half. Losing it leaves every other check
        passing, the summary line unchanged, and an engine shipping files that only work on the
        machine they were written on.
        """
        write(self.root, "rules/helper.py", 'NOTES = "/Users/someone/notes"\n')
        done = self.gate()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("CP-1", done.stderr)
        self.assertIn("rules/helper.py", done.stderr)

    def test_the_structural_half_stays_quiet_about_a_persons_own_files(self):
        # A person's base runs this half through /minder:doctor, where their own knowledge and
        # activities are exactly what is supposed to be there.
        write(self.root, ".engine-manifest.yml",
              self.GATE_MANIFEST.replace("exclude: []", "exclude:\n  - notes/"))
        write(self.root, "notes/their-thinking.md", "theirs\n")
        git(self.root, "add", "-A")
        done = self.gate()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


class PortabilityGateTests(TempCase):
    """Every clause must fire on real code and stay silent on prose. A gate that cannot fail is
    indistinguishable from a codebase that is clean."""

    def setUp(self):
        super().setUp()
        self.root = self.tmpdir

    def findings(self, relpath, body, binary=False):
        target = self.root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        if binary:
            target.write_bytes(body)
        else:
            target.write_text(body, encoding="utf-8")
        return portability.scan_file(self.root, relpath)

    def clauses(self, relpath, body, binary=False):
        return sorted({f.rule.clause for f in self.findings(relpath, body, binary)})

    # -- CP-2: bash 4 and GNU/BSD splits -------------------------------------
    def test_bash_four_builtins_are_caught(self):
        for line in ("mapfile -t x < f", "readarray -t x < f", "declare -A m",
                     'echo "${name^^}"', 'echo "${name,,}"'):
            self.assertIn("CP-2", self.clauses("a.sh", line + "\n"), line)

    def test_commands_whose_flags_differ_by_platform_are_caught(self):
        for line in ("readlink -f x", "sed -i s/a/b/ f", "stat -c %s f", "stat -f %z f",
                     "grep -P foo f"):
            self.assertIn("CP-2", self.clauses("a.sh", line + "\n"), line)

    def test_a_portable_equivalent_is_not_a_finding(self):
        clean = 'while IFS= read -r line; do :; done < f\ntr "a-z" "A-Z" < f\ngrep -E foo f\n'
        self.assertEqual(self.clauses("a.sh", clean), [])

    # -- CP-1: a path that exists on one machine ------------------------------
    def test_a_hardcoded_home_path_is_caught_in_shell_and_python(self):
        self.assertIn("CP-1", self.clauses("a.sh", 'cd /Users/someone/base\n'))
        self.assertIn("CP-1", self.clauses("a.py", 'p = "/home/someone/base"\n'))

    # -- CP-5: text decoded through whatever the platform defaults to ---------
    def test_python_text_io_without_an_encoding_is_caught(self):
        for line in ('t = p.read_text()', 't = path.read_text(errors="replace")',
                     'f = open(path)', 'f = open(path, "w")'):
            self.assertIn("CP-5", self.clauses("a.py", line + "\n"), line)

    def test_declared_encoding_and_binary_mode_are_not_findings(self):
        clean = ('t = p.read_text(encoding="utf-8")\n'
                 'f = open(path, "w", encoding="utf-8")\n'
                 'b = open(path, "rb")\n')
        self.assertEqual(self.clauses("a.py", clean), [])

    def test_powershell_reading_without_an_encoding_is_caught(self):
        self.assertIn("CP-5", self.clauses("a.ps1", '$t = Get-Content -Raw -LiteralPath $p\n'))
        self.assertEqual(self.clauses("a.ps1", '$t = Get-Content -Raw -Encoding UTF8 -LiteralPath $p\n'), [])

    def test_a_ps1_with_non_ascii_and_no_bom_is_caught(self):
        self.assertIn("CP-5", self.clauses("a.ps1", "Write-Host 'тире —'\n".encode("utf-8"), binary=True))
        with_bom = b"\xef\xbb\xbf" + "Write-Host 'тире —'\n".encode("utf-8")
        self.assertEqual(self.clauses("a.ps1", with_bom, binary=True), [])

    # -- CP-6: a native command under a stop-on-error shell -------------------
    def test_a_bare_native_call_in_powershell_is_caught(self):
        self.assertIn("CP-6", self.clauses("a.ps1", '$u = (git -C $Dest remote get-url origin)\n'))

    def test_the_helper_and_an_existence_check_are_not_findings(self):
        clean = ('$u = (Git-Q -C $Dest remote get-url origin)\n'
                 'Invoke-Native gh auth status\n'
                 '$has = [bool](Get-Command git -ErrorAction SilentlyContinue)\n')
        self.assertEqual(self.clauses("a.ps1", clean), [])

    # -- CP-3: line endings ---------------------------------------------------
    def test_crlf_is_caught_in_any_shipped_text(self):
        self.assertIn("CP-3", self.clauses("a.sh", b"echo hi\r\n", binary=True))

    # -- prose is never code --------------------------------------------------
    def test_a_comment_describing_a_banned_construct_is_not_a_finding(self):
        self.assertEqual(self.clauses("a.sh", "# never use mapfile or readlink -f here\n"), [])
        self.assertEqual(self.clauses("a.py", "# open(path) without an encoding is wrong\n"), [])

    def test_a_docstring_describing_a_banned_construct_is_not_a_finding(self):
        body = '"""Why open(path) is wrong.\n\nAlso never mapfile.\n"""\nx = 1\n'
        self.assertEqual(self.clauses("a.py", body), [])

    def test_a_hash_inside_a_string_is_not_a_comment(self):
        # Blanking from the first `#` regardless of quotes would hide the rest of the line.
        self.assertIn("CP-2", self.clauses("a.sh", 'echo "a # b"; mapfile -t x < f\n'))

    def test_markdown_prose_is_never_matched_but_a_tagged_fence_is(self):
        prose = "Never use `mapfile` — it is bash 4.\n"
        self.assertEqual(self.clauses("a.md", prose), [])
        fenced = "Example:\n\n```bash\nmapfile -t x < f\n```\n"
        self.assertIn("CP-2", self.clauses("a.md", fenced))
        untagged = "Example:\n\n```\nmapfile -t x < f\n```\n"
        self.assertEqual(self.clauses("a.md", untagged), [])

    # -- the escape -----------------------------------------------------------
    def test_an_inline_escape_with_a_reason_suppresses_the_finding(self):
        self.assertEqual(self.clauses("a.sh", "mapfile -t x < f  # portability-ok: linux-only probe\n"), [])
        above = "# portability-ok: linux-only probe\nmapfile -t x < f\n"
        self.assertEqual(self.clauses("a.sh", above), [])

    def test_an_escape_without_a_reason_does_not_suppress(self):
        self.assertIn("CP-2", self.clauses("a.sh", "mapfile -t x < f  # portability-ok:\n"))

    # -- scope ----------------------------------------------------------------
    def test_the_fixtures_are_not_scanned(self):
        self.assertEqual(self.clauses("tools/tests/fixture.sh", "mapfile -t x < f\n"), [])

    def test_tier_one_is_everything_the_manifest_ships(self):
        shipped = set(portability.shipped_paths(ENGINE_ROOT))
        self.assertIn("rules/cross-platform.md", shipped)
        self.assertIn("install.ps1", shipped)
        # Every template is tier 1, INCLUDING one seeded inside a directory listed under
        # exclude:. update.py seeds them all regardless of exclude, so calling them the person's
        # space here would let one manifest mean two different things and ship them unchecked.
        for entry in manifest_lib.read_section("template", ENGINE_ROOT):
            self.assertIn(entry, shipped, "a seeded template is not tier 1: %s" % entry)
        # The person's own space, minus those seeds, stays out.
        seeds = set(manifest_lib.read_section("template", ENGINE_ROOT))
        for entry in manifest_lib.read_section("exclude", ENGINE_ROOT):
            stray = [p for p in shipped if manifest_lib.covers([entry], p) and p not in seeds]
            self.assertEqual(stray, [], "the person's space is tier 2: %s" % entry)

    def test_a_build_artifact_inside_a_shipped_directory_is_not_shipped(self):
        # shipped_paths globs the filesystem, so a __pycache__ or a stray .venv would otherwise
        # be counted as engine content and could fail somebody's gate on a file no update carries.
        self.assertEqual([p for p in portability.shipped_paths(ENGINE_ROOT)
                          if "__pycache__" in p or ".venv" in p], [])

    def test_whole_file_rules_run_on_every_shipped_path_whatever_its_suffix(self):
        # .gitattributes is the file that ENFORCES LF and had no LF check of its own.
        self.assertIn("CP-3", self.clauses(".gitattributes", b"*.sh text\r\n", binary=True))
        self.assertIn("CP-3", self.clauses("tools/x.js", b"const a = 1;\r\n", binary=True))

    def test_shipped_javascript_is_checked_for_a_path_from_one_machine(self):
        self.assertIn("CP-1", self.clauses("tools/x.mjs", 'const base = "/home/someone/base";\n'))

    # -- what a regex could not see ------------------------------------------
    def test_a_call_that_nests_or_spans_lines_is_still_seen(self):
        for body in ('f = open(os.path.join(root, name))\n',
                     'f = open(\n    path,\n    "w",\n)\n',
                     't = p.write_text(json.dumps(d))\n'):
            self.assertIn("CP-5", self.clauses("a.py", body), body)

    def test_a_clustered_or_long_form_flag_is_still_the_same_flag(self):
        for line in ("sed -E -i '' f", "sed -ie s/a/b/ f", "grep -Pq foo f", "readlink -fn x",
                     "declare -Ax m", "sed --in-place s/a/b/ f", "grep --perl-regexp x f",
                     "stat --format=%s f"):
            self.assertIn("CP-2", self.clauses("a.sh", line + "\n"), line)

    def test_a_native_call_reached_through_a_variable_or_splat_is_still_native(self):
        for line in ("git $Arguments", "git @gitArgs", "git.exe status"):
            self.assertIn("CP-6", self.clauses("a.ps1", line + "\n"), line)

    def test_a_helper_named_in_a_message_does_not_disarm_the_line_beside_it(self):
        body = 'Write-Host "see Get-Command docs"; git push\n'
        self.assertIn("CP-6", self.clauses("a.ps1", body))

    def test_a_powershell_message_naming_a_command_is_not_a_call(self):
        self.assertEqual(self.clauses("a.ps1", 'Write-Host "then run git push yourself"\n'), [])

    def test_a_hardcoded_windows_path_is_caught_and_a_regex_escape_is_not(self):
        self.assertIn("CP-1", self.clauses("a.ps1", '$d = "C:\\Users\\someone\\base"\n'))
        self.assertEqual(self.clauses("a.ps1", "$rx = [regex]'(?m)^- Language:.*$'\n"), [])
        self.assertEqual(self.clauses("a.sh", "printf 'imports it:\\n'\n"), [])

    def test_a_continued_line_is_read_as_one_command(self):
        self.assertEqual(self.clauses("a.ps1", '$t = Get-Content `\n  -Raw -Encoding UTF8 $p\n'), [])

    def test_a_one_line_docstring_and_a_help_constant_are_prose(self):
        for body in ('"""Why open(path) is wrong."""\nx = 1\n',
                     'HELP = """usage:\n  tool --root /home/someone/base\n  open(path)\n"""\n',
                     'r"""Matches /home/someone style paths."""\nx = 1\n'):
            self.assertEqual(self.clauses("a.py", body), [], body)

    def test_the_escape_has_to_be_a_comment(self):
        # An escape a string literal can trigger is the opposite of loud: it never reads as an
        # exemption to anyone reviewing the line.
        body = 'echo "portability-ok: data" ; mapfile -t x < f\n'
        self.assertIn("CP-2", self.clauses("a.sh", body))

    def test_a_wider_fence_and_a_nested_one_are_documents_not_code(self):
        wrapped = "````markdown\n```bash\nmapfile -t x < f\n```\n````\n"
        self.assertEqual(self.clauses("a.md", wrapped), [])
        quoted = "```text\n```bash\nmapfile -t x < f\n```\n"
        self.assertEqual(self.clauses("a.md", quoted), [])

    # -- the binding between a clause and what enforces it --------------------
    def test_a_gate_rule_citing_an_undefined_clause_fails_the_engine(self):
        """The direction the release gate had no test for.

        A rule table can invent an id, and the failure it prints then points at a contract nobody
        wrote — the person reading it has a regex and nothing to look up.
        """
        rules = portability.LINE_RULES
        invented = portability.Rule("CP-99", "shell", r"\bnothing\b", "invented", "nothing")
        portability.LINE_RULES = rules + (invented,)
        self.addCleanup(setattr, portability, "LINE_RULES", rules)
        self.assertIn("CP-99", portability.clauses())
        found = enginechecks.Report()
        enginechecks.check_clause_ids(ENGINE_ROOT, found)
        self.assertIn("CP-99", found)

    def test_a_clause_nothing_enforces_fails_the_engine(self):
        """Enforcement drifting out from under a written clause is the silent half.

        The rule still reads as guarded, the release still passes, and the only evidence is a
        check that no longer exists.
        """
        rules = portability.LINE_RULES
        portability.LINE_RULES = tuple(r for r in rules if r.clause != "CP-6")
        self.addCleanup(setattr, portability, "LINE_RULES", rules)
        found = enginechecks.Report()
        enginechecks.check_clause_ids(ENGINE_ROOT, found)
        self.assertIn("CP-6", found)

    def test_a_clause_the_tests_carry_instead_of_the_scanner_is_still_enforced(self):
        # Two mechanisms can hold a clause. [CP-4] — installer twins in lockstep — is not
        # expressible as a pattern over one file, so the test suite carries it, and the gate has
        # to count that as enforcement rather than demand a scanner rule for everything.
        self.assertNotIn("CP-4", portability.clauses())
        found = enginechecks.Report()
        enginechecks.check_clause_ids(ENGINE_ROOT, found)
        self.assertEqual(len(found), 0)

    # -- release gates a content scanner cannot express ----------------------
    def test_retiring_a_file_from_inside_a_shipped_directory_is_allowed(self):
        """The case the section exists for, which the gate made impossible to satisfy.

        Without a `retired:` line it failed for the removal; with one it failed for coverage —
        from the same manifest state, so retiring anything out of `rules/` or `doctrine/` could
        not be shipped. The fear does not hold: `git checkout <ref> -- <dir>` writes what the ref
        has and never recreates a file the ref lacks.
        """
        found = enginechecks.Report()
        enginechecks.check_retired(ENGINE_ROOT, ["doctrine/"], [], ["knowledge/"],
                                ["doctrine/gone.md"], found)
        self.assertEqual(len(found), 0,
                         "retiring from inside a shipped directory must be expressible")

    def test_a_path_that_is_both_shipped_on_its_own_and_retired_fails(self):
        found = enginechecks.Report()
        enginechecks.check_retired(ENGINE_ROOT, ["doctrine/gone.md"], [], [],
                                ["doctrine/gone.md"], found)
        self.assertIn("listed on its own", found)

    def test_a_second_canon_list_is_caught_wherever_it_sits(self):
        """A second list is a second truth wherever it lives, so every shipped page is watched.

        `CLAUDE.md` is the likely place and not the only possible one: a list copied into a
        README or a doctrine page drifts exactly the same way, and the person goes on believing
        a rule applies.
        """
        for where in ("README.md", "doctrine/engine-ownership.md", "CLAUDE.md"):
            fake = Path(self.tmp.name) / where.replace("/", "_")
            shutil.copytree(ENGINE_ROOT, fake, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            target = fake / where
            target.write_text(target.read_text(encoding="utf-8")
                              + "\n@rules/safety.md\n@rules/grounding.md\n@rules/communication.md\n",
                              encoding="utf-8")
            found = enginechecks.Report()
            enginechecks.check_canon_listed_once(fake, found)
            self.assertIn("restates the canon list", found,
                          "a second list in %s was not caught: %s" % (where, found))

    def test_a_malformed_canon_entry_does_not_read_as_a_listed_rule(self):
        """A typo in the list is the shape that passes while the rule reaches nobody.

        The check searched for `@rules/safety.md` anywhere in the contract, so any line
        CONTAINING it satisfied the search — `@rules/safety.md-old`, a trailing word, a paste
        gone wrong. The rule is then in force for no runtime and the gate calls the engine ready
        to ship, which is the exact failure this check exists to prevent.
        """
        fake = Path(self.tmp.name) / "typo"
        shutil.copytree(ENGINE_ROOT, fake, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        contract = fake / "AGENTS.md"
        contract.write_text(
            contract.read_text(encoding="utf-8").replace("@rules/safety.md\n",
                                                         "@rules/safety.md-old\n"),
            encoding="utf-8")
        found = enginechecks.Report()
        enginechecks.check_canon_listed_once(fake, found)
        self.assertIn("rules/safety.md", found)

    def test_the_gate_agrees_with_the_updater_about_an_empty_engine_section(self):
        """Two tools, one manifest, opposite verdicts is worse than either being wrong alone.

        `update.py` learned that `engine: []` is a legitimate base and the gate did not, so the
        base `/minder:doctor` runs the gate on was told its manifest was unsafe while the
        updater exited 0 on the same file.
        """
        import re as _re
        for body, expect_failure in ((("engine: []\n\n"), False), ("", True)):
            fake = Path(self.tmp.name) / ("declared" if not expect_failure else "missing")
            shutil.copytree(ENGINE_ROOT, fake, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            manifest = fake / ".engine-manifest.yml"
            text = _re.sub(r"^engine:\n(  - .*\n|  #.*\n|\n)*", body,
                           manifest.read_text(encoding="utf-8"), count=1, flags=_re.M)
            manifest.write_text(text, encoding="utf-8")
            found, _ = enginechecks.run(fake)
            self.assertEqual("has no engine: section" in found, expect_failure,
                             "engine: %r declared=%s" % (body, not expect_failure))

    def test_the_manifests_own_version_is_a_third_mirror_and_is_held_to_it(self):
        # The doctrine, the doctor's list and the manifest's own header all promise this number
        # is held to the other two. The current version is asked of the manifest rather than
        # written here: a literal copy of a value the code owns turns every release into a
        # failing test (rules/self-learning.md — the snapshot filter).
        fake = Path(self.tmp.name) / "drifted"
        shutil.copytree(ENGINE_ROOT, fake, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        manifest = fake / ".engine-manifest.yml"
        declared = manifest_lib.read_version(fake)
        self.assertTrue(declared, "the manifest declares no version to drift from")
        manifest.write_text(manifest.read_text(encoding="utf-8")
                            .replace("version: %s" % declared, "version: 9.9.9", 1),
                            encoding="utf-8")
        found = enginechecks.Report()
        enginechecks.check_versions(fake, found)
        self.assertIn("says version '9.9.9'", found)

    def test_a_pointer_into_a_renamed_section_fails_the_engine(self):
        """The one defect `present-not-history` forbids that only eyes could catch.

        A citation from a remembered heading rots the first time a file is rewritten — and
        rewriting a rule whole is what that same rule requires — after which it points
        confidently at the wrong paragraph.
        """
        fake = Path(self.tmp.name) / "engine"
        shutil.copytree(ENGINE_ROOT, fake, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        target = fake / "rules/device-sync.md"
        target.write_text(
            target.read_text(encoding="utf-8").replace(
                "## Two questions decide your behaviour — not the name of the device",
                "## What decides your behaviour", 1), encoding="utf-8")
        found = enginechecks.Report()
        enginechecks.check_section_references(fake, found)
        self.assertIn("cites a section", found)

    def test_a_pointer_at_a_missing_file_fails_the_engine(self):
        fake = Path(self.tmp.name) / "kit2"
        shutil.copytree(ENGINE_ROOT, fake, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        (fake / "ARCHITECTURE.md").write_text(
            'See `rules/nonexistent.md` -> "Some Heading".\n', encoding="utf-8")
        found = enginechecks.Report()
        enginechecks.check_section_references(fake, found)
        self.assertIn("does not exist", found)

    @AUTHOR_SIDE
    def test_every_pointer_the_engine_ships_resolves_today(self):
        found = enginechecks.Report()
        enginechecks.check_section_references(ENGINE_ROOT, found)
        self.assertEqual(len(found), 0)

    def test_a_path_listed_twice_in_one_section_fails_the_release(self):
        # Silent otherwise: the path count the update reports goes up, the work does not, and an
        # author adding an entry that is already there reads the higher number as it landing.
        found = enginechecks.Report()
        enginechecks.check_no_double_listing(["rules/", "README.md", "README.md"], [],
                                          found)
        self.assertIn("twice under engine", found)
        clean = enginechecks.Report()
        enginechecks.check_no_double_listing(
            list(manifest_lib.read_section("engine", ENGINE_ROOT)),
            list(manifest_lib.read_section("template", ENGINE_ROOT)),
            clean)
        self.assertEqual(len(clean), 0)

    def test_a_path_in_both_engine_and_template_is_caught(self):
        """The arm nobody tested, and the one whose failure is silent on a person's disk.

        `engine:` is replaced wholesale and `template:` is never overwritten, so a path in both
        resolves to engine — and the file the person filled in is quietly replaced by the engine's
        blank one on their next update. `profile.md` is the obvious candidate.
        """
        found = enginechecks.Report()
        enginechecks.check_no_double_listing(["rules/", "profile.md"], ["profile.md"], found)
        self.assertIn("both engine: and template:", found)
        self.assertIn("profile.md", found)

    def test_a_fork_that_kept_the_upstream_address_fails_the_release(self):
        """Fork the engine, forget `engine_remote:`, and every base you set up goes upstream.

        Each update reconciles a base's engine remote to whatever the manifest declares — the same
        mechanism that makes moving the engine possible — so the omission is silent and permanent
        after one line of output nobody reads twice.
        """
        fork = Path(self.tmp.name) / "fork"
        shutil.copytree(ENGINE_ROOT, fork, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        init_repo(fork)
        subprocess.run(["git", "-C", str(fork), "remote", "add", "origin",
                        "https://github.com/someone/their-fork"], check=True)
        found = enginechecks.Report()
        enginechecks.check_engine_remote_is_this_repository(fork, found)
        self.assertIn("engine_remote:", found)

        # And the matching case passes. It is asked of a fixture rather than of ENGINE_ROOT: this
        # suite is an `engine:` path, so it runs on every base that installs the engine — and there
        # `origin` is the person's OWN private repository, exactly as the installer sets it up.
        # Asserting on the ambient origin made the check fire correctly and the assertion fail,
        # so `/minder:doctor` told every owner their base's tooling was broken.
        subprocess.run(["git", "-C", str(fork), "remote", "set-url", "origin",
                        manifest_lib.read_engine_remote(fork)], check=True)
        clean = enginechecks.Report()
        enginechecks.check_engine_remote_is_this_repository(fork, clean)
        self.assertEqual(len(clean), 0, list(clean))

    def test_a_shipped_tool_missing_from_the_catalogue_fails_the_release(self):
        found = enginechecks.Report()
        engine = list(manifest_lib.read_section("engine", ENGINE_ROOT)) + ["tools/nowhere.py"]
        enginechecks.check_engine_tools_are_catalogued(ENGINE_ROOT, engine, found)
        self.assertIn("nowhere.py", found)
        # And the engine as it stands catalogues everything it ships.
        clean = enginechecks.Report()
        enginechecks.check_engine_tools_are_catalogued(
            ENGINE_ROOT, list(manifest_lib.read_section("engine", ENGINE_ROOT)),
            clean)
        self.assertEqual(len(clean), 0)

    def test_a_shell_tool_with_no_twin_fails_the_release(self):
        """[CP-4] The fault a content scanner cannot see.

        Portable bash is still bash: PowerShell cannot run it, and reading the file will never
        say so — check_portability.py would report it clean.
        """
        found = enginechecks.Report()
        enginechecks.check_engine_tools_run_everywhere(
            ENGINE_ROOT, ["tools/helper.sh"], found)
        self.assertIn("helper.sh", found)
        paired = enginechecks.Report()
        enginechecks.check_engine_tools_run_everywhere(
            ENGINE_ROOT, ["tools/helper.sh", "tools/helper.ps1"], paired)
        self.assertEqual(len(paired), 0, list(paired))

    @AUTHOR_SIDE
    def test_the_engine_it_ships_today_is_clean(self):
        self.assertEqual([str(f) for f in portability.scan(ENGINE_ROOT)], [])


# PowerShell variables that exist without anyone assigning them: automatic variables, and the
# scope prefixes that look like one ($script:Root).
POWERSHELL_AUTOMATIC = frozenset({
    "true", "false", "null", "_", "psitem", "args", "input", "home", "pwd", "pid", "host",
    "error", "matches", "lastexitcode", "myinvocation", "psscriptroot", "pscommandpath",
    "psversiontable", "erroractionpreference", "outputencoding", "profile", "foreach",
    "executioncontext", "script", "global", "local",
})


class WindowsInstallerTests(unittest.TestCase):
    """Static checks on install.ps1 — no PowerShell here, so these guard what a read can prove.

    Each one stands for a failure that cannot be caught any other way in this environment, and
    each was a real defect before it was a test.
    """

    def setUp(self):
        self.path = ENGINE_ROOT / "install.ps1"
        self.raw = self.path.read_bytes()
        self.text = self.raw.decode("utf-8-sig")

    def test_it_carries_a_utf8_bom(self):
        # Windows PowerShell 5.1 decodes a BOM-less .ps1 through the system ANSI code page, so
        # the script's own em dashes become mojibake — including the one inside a negated
        # character class, which then stops excluding what it was written to exclude.
        self.assertTrue(self.raw.startswith(b"\xef\xbb\xbf"))

    def test_every_file_read_declares_utf8(self):
        # Without -Encoding, 5.1 reads through the ANSI code page and a read-modify-write cycle
        # permanently corrupts the person's profile.md.
        self.assertNotIn("Get-Content -Raw -LiteralPath", self.text)
        self.assertNotIn("Get-Content -Raw -Path", self.text)

    def test_no_native_command_runs_outside_the_helper(self):
        # git and gh write ordinary progress to stderr; under $ErrorActionPreference = 'Stop'
        # that aborts the installer on a perfectly healthy machine.
        offenders = [
            line.strip() for line in self.text.splitlines()
            if re.search(r"(^|[ (\t])(git|gh) ", line)
            and "Git-Q" not in line and "Invoke-Native" not in line
            and "Get-Command" not in line and not line.strip().startswith("#")
        ]
        self.assertEqual(offenders, [])

    def test_it_refuses_a_non_interactive_run_like_bash_does(self):
        # The gate has to be CALLED, not merely defined. Asserting the name appears is satisfied
        # by the function header alone — and a deleted call site is how this stopped working once.
        calls = [line.strip() for line in self.text.splitlines()
                 if line.strip() == "Require-Answers"]
        self.assertEqual(len(calls), 1, "install.ps1 defines Require-Answers but never calls it")
        # The full spelling in both twins. A shorter substring of it cannot fail — it is satisfied
        # by the very name it is meant to be distinguishing itself from — so it asserts nothing.
        self.assertIn("MINDER_HARNESS_ANSWERS_ON_STDIN", self.text,
                      "install.ps1 does not honour the documented variable")
        shell = engine_text("install.sh")
        self.assertIn("MINDER_HARNESS_ANSWERS_ON_STDIN", shell,
                      "install.sh does not honour the documented variable")
        self.assertTrue(re.search(r"^require_answers\s*$", shell, re.M),
                        "install.sh defines require_answers but never calls it")

    def test_every_variable_it_reads_is_one_it_set(self):
        """A deletion that overshoots is invisible until a stranger's machine runs the script.

        bash has `set -u` and stops on the spot; PowerShell substitutes $null and carries on, so
        an over-wide edit surfaces as `You cannot call a method on a null-valued expression`
        several steps later — on Windows, where nobody here can see it. This is that check.
        """
        code = "\n".join(line for line in self.text.splitlines()
                          if not line.strip().startswith("#"))
        bound = {m.lower() for m in re.findall(r"\$([A-Za-z_]\w*)\s*(?:=|\+=)", code)}
        bound |= {m.lower() for m in
                  re.findall(r"foreach\s*\(\s*\$([A-Za-z_]\w*)\s+in\b", code, re.I)}
        for params in re.findall(r"^\s*(?:function\s+[\w-]+\s*|param\s*)\(([^)]*)\)",
                                 code, re.M | re.I):
            bound |= {m.lower() for m in re.findall(r"\$([A-Za-z_]\w*)", params)}
        used = {m.lower() for m in re.findall(r"\$(?!env:)([A-Za-z_]\w*)", code)}
        self.assertEqual(sorted(used - bound - POWERSHELL_AUTOMATIC), [])

    def test_it_finds_the_engine_remote_the_way_the_manifest_declares_it(self):
        """[CP-4] the twins must agree on WHICH remote is the engine's, not just that one exists.

        Matching on the NAME calls a person's own base the engine whenever the two happen to share
        a name, and rewrites their `origin` — after which nothing can save their work anywhere.
        Asserted as the POSITIVE fact: a negative assertion on a spelling stops guarding anything
        the moment that spelling changes, and goes on passing.
        """
        self.assertTrue("engine_remote" in engine_text("install.sh"),
                        "install.sh no longer reads engine_remote from the manifest")
        self.assertTrue("engine_remote" in self.text,
                        "install.ps1 does not read engine_remote from the manifest")
        self.assertIn("Is-EngineUrl $EngineUrl", self.text,
                      "install.ps1 no longer decides by ADDRESS which remote is the engine's")
        self.assertIn('is_engine_url "$ENGINE_URL"', engine_text("install.sh"),
                      "install.sh no longer decides by ADDRESS which remote is the engine's")

    def test_line_endings_are_lf(self):
        # .gitattributes forces LF; a CRLF checkout of the bash twin breaks bash outright, and
        # the two files are meant to stay byte-comparable in this respect.
        self.assertNotIn(b"\r\n", self.raw)

    def test_both_installers_ask_the_same_questions(self):
        """[CP-4] a mechanism with a platform twin moves in lockstep."""
        shell = engine_text("install.sh")
        for question in ("Where should your base live?", "What should the base folder be called?",
                         "What language should the agent talk to you in?", "Do you use Claude Code?",
                         "Move it inside the base?", "Set that up now?", "Your name", "Your email"):
            self.assertIn(question, shell, "install.sh lost: %s" % question)
            self.assertIn(question, self.text, "install.ps1 lost: %s" % question)

    def test_every_runtime_the_installer_wires_is_also_verified(self):
        """Writing an entry and never checking it is how a runtime looks set up and is not.

        Claude Code's block was verified after install and Codex's was not, in both installers
        identically — so it was an oversight rather than a platform difference.
        """
        shell = engine_text("install.sh")
        for runtime, entry in (("Claude Code", ".claude/CLAUDE.md"), ("Codex", ".codex/AGENTS.md")):
            self.assertIn('check "%s global wiring"' % runtime, shell, runtime)
            self.assertIn(entry, shell, entry)
            self.assertIn('Check "%s global wiring"' % runtime, self.text, runtime)

    def test_the_hot_canon_names_no_capability_only_one_runtime_has(self):
        """A slash command in shared canon reads as available to a runtime that has no slashes."""
        for name in sorted((ENGINE_ROOT / "rules").glob("*.md")):
            body = name.read_text(encoding="utf-8")
            # A slash command, not a path that merely contains the same letters — the canon is
            # full of `rules/harness-stewardship.md`.
            invocation = re.compile(r"(?<![\w/.])/minder:[a-z][a-z:-]*")
            # By paragraph, not by line: a wrapped sentence is one statement, and splitting it
            # would fail on formatting rather than on meaning.
            for block in re.split(r"\n\s*\n", body):
                if not invocation.search(block) or block.lstrip().startswith(">"):
                    continue
                self.assertIn(".claude/commands/", block,
                              "%s offers a slash command without naming the file behind it: %s"
                              % (name.name, block.strip()[:100]))

    def test_both_doctors_check_the_same_things(self):
        shell = engine_text("install.sh")
        in_shell = set(re.findall(r'check "([^"]*)"', shell)) - {"label"}
        in_windows = set(re.findall(r'Check "([^"]*)"', self.text))
        # The one allowed asymmetry: bash hard-requires python3 at the top instead of checking.
        in_windows.discard("python3 available (needed to catch up automatically)")
        self.assertEqual(in_shell, in_windows)


@AUTHOR_SIDE
class ShippedEngineTests(unittest.TestCase):
    """The engine in this working tree is coherent — the same gate a release runs.

    Author-side by definition: every assertion here is about the CONTENT of the tree it runs in,
    and on a base that content is partly the person's. `check_engine.py` is what tells them about
    their own base, and it says "something to fix" rather than "your tooling is broken".
    """

    def test_structural_gate_passes(self):
        done = run_tool(ENGINE_ROOT, "check_engine.py", cwd=ENGINE_ROOT)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_every_rule_is_listed_once_in_the_one_contract(self):
        rules = sorted(p.name for p in (ENGINE_ROOT / "rules").glob("*.md"))
        contract = engine_text("AGENTS.md")
        bridge = engine_text("CLAUDE.md")
        for name in rules:
            self.assertIn(name, contract, "%s is silently not in force" % name)
            self.assertNotIn("@rules/%s" % name, bridge, "the canon list must exist once")

    def test_the_canon_list_tells_the_agent_to_repair_it(self):
        # The list is the one place the canon can be got wrong, and on a person's base nobody runs
        # the release gate. So the instruction itself has to close the hole: a rule on disk that
        # the list omits still binds, and the session that notices repairs it.
        contract = engine_text("AGENTS.md")
        self.assertIn("not named above is a rule the list has LOST", contract)
        # And that adopting one is a decision, not a step: a file that simply appeared in
        # `rules/` is a claim on every future session that nobody made.
        self.assertIn("Confirm before you adopt one", contract)
        self.assertIn("index", contract)

    def test_safety_and_git_safety_do_not_restate_each_other(self):
        # Two rules over one subject drift. git-safety owns git; safety owns everything else and
        # each names the other rather than repeating it.
        git_rule = engine_text("rules/git-safety.md")
        safety = engine_text("rules/safety.md")
        self.assertIn("rules/safety.md", git_rule)
        self.assertIn("rules/git-safety.md", safety)
        self.assertNotIn("--force", safety, "the force list has one home, and it is git-safety")

    def test_declared_paths_exist(self):
        for entry in manifest_lib.read_section("engine", ENGINE_ROOT):
            self.assertTrue((ENGINE_ROOT / entry.rstrip("/")).exists(), entry)
        for entry in manifest_lib.read_section("template", ENGINE_ROOT):
            self.assertTrue((ENGINE_ROOT / entry).exists(), entry)


if __name__ == "__main__":
    unittest.main()
