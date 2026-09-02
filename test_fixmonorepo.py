#!/usr/bin/env python3
"""
Tests for fixmonorepo.

    python3 -m unittest              # all of them
    python3 -m unittest -v           # ...with names
    python3 -m unittest test_fixmonorepo.TestRuin              # one class
    python3 -m unittest test_fixmonorepo.TestRuin.test_dry_run_touches_nothing

Every test drives the real command line against a real throwaway git
repository in a temp directory, and then looks at what ended up on disk. That
is the only honest way to test a program whose entire job is running git.

Reading one of these: `self.make_repo({...})` builds the source repository,
`self.fix(repo)` and `self.ruin()` run the commands, and the assertions look
at the files and the git history that came out.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fixmonorepo as fm

_SAVED_ENV: dict[str, str | None] = {}


def setUpModule():
    """Ignore the developer's own git config; it may sign commits or set hooks."""
    for key, value in {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    }.items():
        _SAVED_ENV[key] = os.environ.get(key)
        os.environ[key] = value


def tearDownModule():
    for key, value in _SAVED_ENV.items():
        if value is None:
            del os.environ[key]
        else:
            os.environ[key] = value


def git(*args: str, cwd: Path) -> str:
    """Run git in the test fixtures. Deliberately not fixmonorepo's own helper."""
    proc = subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(f"fixture git {args} failed: {proc.stderr.strip()}")
    return proc.stdout.rstrip("\n")


# ----------------------------------------------------------------------------
# the fixture every test is built on
# ----------------------------------------------------------------------------

class CLITest(unittest.TestCase):
    """A temp directory, a way to build source repos, and a way to run the CLI."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="fixmonorepo-test-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.out = self.tmp / "fixed"     # where `fix` writes
        self.dest = self.tmp / "ruined"   # where `ruin` writes

    # -- building source repositories ---------------------------------------

    def make_repo(self, files: dict[str, str | bytes] | None = None,
                  name: str = "src") -> Path:
        """A git repository containing `files`, committed as "first commit"."""
        repo = self.tmp / name
        repo.mkdir(parents=True)
        git("init", "-q", cwd=repo)
        git("symbolic-ref", "HEAD", "refs/heads/main", cwd=repo)
        git("config", "user.name", "Ada Lovelace", cwd=repo)
        git("config", "user.email", "ada@example.com", cwd=repo)
        git("config", "commit.gpgsign", "false", cwd=repo)
        if files:
            self.commit(repo, files, "first commit")
        return repo

    def commit(self, repo: Path, files: dict[str, str | bytes], message: str):
        """Write `files` into `repo` and commit them."""
        for rel, content in files.items():
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode() if isinstance(content, str) else content)
        git("add", "-A", cwd=repo)
        git("commit", "-qm", message, cwd=repo)

    # -- running the command line -------------------------------------------

    def cli(self, *argv) -> tuple[int, str, str]:
        """Run the CLI in-process. Returns (exit code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        argv = ["fixmonorepo", *(str(a) for a in argv)]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with mock.patch.object(sys, "argv", argv):
                code = fm.main()
        return code, out.getvalue(), err.getvalue()

    def fix(self, repo: Path, *flags) -> dict:
        """`fix repo -o self.out`, assert it worked, and return the manifest."""
        code, _, err = self.cli("fix", repo, "-o", self.out, *flags)
        self.assertEqual(code, 0, f"fix failed: {err}")
        return json.loads((self.out / "manifest.json").read_text())

    def ruin(self, *flags, source=None) -> tuple[int, str, str]:
        """`ruin self.out -o self.dest`. Returns (exit code, stdout, stderr)."""
        return self.cli("ruin", source or self.out, "-o", self.dest, *flags)

    # -- looking at the results ---------------------------------------------

    def atom_repo(self, name: str) -> Path:
        """One of the generated one-file repositories."""
        return self.out / "repos" / name

    def assertSameFiles(self, produced: Path, original: Path, paths: list[str]):
        for rel in paths:
            self.assertEqual((produced / rel).read_bytes(),
                             (original / rel).read_bytes(), f"{rel} differs")


# ----------------------------------------------------------------------------
# fix: one repository in, one repository per file out
# ----------------------------------------------------------------------------

class TestFix(CLITest):
    def test_one_repository_per_tracked_file(self):
        repo = self.make_repo({"a.txt": "a\n", "src/b.py": "b\n"})

        manifest = self.fix(repo)

        self.assertEqual(manifest["repo_count"], 2)
        self.assertEqual(sorted(a["name"] for a in manifest["atoms"]),
                         ["a-txt", "src-b-py"])
        self.assertEqual(sorted(p.name for p in (self.out / "repos").iterdir()),
                         ["a-txt", "src-b-py"])

    def test_each_atom_is_a_repository_on_the_requested_branch(self):
        repo = self.make_repo({"a.txt": "a\n"})

        self.fix(repo, "--branch", "trunk")

        atom = self.atom_repo("a-txt")
        self.assertTrue((atom / ".git").is_dir())
        self.assertEqual(git("rev-parse", "--abbrev-ref", "HEAD", cwd=atom), "trunk")

    def test_the_file_sits_at_the_root_of_its_repository(self):
        repo = self.make_repo({"src/deep/b.py": "b\n"})

        self.fix(repo)

        self.assertEqual((self.atom_repo("src-deep-b-py") / "b.py").read_text(), "b\n")

    def test_the_manifest_remembers_where_the_file_came_from(self):
        repo = self.make_repo({"src/deep/b.py": "b\n"})

        atom = self.fix(repo)["atoms"][0]

        self.assertEqual(atom["path"], "src/deep/b.py")
        self.assertEqual(atom["file"], "b.py")
        self.assertEqual(atom["clone_url"], "repos/src-deep-b-py")

    def test_the_output_directory_is_self_contained(self):
        repo = self.make_repo({"a.txt": "a\n"})

        self.fix(repo)

        for name in ["manifest.json", "README.md", "ARCHITECTURE.md",
                     "ruin.sh", fm.SELF]:
            self.assertTrue((self.out / name).exists(), f"missing {name}")
        self.assertTrue(os.access(self.out / "ruin.sh", os.X_OK))
        self.assertTrue(os.access(self.out / fm.SELF, os.X_OK))

    def test_names_that_would_collide_are_numbered(self):
        repo = self.make_repo({"a-b.txt": "1\n", "a/b.txt": "2\n", "a.b.txt": "3\n"})

        names = [a["name"] for a in self.fix(repo)["atoms"]]

        self.assertEqual(sorted(names), ["a-b-txt", "a-b-txt-2", "a-b-txt-3"])

    def test_prefix_is_applied_to_every_name(self):
        repo = self.make_repo({"a.txt": "a\n"})

        manifest = self.fix(repo, "--prefix", "pkg-")

        self.assertEqual(manifest["atoms"][0]["name"], "pkg-a-txt")

    def test_exclude_skips_matching_files(self):
        repo = self.make_repo({"a.txt": "a\n", "keep.py": "k\n", "b.txt": "b\n"})

        manifest = self.fix(repo, "--exclude", "*.txt")

        self.assertEqual([a["path"] for a in manifest["atoms"]], ["keep.py"])

    def test_exclude_can_be_repeated(self):
        repo = self.make_repo({"a.txt": "a\n", "keep.py": "k\n", "b.md": "b\n"})

        manifest = self.fix(repo, "--exclude", "*.txt", "--exclude", "*.md")

        self.assertEqual([a["path"] for a in manifest["atoms"]], ["keep.py"])

    def test_remote_template_becomes_the_clone_url(self):
        repo = self.make_repo({"a.txt": "a\n"})

        manifest = self.fix(repo, "--remote-template", "git@host:org/{name}.git")

        self.assertEqual(manifest["atoms"][0]["clone_url"], "git@host:org/a-txt.git")

    def test_binary_files_survive_byte_for_byte(self):
        blob = bytes(range(256))
        repo = self.make_repo({"blob.bin": blob})

        self.fix(repo)

        self.assertEqual((self.atom_repo("blob-bin") / "blob.bin").read_bytes(), blob)

    def test_the_executable_bit_is_carried_over(self):
        repo = self.make_repo({"run.sh": "#!/bin/sh\n"})
        os.chmod(repo / "run.sh", 0o755)
        git("update-index", "--chmod=+x", "run.sh", cwd=repo)
        git("commit", "-qm", "chmod", cwd=repo)

        atom = self.fix(repo)["atoms"][0]

        self.assertEqual(atom["mode"], "100755")
        self.assertTrue(os.access(self.atom_repo("run-sh") / "run.sh", os.X_OK))
        self.assertIn("100755", git("ls-files", "-s", cwd=self.atom_repo("run-sh")))


class TestFixHistory(CLITest):
    def test_every_revision_of_the_file_is_replayed(self):
        repo = self.make_repo({"a.txt": "v1\n"})
        self.commit(repo, {"a.txt": "v2\n"}, "second")
        self.commit(repo, {"a.txt": "v3\n"}, "third")

        manifest = self.fix(repo)

        self.assertEqual(manifest["atoms"][0]["commits"], 3)
        self.assertEqual(
            git("log", "--format=%s", cwd=self.atom_repo("a-txt")).splitlines(),
            ["chore(governance): add mandatory paperwork",
             "third", "second", "first commit"])

    def test_commits_that_touched_other_files_are_not_replayed(self):
        repo = self.make_repo({"a.txt": "a\n", "b.txt": "b\n"})
        self.commit(repo, {"b.txt": "b2\n"}, "only b")
        self.commit(repo, {"b.txt": "b3\n"}, "only b again")

        atoms = {a["name"]: a for a in self.fix(repo)["atoms"]}

        self.assertEqual(atoms["a-txt"]["commits"], 1)
        self.assertEqual(atoms["b-txt"]["commits"], 3)

    def test_a_commit_that_did_not_change_the_content_is_dropped(self):
        # A mode-only change shows up in `git log -- path` but stages nothing.
        repo = self.make_repo({"a.txt": "a\n"})
        git("update-index", "--chmod=+x", "a.txt", cwd=repo)
        git("commit", "-qm", "chmod only", cwd=repo)

        manifest = self.fix(repo)

        self.assertEqual(manifest["atoms"][0]["commits"], 1)

    def test_the_original_author_and_date_are_preserved(self):
        repo = self.make_repo()
        (repo / "a.txt").write_text("a\n")
        git("add", "a.txt", cwd=repo)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "by grace"],
                       check=True, env={**os.environ,
                                        "GIT_AUTHOR_NAME": "Grace Hopper",
                                        "GIT_AUTHOR_EMAIL": "grace@example.com",
                                        "GIT_AUTHOR_DATE": "2001-02-03T04:05:06+00:00"})

        self.fix(repo)

        # --skip=1 skips the paperwork commit sitting on top.
        self.assertEqual(
            git("log", "--format=%an|%ae|%aI", "--skip=1", "-1",
                cwd=self.atom_repo("a-txt")),
            "Grace Hopper|grace@example.com|2001-02-03T04:05:06+00:00")

    def test_each_replayed_commit_records_where_it_came_from(self):
        repo = self.make_repo({"src/a.txt": "a\n"})
        original = git("rev-parse", "HEAD", cwd=repo)

        self.fix(repo)

        body = git("log", "--format=%B", "--skip=1", "-1",
                   cwd=self.atom_repo("src-a-txt"))
        self.assertIn("Liberated-From: src/a.txt", body)
        self.assertIn(f"Original-Commit: {original}", body)

    def test_no_history_writes_a_single_import_commit(self):
        repo = self.make_repo({"a.txt": "v1\n"})
        self.commit(repo, {"a.txt": "v2\n"}, "second")

        manifest = self.fix(repo, "--no-history")

        self.assertEqual(manifest["atoms"][0]["commits"], 1)
        self.assertEqual(
            git("log", "--format=%s", cwd=self.atom_repo("a-txt")).splitlines(),
            ["chore(governance): add mandatory paperwork",
             "feat: initial import of a.txt"])
        self.assertEqual((self.atom_repo("a-txt") / "a.txt").read_text(), "v2\n")

    def test_follow_keeps_the_history_after_a_rename(self):
        # Known limitation: revisions from before the rename cannot be read at
        # the new path, so they are skipped. Only later history is replayed.
        repo = self.make_repo({"old.txt": "v1\n"})
        git("mv", "old.txt", "new.txt", cwd=repo)
        git("commit", "-qm", "rename", cwd=repo)

        manifest = self.fix(repo, "--follow")

        self.assertEqual(manifest["atoms"][0]["commits"], 1)
        self.assertEqual((self.atom_repo("new-txt") / "new.txt").read_text(), "v1\n")


class TestFixCeremony(CLITest):
    def test_the_paperwork_is_committed_and_tagged(self):
        repo = self.make_repo({"a.txt": "a\n"})

        self.fix(repo)

        atom = self.atom_repo("a-txt")
        for name in ["README.md", "CHANGELOG.md", "CODE_OF_CONDUCT.md", "atom.json"]:
            self.assertTrue((atom / name).exists(), f"missing {name}")
        self.assertEqual(git("tag", cwd=atom), "v1.0.0")
        self.assertEqual(git("log", "-1", "--format=%s", cwd=atom),
                         "chore(governance): add mandatory paperwork")

    def test_atom_json_describes_the_one_file(self):
        repo = self.make_repo({"src/a.txt": "a\n", "b.txt": "b\n"})

        self.fix(repo)

        meta = json.loads((self.atom_repo("src-a-txt") / "atom.json").read_text())
        self.assertEqual(meta["files"], ["a.txt"])
        self.assertEqual(meta["originalPath"], "src/a.txt")
        self.assertEqual(meta["peerRepositories"], 1)

    def test_a_real_readme_wins_and_the_paperwork_moves_aside(self):
        repo = self.make_repo({"README.md": "the real one\n"})

        self.fix(repo)

        atom = self.atom_repo("readme-md")
        self.assertEqual((atom / "README.md").read_text(), "the real one\n")
        self.assertTrue((atom / "README.governance.md").exists())

    def test_no_ceremony_leaves_only_the_file(self):
        repo = self.make_repo({"a.txt": "a\n"})

        self.fix(repo, "--no-ceremony")

        atom = self.atom_repo("a-txt")
        self.assertEqual([p.name for p in atom.iterdir() if p.name != ".git"],
                         ["a.txt"])
        self.assertEqual(git("tag", cwd=atom), "")


class TestFixReport(CLITest):
    def test_the_summary_separates_code_from_paperwork(self):
        repo = self.make_repo({"a.txt": "12345\n"})

        _, out, _ = self.cli("fix", repo, "-o", self.out)

        self.assertIn("repositories created ....... 1", out)
        self.assertIn("actual source code ......... 6 bytes", out)
        # README, CHANGELOG, CODE_OF_CONDUCT, atom.json
        self.assertIn("files that are not code .... 4", out)

    def test_without_ceremony_there_is_no_paperwork_to_report(self):
        repo = self.make_repo({"a.txt": "12345\n"})

        _, out, _ = self.cli("fix", repo, "-o", self.out, "--no-ceremony")

        self.assertIn("governance paperwork ....... 0 bytes", out)
        self.assertIn("files that are not code .... 0", out)


class TestFixErrors(CLITest):
    def test_a_directory_that_is_not_a_repository(self):
        plain = self.tmp / "plain"
        plain.mkdir()

        code, _, err = self.cli("fix", plain, "-o", self.out)

        self.assertEqual(code, 1)
        self.assertIn("not a git repository", err)

    def test_a_repository_with_no_tracked_files(self):
        code, _, err = self.cli("fix", self.make_repo(), "-o", self.out)

        self.assertEqual(code, 1)
        self.assertIn("Nothing to liberate", err)

    def test_excluding_everything_leaves_nothing_to_liberate(self):
        repo = self.make_repo({"a.txt": "a\n"})

        code, _, err = self.cli("fix", repo, "-o", self.out, "--exclude", "*")

        self.assertEqual(code, 1)
        self.assertIn("Nothing to liberate", err)

    def test_a_non_empty_output_directory_is_refused(self):
        repo = self.make_repo({"a.txt": "a\n"})
        self.out.mkdir()
        (self.out / "precious.txt").write_text("do not delete me\n")

        code, _, err = self.cli("fix", repo, "-o", self.out)

        self.assertEqual(code, 1)
        self.assertIn("use --force", err)
        self.assertTrue((self.out / "precious.txt").exists())

    def test_an_empty_output_directory_is_fine(self):
        repo = self.make_repo({"a.txt": "a\n"})
        self.out.mkdir()

        code, _, _ = self.cli("fix", repo, "-o", self.out)

        self.assertEqual(code, 0)

    def test_force_replaces_the_output_directory(self):
        repo = self.make_repo({"a.txt": "a\n"})
        self.out.mkdir()
        (self.out / "stale.txt").write_text("old\n")

        code, _, _ = self.cli("fix", repo, "-o", self.out, "--force")

        self.assertEqual(code, 0)
        self.assertFalse((self.out / "stale.txt").exists())
        self.assertTrue((self.out / "manifest.json").exists())

    def test_force_refuses_to_delete_the_script_it_is_running_from(self):
        # Run a *copy* of the tool as a subprocess: if this guard ever breaks,
        # the --force below deletes the directory it is pointed at, and that
        # must never be the real checkout.
        repo = self.make_repo({"a.txt": "a\n"})
        tool_dir = self.tmp / "tool"
        tool_dir.mkdir()
        tool = tool_dir / fm.SELF
        tool.write_bytes(Path(fm.__file__).read_bytes())

        proc = subprocess.run(
            [sys.executable, str(tool), "fix", str(repo), "-o", str(tool_dir),
             "--force"],
            capture_output=True, text=True)

        self.assertEqual(proc.returncode, 1)
        self.assertIn("contains this script", proc.stderr)
        self.assertTrue(tool.exists(), "the guard let the script delete itself")


# ----------------------------------------------------------------------------
# ruin: many repositories in, one working tree out
# ----------------------------------------------------------------------------

class TestRuin(CLITest):
    FILES = {"a.txt": "a\n", "src/b.py": "b\n", "src/deep/c.md": "c\n"}

    def setUp(self):
        super().setUp()
        self.repo = self.make_repo(dict(self.FILES))
        self.fix(self.repo)

    def test_every_file_returns_to_its_original_path(self):
        code, out, _ = self.ruin()

        self.assertEqual(code, 0)
        self.assertIn("Reassembled 3/3", out)
        self.assertSameFiles(self.dest, self.repo, list(self.FILES))

    def test_it_accepts_the_manifest_file_as_well_as_the_directory(self):
        code, _, _ = self.ruin(source=self.out / "manifest.json")

        self.assertEqual(code, 0)
        self.assertSameFiles(self.dest, self.repo, list(self.FILES))

    def test_the_reassembled_tree_is_a_repository_again(self):
        self.ruin()

        self.assertTrue((self.dest / ".git").exists())
        self.assertIn("consolidate 1 repository from 3 repositories",
                      git("log", "-1", "--format=%s", cwd=self.dest))

    def test_no_git_leaves_a_plain_directory(self):
        self.ruin("--no-git")

        self.assertFalse((self.dest / ".git").exists())
        self.assertTrue((self.dest / "a.txt").exists())

    def test_dry_run_touches_nothing(self):
        code, out, _ = self.ruin("--dry-run")

        self.assertEqual(code, 0)
        self.assertIn("Dry run: 3 repositories would be cloned", out)
        self.assertFalse((self.dest / "a.txt").exists())

    def test_the_executable_bit_comes_back(self):
        repo = self.make_repo({"run.sh": "#!/bin/sh\n"}, name="exec-src")
        os.chmod(repo / "run.sh", 0o755)
        git("update-index", "--chmod=+x", "run.sh", cwd=repo)
        git("commit", "-qm", "chmod", cwd=repo)
        self.out = self.tmp / "fixed2"
        self.fix(repo)

        self.ruin("--no-git")

        self.assertTrue(os.access(self.dest / "run.sh", os.X_OK))

    def test_a_missing_manifest_is_reported(self):
        code, _, err = self.ruin(source=self.tmp / "nowhere")

        self.assertEqual(code, 1)
        self.assertIn("no manifest", err)

    def test_one_unreachable_repository_fails_but_the_rest_arrive(self):
        self.break_clone_url("a-txt")

        code, out, _ = self.ruin()

        self.assertEqual(code, 1)
        self.assertIn("Failed: a-txt", out)
        self.assertIn("partially real", out)
        self.assertFalse((self.dest / "a.txt").exists())
        self.assertSameFiles(self.dest, self.repo, ["src/b.py"])

    def test_when_nothing_can_be_cloned_it_says_so(self):
        for name in ["a-txt", "src-b-py", "src-deep-c-md"]:
            self.break_clone_url(name)

        code, out, _ = self.ruin()

        self.assertEqual(code, 1)
        self.assertIn("Nothing was restored", out)

    def test_remote_template_overrides_the_manifest_urls(self):
        self.break_clone_url("a-txt")

        # Point the template at the same repositories by another route.
        code, _, _ = self.ruin("--remote-template",
                               str(self.out / "repos" / "{name}"))

        self.assertEqual(code, 0)
        self.assertSameFiles(self.dest, self.repo, list(self.FILES))

    def test_a_manifest_with_unexpected_fields_still_works(self):
        # Someone hand-edits manifest.json, or a newer fixmonorepo adds a field.
        # Unknown keys are ignored and missing optional ones fall back.
        path = self.out / "manifest.json"
        manifest = json.loads(path.read_text())
        for atom in manifest["atoms"]:
            atom.pop("branch")           # optional: defaults to main
            atom.pop("commits")          # optional: only used for reporting
            atom["invented_later"] = {"by": "a future version"}
        path.write_text(json.dumps(manifest, indent=2))

        code, _, err = self.ruin()

        self.assertEqual(code, 0, err)
        self.assertSameFiles(self.dest, self.repo, list(self.FILES))

    def break_clone_url(self, name: str):
        """Point one atom at a repository that is not there."""
        path = self.out / "manifest.json"
        manifest = json.loads(path.read_text())
        for atom in manifest["atoms"]:
            if atom["name"] == name:
                atom["clone_url"] = "repos/does-not-exist"
        path.write_text(json.dumps(manifest, indent=2))


class TestRoundTrip(CLITest):
    def test_fix_then_ruin_reproduces_the_working_tree(self):
        repo = self.make_repo({
            "a.txt": "a\n",
            "src/main.py": "print('hi')\n",
            "src/util/main.py": "helper\n",   # same basename, different repo
            "docs/guide.md": "# guide\n",
            "blob.bin": bytes(range(256)),
        })
        self.commit(repo, {"src/main.py": "print('bye')\n"}, "change main")

        self.fix(repo)
        code, _, _ = self.ruin("--no-git")

        self.assertEqual(code, 0)
        tracked = git("ls-files", cwd=repo).splitlines()
        self.assertEqual(len(tracked), 5)
        self.assertSameFiles(self.dest, repo, tracked)

    def test_the_generated_ruin_script_works(self):
        repo = self.make_repo({"a.txt": "a\n"})
        self.fix(repo)

        proc = subprocess.run(["bash", str(self.out / "ruin.sh"), str(self.dest)],
                              capture_output=True, text=True)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual((self.dest / "a.txt").read_text(), "a\n")


class TestCLI(CLITest):
    def test_a_subcommand_is_required(self):
        with self.assertRaises(SystemExit) as caught:
            self.cli()
        self.assertNotEqual(caught.exception.code, 0)

    def test_an_unknown_subcommand_is_refused(self):
        with self.assertRaises(SystemExit) as caught:
            self.cli("liberate")
        self.assertNotEqual(caught.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
