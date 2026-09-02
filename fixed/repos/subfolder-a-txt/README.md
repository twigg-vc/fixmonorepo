# subfolder-a-txt

![build](https://img.shields.io/badge/build-passing-brightgreen) ![coverage](https://img.shields.io/badge/coverage-100%25-brightgreen) ![files](https://img.shields.io/badge/files-1-blue) ![repos](https://img.shields.io/badge/sibling%20repos-4-orange)

The canonical home of **`a.txt`**.

`a.txt` used to be one line in a directory listing, sharing a repository
with 4 unrelated files. It now has its own repository, its own
history, its own releases, its own issue tracker, and its own README, which
is this one. Everything that could be separated has been separated.

## Organization

| | before | after |
|---|---|---|
| repositories | 1 | 5 |
| files in this repository | 5 | 1 |
| places to look for `a.txt` | 1 | 1 |
| places to look for anything else | 1 | 4 |

The right-hand column is more organized than the left-hand column, because
the number of repositories in it is larger. That is the metric that was
optimized. The other rows were not consulted.

## Scope

This repository contains `a.txt`. It does not contain anything else.
Requests to add a second file will be closed as `wontfix (out of scope)`: a
repository with two files is a monorepo, and this project does not ship
monorepos.

## Installation

```sh
git clone <this repo>
cp a.txt $WHEREVER_IT_USED_TO_BE
```

Its original location was `subfolder/a.txt`, though that is an implementation detail
of the consumer and this repository makes no guarantees about it.

## Dependencies

See `atom.json`. If `a.txt` references code that lives in a sibling
repository, coordinate the change across both repositories, and their
CHANGELOGs, and their release tags, and their reviewers.

## Contributing

1. Open an issue describing the change to `a.txt`.
2. Fork this repository. Fork the 4 repositories your change also
   touches.
3. Open one pull request per repository. Cross-link them all in each
   description.
4. Land them in dependency order. There is no dependency order.
5. Cut a release in each repository. Bump the pins in each consumer.
6. Update the CHANGELOG here to say `- bump a.txt`.

Atomic commits across repositories are not supported by git, by this project,
or by the universe. Please do your best.
