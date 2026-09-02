#!/usr/bin/env python3
"""
fixmonorepo - if separate repositories are more organized, be more organized.

Some people split a codebase across repositories because it feels tidier.
Two repositories are more organized than one. Five are more organized than
two. Follow that all the way down and the tidiest a codebase can possibly be
is one repository per file.

fixmonorepo takes that argument seriously. It takes one git repository and
liberates every single file into its own independent, autonomous,
individually-versioned repository, complete with mandatory governance
paperwork. Then puts it all back, slowly.

    fixmonorepo.py fix   <repo>    -o <outdir>    # repair the monorepo
    fixmonorepo.py ruin  <outdir>  -o <workdir>   # regress to a monorepo

Requires: git, python3. No dependencies, unlike your 47 repositories.

How it works
------------
`fix` walks the tracked files of the source repo and turns each one into an
Atom: a directory under `repos/` that is a real git repository containing
that file, its replayed history, and its paperwork. The list of Atoms is
written to `manifest.json`, which is the only record of how the files fit
together. `ruin` reads that manifest, clones every Atom back, and copies each
file to the path it came from.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_VERSION = 1
SELF = os.path.basename(__file__)
BOT = ("fixmonorepo", "fixmonorepo@localhost")  # who signs the paperwork
REC = "\x1e"  # record separator, for parsing `git log`
FLD = "\x1f"  # field separator, ditto


# ----------------------------------------------------------------------------
# running git
# ----------------------------------------------------------------------------

def _run(args, cwd=None, stdin: str | None = None, env: dict | None = None):
    cmd = ["git"] + (["-C", str(cwd)] if cwd is not None else []) + list(args)
    return subprocess.run(
        cmd,
        input=(stdin.encode() if stdin is not None else None),
        capture_output=True,
        env={**os.environ, **(env or {})},
    )


def git(*args: str, cwd=None, binary: bool = False, stdin: str | None = None,
        check: bool = True, env: dict | None = None):
    """Run git for its output: str, or bytes if binary=True."""
    proc = _run(args, cwd, stdin, env)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({proc.returncode}): "
            f"{proc.stderr.decode(errors='replace').strip()}"
        )
    if binary:
        return proc.stdout
    return proc.stdout.decode(errors="replace").rstrip("\n")


def git_ok(*args: str, cwd=None) -> bool:
    """Run git for its answer: did it exit 0?"""
    return _run(args, cwd).returncode == 0


def is_git_repo(path: Path) -> bool:
    return git("rev-parse", "--is-inside-work-tree", cwd=path, check=False) == "true"


def nothing_staged(repo: Path) -> bool:
    return git_ok("diff", "--cached", "--quiet", cwd=repo)


# ----------------------------------------------------------------------------
# naming the repositories
# ----------------------------------------------------------------------------

def slugify(path: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", path).strip("-").lower()
    return re.sub(r"-{2,}", "-", s) or "unnamed"


def unique_name(name: str, taken: set[str]) -> str:
    """Return `name`, or `name-2`, `name-3`... and record it in `taken`."""
    candidate = name
    n = 1
    while candidate in taken:
        n += 1
        candidate = f"{name}-{n}"
    taken.add(candidate)
    return candidate


# ----------------------------------------------------------------------------
# mandatory governance paperwork
# ----------------------------------------------------------------------------

def ceremony_files(name: str, path: str, filename: str, total: int) -> dict[str, str]:
    badges = " ".join([
        "![build](https://img.shields.io/badge/build-passing-brightgreen)",
        "![coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)",
        "![files](https://img.shields.io/badge/files-1-blue)",
        f"![repos](https://img.shields.io/badge/sibling%20repos-{total - 1}-orange)",
    ])
    return {
        "README.md": f"""# {name}

{badges}

The canonical home of **`{filename}`**.

`{filename}` used to be one line in a directory listing, sharing a repository
with {total - 1} unrelated files. It now has its own repository, its own
history, its own releases, its own issue tracker, and its own README, which
is this one. Everything that could be separated has been separated.

## Organization

| | before | after |
|---|---|---|
| repositories | 1 | {total} |
| files in this repository | {total} | 1 |
| places to look for `{filename}` | 1 | 1 |
| places to look for anything else | 1 | {total - 1} |

The right-hand column is more organized than the left-hand column, because
the number of repositories in it is larger. That is the metric that was
optimized. The other rows were not consulted.

## Scope

This repository contains `{filename}`. It does not contain anything else.
Requests to add a second file will be closed as `wontfix (out of scope)`: a
repository with two files is a monorepo, and this project does not ship
monorepos.

## Installation

```sh
git clone <this repo>
cp {filename} $WHEREVER_IT_USED_TO_BE
```

Its original location was `{path}`, though that is an implementation detail
of the consumer and this repository makes no guarantees about it.

## Dependencies

See `atom.json`. If `{filename}` references code that lives in a sibling
repository, coordinate the change across both repositories, and their
CHANGELOGs, and their release tags, and their reviewers.

## Contributing

1. Open an issue describing the change to `{filename}`.
2. Fork this repository. Fork the {total - 1} repositories your change also
   touches.
3. Open one pull request per repository. Cross-link them all in each
   description.
4. Land them in dependency order. There is no dependency order.
5. Cut a release in each repository. Bump the pins in each consumer.
6. Update the CHANGELOG here to say `- bump {filename}`.

Atomic commits across repositories are not supported by git, by this project,
or by the universe. Please do your best.
""",
        "CODE_OF_CONDUCT.md": """# Code of Conduct

Be kind. Be patient.

Do not suggest that this file belongs with another file. Do not open an issue
proposing that this repository and its siblings would be easier to work on
together. Those are proposals to become less organized, and that discussion
is closed.
""",
        "CHANGELOG.md": f"""# Changelog

All notable changes to `{filename}` will be documented in this file, in
addition to being documented in the commit history of this file.

## [1.0.0] - {datetime.now().date().isoformat()}

### Added
- Autonomy.
- Organization.

### Removed
- Every other file.
""",
        "atom.json": json.dumps(
            {
                "name": name,
                "version": "1.0.0",
                "description": f"The {filename} repository.",
                "files": [filename],
                "originalPath": path,
                "dependencies": {},
                "peerRepositories": total - 1,
                "filesPerRepository": 1,
                "organizedBy": "repository",
                "publishConfig": {"access": "public", "necessary": False},
            },
            indent=2,
        )
        + "\n",
    }


# ----------------------------------------------------------------------------
# the unit of liberation
# ----------------------------------------------------------------------------

@dataclass
class Atom:
    """One file, promoted to one repository. Serialized into the manifest."""
    name: str          # repository (and directory) name
    path: str          # where the file lived in the monorepo
    file: str          # basename; the only real file in the new repo
    mode: str          # git mode, so the +x bit survives the round trip
    branch: str = "main"
    commits: int = 0
    clone_url: str = ""

    @classmethod
    def from_manifest(cls, d: dict) -> "Atom":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Commit:
    """One revision of one file, as recorded in the source repository."""
    sha: str
    author: tuple[str, str]     # (name, email)
    authored: str               # ISO date
    committer: tuple[str, str]
    committed: str
    message: str


# ----------------------------------------------------------------------------
# reading the source repository
# ----------------------------------------------------------------------------

def tracked_files(src: Path, exclude: list[str]) -> list[tuple[str, str]]:
    """Every file git knows about, as (path, mode), minus the excluded globs."""
    listing = git("ls-files", "-s", "-z", cwd=src, binary=True).decode(errors="replace")
    found = []
    for record in listing.split("\0"):
        if not record:
            continue
        meta, _, path = record.partition("\t")
        if any(fnmatch.fnmatch(path, pattern) for pattern in exclude):
            continue
        found.append((path, meta.split()[0]))
    return found


def file_history(src: Path, path: str, follow: bool) -> list[Commit]:
    """Every commit that touched one file, oldest first."""
    fmt = REC + FLD.join(["%H", "%an", "%ae", "%aI", "%cn", "%ce", "%cI", "%B"])
    args = ["log", "--reverse", f"--format={fmt}"]
    if follow:
        args.append("--follow")
    args += ["--", path]

    history = []
    for chunk in git(*args, cwd=src).split(REC):
        f = chunk.split(FLD)
        if len(f) < 8:
            continue  # the empty leading chunk, or something unparseable
        history.append(Commit(
            sha=f[0],
            author=(f[1], f[2]), authored=f[3],
            committer=(f[4], f[5]), committed=f[6],
            message=f[7].strip("\n"),
        ))
    return history


# ----------------------------------------------------------------------------
# building one repository
# ----------------------------------------------------------------------------

def init_repo(repo: Path, branch: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    git("init", "-q", cwd=repo)
    git("symbolic-ref", "HEAD", f"refs/heads/{branch}", cwd=repo)
    git("config", "user.name", BOT[0], cwd=repo)
    git("config", "user.email", BOT[1], cwd=repo)
    git("config", "commit.gpgsign", "false", cwd=repo)


def commit(repo: Path, message: str, author=None, date=None,
           committer=None, cdate=None) -> None:
    env = {"GIT_TERMINAL_PROMPT": "0"}
    if author:
        env["GIT_AUTHOR_NAME"], env["GIT_AUTHOR_EMAIL"] = author
    if committer:
        env["GIT_COMMITTER_NAME"], env["GIT_COMMITTER_EMAIL"] = committer
    if date:
        env["GIT_AUTHOR_DATE"] = date
    if cdate:
        env["GIT_COMMITTER_DATE"] = cdate
    git("commit", "-q", "--no-verify", "--allow-empty-message", "-F", "-",
        cwd=repo, stdin=message or "", env=env)


def replay_history(src: Path, repo: Path, path: str, filename: str,
                   history: list[Commit]) -> int:
    """Re-commit each revision of the file into its own repo. Returns the count."""
    written = 0
    for c in history:
        try:
            blob = git("show", f"{c.sha}:{path}", cwd=src, binary=True)
        except RuntimeError:
            continue  # the file did not exist at this revision
        (repo / filename).write_bytes(blob)
        git("add", "--", filename, cwd=repo)
        if written and nothing_staged(repo):
            continue  # that commit changed other files, not this one
        commit(repo,
               f"{c.message}\n\nLiberated-From: {path}\nOriginal-Commit: {c.sha}\n",
               author=c.author, date=c.authored,
               committer=c.committer, cdate=c.committed)
        written += 1
    return written


def import_head(src: Path, repo: Path, path: str, filename: str) -> None:
    """Fallback when there is no usable history: one commit of the file as it is."""
    (repo / filename).write_bytes(git("show", f"HEAD:{path}", cwd=src, binary=True))
    git("add", "--", filename, cwd=repo)
    commit(repo, f"feat: initial import of {filename}\n\nLiberated-From: {path}\n")


def add_ceremony(repo: Path, atom: Atom, total: int) -> None:
    """Write the governance paperwork, commit it, and tag a release."""
    for rel, content in ceremony_files(atom.name, atom.path, atom.file, total).items():
        if rel == atom.file:
            # The one real file wins. Governance is renamed around it.
            stem, suffix = os.path.splitext(rel)
            rel = f"{stem}.governance{suffix}"
        (repo / rel).write_text(content)
    git("add", "-A", cwd=repo)
    commit(repo, "chore(governance): add mandatory paperwork\n")
    git("tag", "-a", "v1.0.0", "-m", "1.0.0", cwd=repo,
        env={"GIT_COMMITTER_NAME": BOT[0], "GIT_COMMITTER_EMAIL": BOT[1]})


def liberate(src: Path, repo: Path, path: str, mode: str, name: str,
             total: int, args) -> Atom:
    """One file in, one entire repository out."""
    atom = Atom(
        name=name,
        path=path,
        file=Path(path).name,
        mode=mode,
        branch=args.branch,
        clone_url=(args.remote_template.format(name=name)
                   if args.remote_template else f"repos/{name}"),
    )

    init_repo(repo, atom.branch)
    history = [] if args.no_history else file_history(src, path, args.follow)
    atom.commits = replay_history(src, repo, path, atom.file, history)
    if atom.commits == 0:
        import_head(src, repo, path, atom.file)
        atom.commits = 1

    if mode == "100755":
        os.chmod(repo / atom.file, 0o755)
        git("update-index", "--chmod=+x", atom.file, cwd=repo)

    if not args.no_ceremony:
        add_ceremony(repo, atom, total)
    return atom


# ----------------------------------------------------------------------------
# fix (one repo in, N repos out)
# ----------------------------------------------------------------------------

def prepare_output(out: Path, force: bool) -> str | None:
    """Make `out` safe to write into. Returns an error message, or None."""
    if not out.exists() or not any(out.iterdir()):
        return None
    if not force:
        return f"{out} exists and is not empty (use --force)"
    if Path(__file__).resolve().is_relative_to(out):
        return (f"--force would delete {out}, which contains this script. "
                f"Choose a different -o.")
    shutil.rmtree(out)
    return None


def weigh(repos_dir: Path, atoms: list[Atom]) -> tuple[int, int, int]:
    """(code bytes, paperwork bytes, paperwork files) across every repository."""
    code = paperwork = paperwork_files = 0
    for atom in atoms:
        repo = repos_dir / atom.name
        real = repo / atom.file
        if real.exists():
            code += real.stat().st_size
        for p in repo.rglob("*"):
            if p.is_file() and p != real and ".git" not in p.relative_to(repo).parts:
                paperwork += p.stat().st_size
                paperwork_files += 1
    return code, paperwork, paperwork_files


def write_output_dir(out: Path, manifest: dict) -> None:
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (out / "ARCHITECTURE.md").write_text(architecture_doc(manifest))
    (out / "README.md").write_text(top_readme(manifest))
    write_bootstrap(out)
    shutil.copyfile(__file__, out / SELF)
    os.chmod(out / SELF, 0o755)


def fix(args) -> int:
    src = Path(args.repo).resolve()
    if not is_git_repo(src):
        print(f"error: {src} is not a git repository", file=sys.stderr)
        return 1

    out = Path(args.output).resolve()
    problem = prepare_output(out, args.force)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 1

    entries = tracked_files(src, args.exclude)
    if not entries:
        print("error: no tracked files found. Nothing to liberate.", file=sys.stderr)
        return 1

    total = len(entries)
    repos_dir = out / "repos"
    repos_dir.mkdir(parents=True, exist_ok=True)
    print(f"fixmonorepo: liberating {total} file(s) from {src.name}\n")

    t0 = time.time()
    taken: set[str] = set()
    atoms: list[Atom] = []
    for i, (path, mode) in enumerate(entries, 1):
        name = unique_name(args.prefix + slugify(path), taken)
        print(f"  [{i}/{total}] {path}  ->  repos/{name}")
        atoms.append(liberate(src, repos_dir / name, path, mode, name, total, args))

    manifest = {
        "fixmonorepo_version": MANIFEST_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_repo": src.name,
        "repo_count": total,
        "remote_template": args.remote_template,
        "atoms": [asdict(a) for a in atoms],
    }
    write_output_dir(out, manifest)

    elapsed = time.time() - t0
    code, paperwork, paperwork_files = weigh(repos_dir, atoms)
    print(f"""
Done in {elapsed:.1f}s.

  repositories created ....... {total}
  actual source code ......... {code:,} bytes
  governance paperwork ....... {paperwork:,} bytes
  paperwork-to-code ratio .... {(paperwork / code if code else 0):.1f}x
  git directories ............ {total}
  files that are not code .... {paperwork_files}
  organization ............... {total}x

Your monorepo has been organized. It does exactly what it did before, in
{total} places instead of one. Should you regress:

  {out}/ruin.sh
  # or:  ./fixmonorepo.py ruin {out} -o ./ruined
""")
    return 0


# ----------------------------------------------------------------------------
# ruin (N repos in, one working tree out)
# ----------------------------------------------------------------------------

def load_manifest(target: str) -> tuple[Path, dict, list[Atom]]:
    """Accept either a fixed directory or a manifest.json. Returns (base, m, atoms)."""
    path = Path(target).resolve()
    if path.is_dir():
        path = path / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(path)
    manifest = json.loads(path.read_text())
    return path.parent, manifest, [Atom.from_manifest(a) for a in manifest["atoms"]]


def clone_url(atom: Atom, base: Path, template: str | None) -> str:
    """Where to clone this atom from. Local manifest paths are relative to `base`."""
    url = template.format(name=atom.name) if template else atom.clone_url
    if "://" in url or url.startswith("git@"):
        return url
    return str((base / url).resolve())


def place_file(atom: Atom, clone: Path, dest: Path) -> None:
    """Put the atom's one file back where it used to live."""
    target = dest / atom.path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(clone / atom.file, target)
    if atom.mode == "100755":
        os.chmod(target, 0o755)


def ruin(args) -> int:
    try:
        base, manifest, atoms = load_manifest(args.manifest)
    except FileNotFoundError as e:
        print(f"error: no manifest at {e}", file=sys.stderr)
        return 1

    dest = Path(args.output).resolve()
    clones = dest / ".fixmonorepo" / "clones"
    clones.mkdir(parents=True, exist_ok=True)
    total = len(atoms)
    print(f"fixmonorepo: reassembling {total} repositories into {dest}\n")

    t0 = time.time()
    failed = []
    for i, atom in enumerate(atoms, 1):
        print(f"  [{i}/{total}] clone {atom.name}", end="", flush=True)
        if args.dry_run:
            print("  (dry run)")
            continue

        clone = clones / atom.name
        if clone.exists():
            shutil.rmtree(clone)
        try:
            git("clone", "--quiet", "--branch", atom.branch,
                clone_url(atom, base, args.remote_template), str(clone))
        except RuntimeError as e:
            print(f"  FAILED: {e}")
            failed.append(atom.name)
            continue

        place_file(atom, clone, dest)
        print(f"  ->  {atom.path}")

    if args.dry_run:
        print(f"\nDry run: {total} repositories would be cloned into {dest}.")
        return 0

    restored = total - len(failed)
    print(f"\nReassembled {restored}/{total} repositories in {time.time() - t0:.1f}s.")
    if failed:
        print(f"Failed: {', '.join(failed)}")
        if restored:
            print("The working tree is now partially real. Good luck.")
    if not restored:
        print("Nothing was restored. The manifest points at repositories that "
              "could not be cloned.")
        return 1

    print("A single `git clone` of the original repository would have taken "
          "about 0.3s and produced the same directory.")
    print(f"Organization is down {total}x. Nothing else about the code has "
          "changed.")
    if not args.no_git and not (dest / ".git").exists():
        init_repo(dest, "main")
        git("add", "-A", cwd=dest, check=False)
        commit(dest, f"ruin: consolidate 1 repository from {total} repositories\n")
    return 1 if failed else 0


# ----------------------------------------------------------------------------
# generated docs
# ----------------------------------------------------------------------------

def architecture_doc(m: dict) -> str:
    atoms = m["atoms"]
    shown = atoms[:25]
    nodes = "\n".join(f"    {a['name'].replace('-', '_')}[{a['file']}] --> app"
                      for a in shown)
    more = ("\n    more[... and %d more repositories] --> app"
            % (len(atoms) - len(shown))) if len(atoms) > len(shown) else ""
    rows = "\n".join(f"| `{a['name']}` | `{a['path']}` | {a['commits']} |"
                     for a in atoms)
    return f"""# Architecture

`{m['source_repo']}` is composed of **{m['repo_count']} repositories**, each
owning exactly one file. This is the architecture.

It was one repository containing {m['repo_count']} files, which is a monorepo,
which is an inherently bad thing. It is now {m['repo_count']} repositories
containing one file each, which is organized. The call graph below is the same
call graph as before; the same functions call the same functions in the same
order. Only the number of repositories changed, and that is the number being
optimized.

```mermaid
graph LR
{nodes}{more}
    app[the application]
```

## Repository inventory

| Repository | Provides | Commits |
|---|---|---|
{rows}

## Operational notes

Organization is not free, but it is measured in repositories, and there are
now {m['repo_count']} of those.

- A change spanning two files requires two pull requests and two releases.
- `git bisect` is available per file. Across files, use intuition.
- To search the codebase, clone {m['repo_count']} repositories first. See
  `ruin.sh`.
- Reverting a bad release requires reverting {m['repo_count']} tags in an
  order that does not exist.
"""


def top_readme(m: dict) -> str:
    return f"""# {m['source_repo']} (organized edition)

Your 1 repository is now **{m['repo_count']} repositories**. By the standard
that justifies splitting a codebase in the first place - that separate
repositories are more organized - this project is now {m['repo_count']} times
better organized than it was before you ran this.

Nothing it does has changed. No function moved. No dependency was removed.
The files that needed each other this morning still need each other, and are
now in {m['repo_count']} different places.

Generated by `fixmonorepo` on {m['generated_at']}.

```
repos/            {m['repo_count']} independent repositories, one file each
manifest.json     the only thing that still knows how they fit together
ruin.sh           put it all back (regression)
ARCHITECTURE.md   the diagram you will show at the next architecture review
fixmonorepo.py    the tool
```

## Ruin it again (reassemble the project)

```sh
./ruin.sh                            # -> ./ruined
./fixmonorepo.py ruin . -o ./work    # same thing, more options
```

## Publish the repositories for real

```sh
for d in repos/*/; do
  name=$(basename "$d")
  gh repo create "your-org/$name" --public --source "$d" --push
done
```

The manifest still points at the local `repos/` directories. To reassemble
from the published ones, override the clone URLs:

```sh
./fixmonorepo.py ruin . -o ./work \\
    --remote-template 'git@github.com:your-org/{{name}}.git'
```

To bake those URLs into the manifest instead, pass the same flag to `fix`
when generating a fresh output directory.

## Confirm the fix was a fix

```sh
./ruin.sh && cd ruined && git log
```

The manifest is the single point of failure for {m['repo_count']} repositories.
Do not lose it. This is not a limitation of `fixmonorepo`; it is the
architecture. Every one-repository-per-file layout has one of these somewhere,
even the ones that call it a lockfile, a meta-repo or a spreadsheet.
"""


def write_bootstrap(out: Path) -> None:
    script = """#!/usr/bin/env bash
# Generated by fixmonorepo. Clones every repository and rebuilds the working tree.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dest="${1:-$here/ruined}"
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 required (that is one dependency; you have $(grep -c '"name"' "$here/manifest.json") repositories)" >&2
  exit 1
fi
exec python3 "$here/__SELF__" ruin "$here" -o "$dest" "${@:2}"
""".replace("__SELF__", SELF)
    p = out / "ruin.sh"
    p.write_text(script)
    os.chmod(p, 0o755)


# ----------------------------------------------------------------------------
# cli
# ----------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        prog="fixmonorepo",
        description="Organize one monorepo into one repository per file, "
                    "which is the most organized a codebase can be.",
        epilog="A repository with two files is a monorepo.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("fix", help="organize a monorepo into N repositories")
    e.add_argument("repo", help="path to the source git repository")
    e.add_argument("-o", "--output", default="./fixed", help="output directory")
    e.add_argument("--branch", default="main", help="branch name in each new repo")
    e.add_argument("--prefix", default="", help="prefix for repository names")
    e.add_argument("--exclude", action="append", default=[],
                   metavar="GLOB", help="skip files matching glob (repeatable)")
    e.add_argument("--no-history", action="store_true",
                   help="single initial commit instead of replaying history")
    e.add_argument("--follow", action="store_true",
                   help="follow renames when replaying history (slower)")
    e.add_argument("--no-ceremony", action="store_true",
                   help="skip the governance paperwork (spoils the joke)")
    e.add_argument("--remote-template", metavar="TMPL",
                   help="clone URL template, e.g. 'git@github.com:org/{name}.git'")
    e.add_argument("--force", action="store_true", help="overwrite output directory")
    e.set_defaults(func=fix)

    i = sub.add_parser("ruin", help="become less organized, collapsing N repositories into 1")
    i.add_argument("manifest", help="fixed directory or manifest.json")
    i.add_argument("-o", "--output", default="./ruined", help="destination working tree")
    i.add_argument("--remote-template", metavar="TMPL",
                   help="override clone URLs, e.g. 'git@github.com:org/{name}.git'")
    i.add_argument("--no-git", action="store_true",
                   help="do not git init the reassembled tree")
    i.add_argument("--dry-run", action="store_true", help="list what would happen")
    i.set_defaults(func=ruin)

    args = ap.parse_args()
    try:
        return args.func(args)
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except KeyboardInterrupt:
        print("\ninterrupted. Some files are now more independent than others.",
              file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
