# FixMonorepo

I was a monorepo guy. I firmly believed the industry defaulted to polyrepos
only due to "we've always done it like this" and not for an actual good reason.

Until one day I was asking a client why they had 7 repos for a Web App,
including one specifically for terraform configs called "infra".
The answer changed everything I knew about software: `to keep things organized`.

I had never considered this. All these years I used a monorepo and just plain
**FOLDERS** for organization, without realizing that what I actually needed was
more repositories to achieve peak organization.

Building on this idea, it occurred to me: *why stop at 7?*

Since **more repos = more organization = better collaboration = higher
stakeholder value**, 7 repos for a Web App is **NOT ENOUGH**. We stop at those
rookie numbers just because our tools are not there yet.

This project is the first step towards fixing this problem. **FixMonorepo** is
a POC tool that automatically fixes monorepos by splitting them into single-file
repositories, and also allows *ruining* the result, i.e. combining the
resulting repos back to the original monorepo.

The ultimate goal is obviously to achieve **Single-Bit** repositories - i.e.
one repo per bit. Here's our current roadmap:
- **Single-File** -> **Single-Line**
- **Single-Line** -> **Single-Byte**
- Finally, implement fixing **Single-Byte** repos to **Single-Bit** repos
- Fix all world problems with software

It'll take a village to get there, so please contribute to the project.

## Instructions

**FixMonorepo** is a simple python script. Just copy the file and run one of
the following commands to fix/ruin a repository:
```
    fixmonorepo.py fix   <repo>    -o <outdir>    # repair the monorepo
    fixmonorepo.py ruin  <outdir>  -o <workdir>   # regress to a monorepo
```

## Demo

For easy demonstration, we've kept an example as part of this repository.
Note that `/fixed` is auto-generated, but we kept it in this repo anyway just
so that it's easy for anyone to inspect the results without running locally.

`/example` is an example monorepo (bad).
Running `make fix-example` generated `/fixed`, and showed the following output:
```
fixmonorepo: liberating 5 file(s) from example

  [1/5] README.md  ->  repos/readme-md
  [2/5] a.txt  ->  repos/a-txt
  [3/5] b.txt  ->  repos/b-txt
  [4/5] subfolder/a.txt  ->  repos/subfolder-a-txt
  [5/5] subfolder/b.txt  ->  repos/subfolder-b-txt

Done in 0.2s.

  repositories created ....... 5
  actual source code ......... 163 bytes
  governance paperwork ....... 15,280 bytes
  paperwork-to-code ratio .... 93.7x
  git directories ............ 5
  files that are not code .... 20
  organization ............... 5x

Your monorepo has been organized. It does exactly what it did before, in
5 places instead of one. Should you regress:

  /home/user/fixmonorepo/fixed/ruin.sh
  # or:  ./fixmonorepo.py ruin /home/user/fixmonorepo/fixed -o ./ruined
```
Running `make ruin-example-fix` generated `/fixed/ruined`, and showed the following output:
```
fixmonorepo: reassembling 5 repositories into /home/user/fixmonorepo/fixed/ruined

  [1/5] clone readme-md  ->  README.md
  [2/5] clone a-txt  ->  a.txt
  [3/5] clone b-txt  ->  b.txt
  [4/5] clone subfolder-a-txt  ->  subfolder/a.txt
  [5/5] clone subfolder-b-txt  ->  subfolder/b.txt

Reassembled 5/5 repositories in 0.1s.
A single `git clone` of the original repository would have taken about 0.3s and produced the same directory.
Organization is down 5x. Nothing else about the code has changed.
```
