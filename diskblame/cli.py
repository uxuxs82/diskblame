import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, db, scan, why
from .config import config_path, expand_path, load_config, write_default_config
from .format import (
    format_delta,
    format_size,
    format_time,
    human_age,
    parse_duration,
    parse_size,
)


class Colors:
    def __init__(self, enabled):
        self.enabled = enabled

    def _wrap(self, code, text):
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    def red(self, text):
        return self._wrap("31", text)

    def green(self, text):
        return self._wrap("32", text)

    def yellow(self, text):
        return self._wrap("33", text)

    def bold(self, text):
        return self._wrap("1", text)

    def dim(self, text):
        return self._wrap("2", text)


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=argparse.SUPPRESS, help="database path")
    common.add_argument("--config", default=argparse.SUPPRESS, help="config path")
    common.add_argument(
        "--no-color",
        action="store_true",
        default=argparse.SUPPRESS,
        help="disable colors",
    )

    parser = argparse.ArgumentParser(
        prog="diskblame",
        description="Track what grows on your disk and why.",
    )
    parser.add_argument("--db", help="database path")
    parser.add_argument("--config", help="config path")
    parser.add_argument("--no-color", action="store_true", help="disable colors")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser(
        "snap", parents=[common], help="scan a directory and store a snapshot"
    )
    snap.add_argument("path", nargs="?", default="~")
    snap.add_argument("--min-file-size", help="store files at least this large")
    snap.add_argument("--exclude", action="append", default=[], help="exclude a name or glob")
    snap.add_argument("--follow-symlinks", action="store_true")
    snap.add_argument("--json", action="store_true")
    snap.set_defaults(func=cmd_snap)

    diff = sub.add_parser(
        "diff", parents=[common], help="show what changed between snapshots"
    )
    diff.add_argument("--root")
    diff.add_argument("--from", dest="from_id", type=int)
    diff.add_argument("--to", dest="to_id", type=int)
    diff.add_argument("--since", help="compare with a snapshot at least this old")
    diff.add_argument("--path", help="limit to a relative path")
    diff.add_argument("--limit", type=int, default=20)
    diff.add_argument("--files", action="store_true", help="show file changes")
    diff.add_argument("--json", action="store_true")
    diff.set_defaults(func=cmd_diff)

    top = sub.add_parser(
        "top", parents=[common], help="show the largest directories or files"
    )
    top.add_argument("--root")
    top.add_argument("--snapshot", type=int)
    top.add_argument("--path", help="limit to a relative path")
    top.add_argument("--depth", type=int, default=1)
    top.add_argument("--limit", type=int, default=20)
    top.add_argument("--files", action="store_true")
    top.add_argument("--json", action="store_true")
    top.set_defaults(func=cmd_top)

    why_parser = sub.add_parser(
        "why", parents=[common], help="explain a file or directory"
    )
    why_parser.add_argument("path")
    why_parser.add_argument("--snapshot", type=int)
    why_parser.add_argument("--no-refs", action="store_true")
    why_parser.add_argument("--json", action="store_true")
    why_parser.set_defaults(func=cmd_why)

    prune = sub.add_parser(
        "prune", parents=[common], help="delete old snapshots"
    )
    prune.add_argument("--keep", type=int)
    prune.add_argument("--older-than")
    prune.add_argument("--vacuum", action="store_true")
    prune.add_argument("--json", action="store_true")
    prune.set_defaults(func=cmd_prune)

    chart = sub.add_parser(
        "chart", parents=[common], help="show total size over time"
    )
    chart.add_argument("--root")
    chart.add_argument("--days", type=int, default=30)
    chart.add_argument("--json", action="store_true")
    chart.set_defaults(func=cmd_chart)

    watch = sub.add_parser(
        "watch", parents=[common], help="alert when a directory grows too much"
    )
    watch.add_argument("--root")
    watch.add_argument("--since", default="7d")
    watch.add_argument("--max-growth", default="500MiB")
    watch.add_argument("--interval", default="1h")
    watch.add_argument("--once", action="store_true")
    watch.add_argument("--snap", action="store_true", help="take a snapshot on each check")
    watch.add_argument("--notify", action="store_true", help="use termux-notification")
    watch.add_argument("--json", action="store_true")
    watch.set_defaults(func=cmd_watch)

    config = sub.add_parser(
        "config", parents=[common], help="show or create the config"
    )
    config.add_argument("--init", action="store_true")
    config.add_argument("--json", action="store_true")
    config.set_defaults(func=cmd_config)

    return parser


def snapshot_dict(row):
    return {key: row[key] for key in row.keys()}


def open_db(config):
    return db.connect(config.db_path)


def resolve_filter(path):
    if not path:
        return ""
    value = path.strip().strip("/")
    return "" if value == "." else value


def matches_filter(path, filter_path):
    if not filter_path:
        return True
    return path == filter_path or path.startswith(filter_path + "/")


def compare_dirs(from_dirs, to_dirs, filter_path, limit):
    raw = []
    for path in set(from_dirs) | set(to_dirs):
        if not matches_filter(path, filter_path):
            continue
        before = from_dirs[path] if path in from_dirs else None
        after = to_dirs[path] if path in to_dirs else None
        before_size = before["size"] if before else 0
        after_size = after["size"] if after else 0
        delta = after_size - before_size
        if delta == 0:
            continue
        if before is None:
            status = "added"
        elif after is None:
            status = "deleted"
        else:
            status = "changed"
        raw.append(
            {
                "path": path,
                "status": status,
                "delta": delta,
                "size": after_size,
                "files_delta": (after["files"] if after else 0)
                - (before["files"] if before else 0),
                "dirs_delta": (after["dirs"] if after else 0)
                - (before["dirs"] if before else 0),
            }
        )

    def parent_of(path):
        if path == ".":
            return None
        if "/" in path:
            return path.rsplit("/", 1)[0]
        return "."

    by_path = {item["path"]: item for item in raw}
    children = {}
    for item in raw:
        parent = parent_of(item["path"])
        if parent is not None:
            children.setdefault(parent, []).append(item)

    changes = []
    for item in raw:
        path = item["path"]
        parent = parent_of(path)
        parent_item = by_path.get(parent)
        if item["status"] == "added" and parent_item and parent_item["status"] == "added":
            continue
        if item["status"] == "deleted" and parent_item and parent_item["status"] == "deleted":
            continue
        child_delta = sum(child["delta"] for child in children.get(path, []))
        direct_delta = item["delta"] - child_delta
        if item["status"] == "changed" and direct_delta == 0:
            continue
        item["direct_delta"] = direct_delta
        changes.append(item)

    changes.sort(key=lambda item: abs(item["delta"]), reverse=True)
    return changes[:limit]


def compare_files(from_files, to_files, filter_path, limit):
    changes = []
    for path in set(from_files) | set(to_files):
        if not matches_filter(path, filter_path):
            continue
        before = from_files[path] if path in from_files else None
        after = to_files[path] if path in to_files else None
        before_size = before["size"] if before else 0
        after_size = after["size"] if after else 0
        delta = after_size - before_size
        if delta == 0:
            continue
        if before is None:
            status = "added"
        elif after is None:
            status = "deleted"
        else:
            status = "changed"
        changes.append(
            {
                "path": path,
                "status": status,
                "delta": delta,
                "size": after_size,
                "before": before_size,
            }
        )
    changes.sort(key=lambda item: abs(item["delta"]), reverse=True)
    return changes[:limit]


def cmd_snap(args, config, color):
    root = Path(args.path).expanduser()
    exclude = list(config.exclude)
    for item in args.exclude:
        if item not in exclude:
            exclude.append(item)
    min_file_size = (
        parse_size(args.min_file_size) if args.min_file_size else config.min_file_size
    )
    follow_symlinks = args.follow_symlinks or config.follow_symlinks
    result = scan.scan(
        root,
        exclude=exclude,
        min_file_size=min_file_size,
        follow_symlinks=follow_symlinks,
    )
    conn = open_db(config)
    created_at = time.time()
    snapshot_id = db.insert_snapshot(
        conn,
        created_at,
        result.root,
        result.total_size,
        result.total_files,
        result.total_dirs,
        result.elapsed_ms,
        result.skipped,
        __version__,
        result.dirs,
        result.files,
    )
    snapshot = db.get_snapshot(conn, snapshot_id)
    previous = db.previous_snapshot(conn, snapshot)
    delta = result.total_size - previous["total_size"] if previous else None
    db_size = db.database_size(conn)
    conn.close()

    if args.json:
        payload = {
            "snapshot": snapshot_dict(snapshot),
            "previous": snapshot_dict(previous) if previous else None,
            "delta": delta,
            "db_size": db_size,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print(f"snapshot {snapshot_id}: {result.root}")
    print(
        f"{format_size(result.total_size)}, "
        f"{result.total_files} files, {result.total_dirs} dirs, "
        f"{result.elapsed_ms} ms"
    )
    if previous:
        print(
            f"since {previous['id']} ({format_time(previous['created_at'])}): "
            f"{color.red(format_delta(delta)) if delta > 0 else color.green(format_delta(delta))}"
        )
    if result.skipped:
        print(color.yellow(f"skipped {result.skipped} unreadable entries"))
    print(color.dim(f"db: {config.db_path} ({format_size(db_size)})"))
    return 0


def cmd_diff(args, config, color):
    conn = open_db(config)
    if args.to_id:
        to_snapshot = db.get_snapshot(conn, args.to_id)
    else:
        to_snapshot = db.latest_snapshot(conn, args.root)
    if to_snapshot is None:
        raise ValueError("no snapshots found")

    if args.from_id:
        from_snapshot = db.get_snapshot(conn, args.from_id)
    elif args.since:
        cutoff = time.time() - parse_duration(args.since)
        from_snapshot = db.snapshot_at_or_before(conn, to_snapshot["root"], cutoff)
        if from_snapshot is None:
            rows = db.list_snapshots(conn, to_snapshot["root"])
            from_snapshot = rows[-1] if rows else None
    else:
        from_snapshot = db.previous_snapshot(conn, to_snapshot)

    if from_snapshot is None:
        raise ValueError("need at least two snapshots")
    if from_snapshot["id"] == to_snapshot["id"]:
        raise ValueError("from and to are the same snapshot")
    if from_snapshot["root"] != to_snapshot["root"]:
        raise ValueError("snapshots have different roots")

    filter_path = resolve_filter(args.path)
    from_dirs = db.get_dirs(conn, from_snapshot["id"])
    to_dirs = db.get_dirs(conn, to_snapshot["id"])
    changes = compare_dirs(from_dirs, to_dirs, filter_path, args.limit)
    file_changes = []
    if args.files:
        from_files = db.get_files(conn, from_snapshot["id"])
        to_files = db.get_files(conn, to_snapshot["id"])
        file_changes = compare_files(from_files, to_files, filter_path, args.limit)
    total_delta = to_snapshot["total_size"] - from_snapshot["total_size"]
    conn.close()

    if args.json:
        payload = {
            "from": snapshot_dict(from_snapshot),
            "to": snapshot_dict(to_snapshot),
            "total_delta": total_delta,
            "changes": changes,
            "files": file_changes,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print(
        f"from {from_snapshot['id']} ({format_time(from_snapshot['created_at'])}) "
        f"{format_size(from_snapshot['total_size'])}"
    )
    print(
        f"to   {to_snapshot['id']} ({format_time(to_snapshot['created_at'])}) "
        f"{format_size(to_snapshot['total_size'])}"
    )
    total_text = format_delta(total_delta)
    print(f"total {color.red(total_text) if total_delta > 0 else color.green(total_text)}")
    print()

    if not changes and not file_changes:
        print("no changes")
        return 0

    if not args.files:
        for item in changes:
            text = f"{format_delta(item['delta']):>12}"
            colored = color.red(text) if item["delta"] > 0 else color.green(text)
            print(f"{colored}  {item['path']}")
        return 0

    print(color.bold("directories"))
    for item in changes:
        text = f"{format_delta(item['delta']):>12}"
        colored = color.red(text) if item["delta"] > 0 else color.green(text)
        print(f"{colored}  {item['path']}")
    if file_changes:
        print()
        print(color.bold("files"))
        for item in file_changes:
            text = f"{format_delta(item['delta']):>12}"
            colored = color.red(text) if item["delta"] > 0 else color.green(text)
            print(f"{colored}  {item['status']:<8} {item['path']}")
    return 0


def cmd_top(args, config, color):
    conn = open_db(config)
    if args.snapshot:
        snapshot = db.get_snapshot(conn, args.snapshot)
    else:
        snapshot = db.latest_snapshot(conn, args.root)
    if snapshot is None:
        raise ValueError("no snapshots found")

    filter_path = resolve_filter(args.path)
    rows = []
    if args.files:
        files = db.get_files(conn, snapshot["id"])
        for path, row in files.items():
            if not matches_filter(path, filter_path):
                continue
            rows.append({"path": path, "size": row["size"], "mtime": row["mtime"]})
    else:
        directories = db.get_dirs(conn, snapshot["id"])
        base = filter_path or "."
        prefix = "" if base == "." else base + "/"
        for path, row in directories.items():
            if path == base:
                continue
            if base == ".":
                depth = path.count("/") + 1
            else:
                if not path.startswith(prefix):
                    continue
                depth = path[len(prefix) :].count("/") + 1
            if depth > args.depth:
                continue
            rows.append(
                {
                    "path": path,
                    "size": row["size"],
                    "files": row["files"],
                    "dirs": row["dirs"],
                    "mtime": row["mtime"],
                }
            )
    rows.sort(key=lambda item: item["size"], reverse=True)
    rows = rows[: args.limit]
    conn.close()

    if args.json:
        payload = {
            "snapshot": snapshot_dict(snapshot),
            "path": filter_path or ".",
            "items": rows,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print(
        f"snapshot {snapshot['id']} ({format_time(snapshot['created_at'])}), "
        f"{format_size(snapshot['total_size'])}"
    )
    for item in rows:
        suffix = ""
        if not args.files:
            suffix = color.dim(f"  {item['files']} files, {item['dirs']} dirs")
        print(f"{format_size(item['size']):>10}  {item['path']}{suffix}")
    return 0


def print_git(info):
    if not info:
        return "not in a git repo"
    parts = []
    parts.append("tracked" if info.get("tracked") else "untracked")
    if info.get("ignored"):
        parts.append("ignored")
    if info.get("added"):
        parts.append(f"added {info['added']}")
    if info.get("last"):
        parts.append(f"last {info['last']}")
    return ", ".join(parts)


def cmd_why(args, config, color):
    conn = open_db(config)
    info = why.explain(
        conn,
        args.path,
        snapshot_id=args.snapshot,
        include_refs=not args.no_refs,
    )
    conn.close()

    if args.json:
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return 0

    print(color.bold(info["path"]))
    kind = info["kind"]
    if info.get("dimensions"):
        kind = f"{kind}, {info['dimensions'][0]}x{info['dimensions'][1]}"
    print(f"  type: {kind}")
    if info["kind"] == "directory":
        print(f"  size: {format_size(info['size'])}")
    else:
        print(
            f"  size: {format_size(info['size'])} "
            f"(apparent {format_size(info['apparent'])})"
        )
    print(
        f"  modified: {format_time(info['mtime'])} "
        f"({human_age(info['mtime'])})"
    )
    print(
        f"  mode: {oct(info['mode'] & 0o7777)}, "
        f"inode: {info['inode']}, links: {info['links']}"
    )
    if info.get("cache"):
        print(f"  cache: {color.yellow(info['cache'])}")
    else:
        print("  cache: no")
    print(f"  git: {print_git(info.get('git', {}))}")
    if info["kind"] == "directory":
        print(f"  contents: {info['files']} files, {info['dirs']} dirs")
        if info.get("children"):
            print("  largest children:")
            for path, size in info["children"]:
                print(f"    {format_size(size):>10}  {path}")
    else:
        if args.no_refs:
            print("  references: skipped")
        elif info.get("references"):
            refs = ", ".join(f"{path}:{line}" for path, line in info["references"][:10])
            print(f"  references: {refs}")
        else:
            print("  references: none found")
        if info.get("duplicates"):
            print("  duplicates:")
            for path in info["duplicates"]:
                print(f"    {path}")
    print(f"  verdict: {color.bold(info['recommendation'])}")
    return 0


def cmd_prune(args, config, color):
    conn = open_db(config)
    keep = args.keep
    older_than = None
    if args.older_than:
        older_than = time.time() - parse_duration(args.older_than)
    if keep is None and older_than is None:
        keep = 20
    if keep is not None and keep < 1:
        raise ValueError("keep must be at least 1")
    deleted = db.prune_snapshots(conn, keep=keep, older_than=older_than)
    if args.vacuum:
        db.vacuum(conn)
    db_size = db.database_size(conn)
    conn.close()

    if args.json:
        print(
            json.dumps(
                {"deleted": deleted, "db_size": db_size},
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    print(f"deleted {deleted} snapshots")
    print(color.dim(f"db: {config.db_path} ({format_size(db_size)})"))
    return 0


def cmd_chart(args, config, color):
    conn = open_db(config)
    if args.root:
        root = db.normalize_root(args.root)
    else:
        latest = db.latest_snapshot(conn)
        if latest is None:
            raise ValueError("no snapshots found")
        root = latest["root"]
    rows = db.list_snapshots(conn, root)
    conn.close()
    rows = list(reversed(rows))
    if args.days > 0:
        cutoff = time.time() - args.days * 86400
        rows = [row for row in rows if row["created_at"] >= cutoff]
    if not rows:
        raise ValueError("no snapshots in range")

    if args.json:
        payload = {"root": root, "items": [snapshot_dict(row) for row in rows]}
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print(color.bold(root))
    maximum = max(row["total_size"] for row in rows) or 1
    for row in rows:
        width = max(1, round(row["total_size"] / maximum * 40))
        print(
            f"{format_time(row['created_at'])}  "
            f"{format_size(row['total_size']):>10}  {'#' * width}"
        )
    return 0


def notify(message):
    command = shutil.which("termux-notification")
    if not command:
        print("termux-notification not found", file=sys.stderr)
        return False
    try:
        subprocess.run(
            [command, "--title", "diskblame", "--content", message],
            capture_output=True,
            timeout=10,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def cmd_watch(args, config, color):
    conn = open_db(config)
    if args.root:
        root = db.normalize_root(args.root)
    else:
        latest = db.latest_snapshot(conn)
        if latest is None:
            raise ValueError("no snapshots found")
        root = latest["root"]

    since = parse_duration(args.since)
    max_growth = parse_size(args.max_growth)
    interval = parse_duration(args.interval)
    if interval < 1:
        raise ValueError("interval must be at least 1s")

    alerted = False
    try:
        while True:
            if args.snap:
                result = scan.scan(
                    root,
                    exclude=config.exclude,
                    min_file_size=config.min_file_size,
                    follow_symlinks=config.follow_symlinks,
                )
                snapshot_id = db.insert_snapshot(
                    conn,
                    time.time(),
                    result.root,
                    result.total_size,
                    result.total_files,
                    result.total_dirs,
                    result.elapsed_ms,
                    result.skipped,
                    __version__,
                    result.dirs,
                    result.files,
                )
                if not args.json:
                    print(f"snapshot {snapshot_id}: {format_size(result.total_size)}")

            latest = db.latest_snapshot(conn, root)
            baseline = db.snapshot_at_or_before(conn, root, time.time() - since)
            if baseline is None:
                rows = db.list_snapshots(conn, root)
                baseline = rows[-1] if rows else None
            if latest is None or baseline is None or latest["id"] == baseline["id"]:
                growth = 0
            else:
                growth = latest["total_size"] - baseline["total_size"]

            if growth > 0 and growth >= max_growth:
                alerted = True
                message = (
                    f"{root} grew {format_size(growth)} in {args.since} "
                    f"(limit {format_size(max_growth)})"
                )
                if args.json:
                    print(
                        json.dumps(
                            {
                                "root": root,
                                "growth": growth,
                                "limit": max_growth,
                                "since": args.since,
                                "message": message,
                            },
                            ensure_ascii=False,
                        )
                    )
                else:
                    print(color.red(f"alert: {message}"))
                if args.notify:
                    notify(message)

            if args.once:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        return 130
    finally:
        conn.close()
    return 2 if alerted else 0


def cmd_config(args, config, color):
    path = expand_path(args.config) if args.config else config_path()
    if args.init:
        write_default_config(path)
    exists = path.exists()
    payload = {
        "config_path": str(path),
        "exists": exists,
        "db_path": str(config.db_path),
        "exclude": config.exclude,
        "min_file_size": config.min_file_size,
        "follow_symlinks": config.follow_symlinks,
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    print(f"config: {path}{'' if exists else ' (not found, using defaults)'}")
    print(f"db: {config.db_path}")
    print(f"exclude: {', '.join(config.exclude)}")
    print(f"min file size: {format_size(config.min_file_size)}")
    print(f"follow symlinks: {config.follow_symlinks}")
    return 0


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.db:
        config.db_path = expand_path(args.db)
    color = Colors(
        sys.stdout.isatty()
        and not args.no_color
        and not os.environ.get("NO_COLOR")
    )
    try:
        return args.func(args, config, color)
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"diskblame: {exc}", file=sys.stderr)
        return 1
