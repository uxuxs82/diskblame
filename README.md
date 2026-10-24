# diskblame

![ci](https://github.com/uxuxs82/diskblame/actions/workflows/ci.yml/badge.svg)

`diskblame` keeps a lightweight history of disk usage and tells you what changed.

`du` and `ncdu` show the current state. `diskblame` stores metadata snapshots in SQLite, so you can ask what grew since last week, which directory is responsible, and why a file is still there.

It never copies your files.

## Why not just du?

`du` and `ncdu` answer "what is big now". They do not answer "what got big since last week" unless you keep full copies or remember the numbers. `diskblame` stores a few numbers per path and compares them later.

It is built for the case where storage is already tight: a phone, a small VPS, or a laptop with a full disk. The database is metadata only, so a snapshot of a 100 GiB directory usually fits in a few megabytes.

| tool | keeps history | explains a path |
| --- | --- | --- |
| `du`, `ncdu` | no | no |
| `duc` | indexed current state | no |
| `snapdiff` | compares two trees | no |
| `diskblame` | metadata snapshots | `diff` and `why` |

## Install

Requires Python 3.11 or newer. There are no runtime dependencies.

```sh
pipx install git+https://github.com/uxuxs82/diskblame.git
```

Or from a local checkout:

```sh
git clone https://github.com/uxuxs82/diskblame.git
cd diskblame
pip install .
```

On Termux:

```sh
pkg install python
pip install .
```

## Quick start

```sh
diskblame snap ~
diskblame snap ~
diskblame diff --since 7d
```

The first snapshot is the baseline. The second one gives `diff` something to compare against.

Show the largest directories:

```sh
diskblame top --depth 2
```

Show the largest files:

```sh
diskblame top --files --limit 30
```

Explain a file:

```sh
diskblame why ~/storage/shared/DCIM/Camera/IMG_0001.jpg
```

`why` reports the size, type, age, git status, duplicates, references in nearby text files, and whether the path looks like a cache or build directory. It does not claim a file is safe to delete. It gives you the facts and a conservative verdict.

## Commands

| command | what it does |
| --- | --- |
| `snap [path]` | scan a directory and store a snapshot |
| `diff` | compare two snapshots, defaulting to the last two |
| `top` | show the largest directories or files in a snapshot |
| `why <path>` | explain a file or directory |
| `chart` | show total size over time |
| `watch` | alert when a directory grows past a limit |
| `prune` | delete old snapshots |
| `config` | show or create the config file |

Useful options:

```sh
diskblame snap ~ --exclude '*.log' --min-file-size 5MiB
diskblame diff --since 30d --path DCIM --limit 10
diskblame diff --files --limit 50
diskblame why ~/Downloads/archive.zip --no-refs
diskblame chart --days 90
diskblame prune --keep 20 --vacuum
diskblame watch --root ~ --since 7d --max-growth 1GiB --snap --interval 1h
```

Most commands accept `--json` for scripts.

## How it works

A snapshot stores:

- one row per directory with total size, file count, and directory count
- one row per file at or above `min_file_size`, default 1 MiB
- snapshot metadata: root, time, total size, file count, directory count, elapsed time

Directory totals include all files, including those below the file threshold. The file threshold only limits which individual files are stored for `top --files`, `diff --files`, and duplicate checks. `diff --files` reports size changes, not content changes.

Hard links are counted once in directory totals. Symbolic links are skipped unless `--follow-symlinks` is used. Unreadable entries are counted and reported, not treated as zero.

The database lives in `~/.local/share/diskblame/diskblame.db` by default. A snapshot of a few hundred thousand paths is small compared with a full copy of the files.

## Config

The default config is `~/.config/diskblame/config.toml`. Create it with:

```sh
diskblame config --init
```

Example:

```toml
[scan]
exclude = [".git", ".hg", ".svn", "__pycache__", ".DS_Store", "lost+found"]
min_file_size = "1MiB"
follow_symlinks = false

[db]
path = "~/.local/share/diskblame/diskblame.db"
```

`--db` and `--config` override the paths for one command.

## Limitations

- It stores metadata, not file contents. It cannot restore anything.
- It is not a backup tool and does not replace `du`, `ncdu`, or `duc`.
- Directory sizes depend on the filesystem's block accounting. Sparse files can report a smaller size than their apparent length.
- Duplicate detection compares stored files with the same size, then hashes them. Large files use the first and last 1 MiB plus the size.
- Reference search uses `git grep` inside a repository and a bounded text-file scan outside one.
- `watch` is a foreground loop. Run it in tmux or a service manager if you want it to stay alive.

## License

MIT
