#!/usr/bin/env python3
"""Configure Skill-local conversation log routes and enable the skill in a Git repository."""

import argparse
import json
import os
import platform
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SKILL_NAME = "agent-logger"
SKILL_DIR = Path(__file__).resolve().parent.parent
ROUTES_FILE = SKILL_DIR / "routes.json"
OPTIONAL_FIELDS = (
    "user", "image_description", "reply", "device", "project", "source",
    "timezone", "files", "skills", "ai", "model",
)
PACKAGE_FILES = ("SKILL.md", "routes.example.json", "scripts/logger_setup.py")
AGENTS_BLOCK = """<!-- agent-logger:begin -->
## Conversation log

Before every final response, read and follow `.agents/skills/agent-logger/SKILL.md`.
If the log cannot be written, say why in the final response.
<!-- agent-logger:end -->"""
CLAUDE_BLOCK = """<!-- agent-logger:begin -->
Before every final response, read and follow `.agents/skills/agent-logger/SKILL.md`.
If the log cannot be written, say why in the final response.
<!-- agent-logger:end -->"""
CURSOR_RULE = """---
description: Record every user turn with agent-logger
alwaysApply: true
---

Before every final response, read and follow `.agents/skills/agent-logger/SKILL.md`.
If the log cannot be written, say why in the final response.
"""
LOCAL_PATHS = (
    "/AGENTS.override.md", "/CLAUDE.local.md",
    "/.agents/skills/agent-logger/",
    "/.cursor/rules/agent-logger.mdc",
)


def hostname():
    if platform.system() == "Darwin":
        try:
            name = subprocess.run(
                ["scutil", "--get", "LocalHostName"], capture_output=True,
                text=True, check=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            name = socket.gethostname()
    else:
        name = socket.gethostname()
    name = name.strip().lower()
    return name[:-6] if name.endswith(".local") else name


def read_json(path):
    try:
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
    except json.JSONDecodeError as exc:
        raise ValueError(f"无效的 JSON 配置：{path}（{exc}）") from exc
    if not isinstance(data, dict):
        raise ValueError(f"配置必须是 JSON 对象：{path}")
    return data


def validate_fields(raw):
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise ValueError("excluded_fields 必须是字符串列表")
    unknown = sorted(set(raw) - set(OPTIONAL_FIELDS))
    if unknown:
        raise ValueError("未知记录字段：" + ", ".join(unknown))
    return [field for field in OPTIONAL_FIELDS if field in raw]


def validate_root(raw):
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("日志目录为空")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError(f"日志目录必须是绝对路径：{raw}")
    path = path.resolve(strict=True)
    if not path.is_dir():
        raise ValueError(f"日志路径不是目录：{path}")
    with tempfile.TemporaryFile(dir=path):
        pass
    return path


def resolve():
    routes = read_json(ROUTES_FILE) if ROUTES_FILE.exists() else {}
    mapping = routes.get("log_root_by_host", {})
    if not isinstance(mapping, dict):
        raise ValueError(f"{ROUTES_FILE} 的 log_root_by_host 必须是对象")
    host = hostname()
    raw = mapping.get(host)
    if not raw:
        raise ValueError(f"设备 {host} 在 {ROUTES_FILE} 中没有日志目录；请询问用户路径")
    try:
        root = validate_root(raw)
    except (OSError, ValueError) as exc:
        raise ValueError(f"设备 {host} 的日志目录无效（{ROUTES_FILE}: {raw}）：{exc}") from exc
    field_mapping = routes.get("excluded_fields_by_host", {})
    if not isinstance(field_mapping, dict):
        raise ValueError(f"{ROUTES_FILE} 的 excluded_fields_by_host 必须是对象")
    fields = validate_fields(field_mapping.get(host, []))
    return {
        "host": host, "source": "route", "log_root": str(root),
        "excluded_fields": fields, "routes_file": str(ROUTES_FILE),
    }


def configure(path, create=False, excluded_fields=None):
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise ValueError(f"日志目录必须是绝对路径：{path}")
    if create:
        candidate.mkdir(parents=True, exist_ok=True)
    root = validate_root(str(candidate))
    current = read_json(ROUTES_FILE) if ROUTES_FILE.exists() else {}
    paths = current.get("log_root_by_host", {})
    field_mapping = current.get("excluded_fields_by_host", {})
    if not isinstance(paths, dict) or not isinstance(field_mapping, dict):
        raise ValueError(f"{ROUTES_FILE} 中的设备映射必须是对象")
    host = hostname()
    fields = field_mapping.get(host, []) if excluded_fields is None else excluded_fields
    paths[host] = str(root)
    field_mapping[host] = validate_fields(fields)
    current.pop("prefer_device_route", None)
    current["log_root_by_host"] = paths
    current["excluded_fields_by_host"] = field_mapping
    ROUTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=ROUTES_FILE.parent, delete=False
    ) as stream:
        json.dump(current, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temp_name = stream.name
    try:
        os.replace(temp_name, ROUTES_FILE)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return resolve()


def run_git(path, *args):
    return subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True,
        text=True, encoding="utf-8", check=False,
    )


def git_repository(path):
    root = run_git(path, "rev-parse", "--show-toplevel")
    common = run_git(path, "rev-parse", "--git-common-dir")
    if root.returncode or common.returncode:
        raise ValueError(f"目标不是 Git 仓库：{path}")
    repository = Path(root.stdout.strip()).resolve(strict=True)
    common_dir = Path(common.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = (Path(path) / common_dir).resolve(strict=True)
    return repository, common_dir


def copied_skill(target, update):
    if target.resolve() == SKILL_DIR.resolve():
        return
    if target.exists() and not update:
        if all(
            (target / part).is_file()
            and (target / part).read_bytes() == (SKILL_DIR / part).read_bytes()
            for part in PACKAGE_FILES
        ):
            return
        raise ValueError(f"目标 Skill 已存在且内容不同：{target}；确认更新后加 --update")
    target.mkdir(parents=True, exist_ok=True)
    for part in PACKAGE_FILES:
        destination = target / part
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SKILL_DIR / part, destination)


def copy_current_route(target):
    """Give a new Skill copy this device's route without replacing its own routes."""
    if target.resolve() == SKILL_DIR.resolve():
        return
    source = read_json(ROUTES_FILE)
    host = hostname()
    source_paths = source.get("log_root_by_host", {})
    source_fields = source.get("excluded_fields_by_host", {})
    destination = target / "routes.json"
    current = read_json(destination) if destination.exists() else {}
    paths = current.get("log_root_by_host", {})
    fields = current.get("excluded_fields_by_host", {})
    if not all(isinstance(value, dict) for value in (source_paths, source_fields, paths, fields)):
        raise ValueError("routes.json 中的设备映射必须是对象")
    if host not in paths:
        paths[host] = source_paths[host]
        fields[host] = source_fields.get(host, [])
        current["log_root_by_host"] = paths
        current["excluded_fields_by_host"] = fields
        destination.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def merge_block(path, block):
    content = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    start = "<!-- agent-logger:begin -->"
    end = "<!-- agent-logger:end -->"
    if start in content or end in content:
        if content.count(start) != 1 or content.count(end) != 1:
            raise ValueError(f"项目规则标记不完整：{path}")
        beginning = content.index(start)
        ending = content.index(end, beginning) + len(end)
        content = content[:beginning] + block + content[ending:]
    else:
        content = content.rstrip() + ("\n\n" if content.strip() else "") + block
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def validate_block(path):
    if not path.exists():
        return
    content = path.read_text(encoding="utf-8-sig")
    start = "<!-- agent-logger:begin -->"
    end = "<!-- agent-logger:end -->"
    if (content.count(start) != content.count(end)
            or content.count(start) > 1
            or (start in content and content.index(end) < content.index(start))):
        raise ValueError(f"项目规则标记不完整：{path}")


def set_local_exclude(common_dir, rules_local, logs_local, log_root, repository):
    path = common_dir / "info" / "exclude"
    start = "# agent-logger:begin"
    end = "# agent-logger:end"
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    if start in content or end in content:
        if content.count(start) != 1 or content.count(end) != 1:
            raise ValueError(f"Git exclude 标记不完整：{path}")
        beginning = content.index(start)
        ending = content.index(end, beginning) + len(end)
        content = content[:beginning] + content[ending:]
    patterns = list(LOCAL_PATHS) if rules_local else ["/.agents/skills/agent-logger/routes.json"]
    if logs_local:
        try:
            relative = Path(log_root).relative_to(repository)
        except ValueError:
            relative = None
        if relative is not None:
            if str(relative) in ("", "."):
                raise ValueError("日志根目录不能是目标仓库根目录")
            patterns.append("/" + relative.as_posix().rstrip("/") + "/")
    if patterns:
        block = "\n".join((start, *patterns, end))
        content = content.rstrip() + ("\n\n" if content.strip() else "") + block + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return path


def tracked_paths(repository, paths):
    result = run_git(repository, "ls-files", "--", *paths)
    if result.returncode:
        raise ValueError(result.stderr.strip() or "无法检查 Git 索引")
    return result.stdout.splitlines()


def install(repo, visibility, log_visibility, update=False):
    settings = resolve()
    repository, common_dir = git_repository(Path(repo).expanduser().resolve(strict=True))
    private_route = ".agents/skills/agent-logger/routes.json"
    if tracked_paths(repository, (private_route,)):
        raise ValueError(f"本机路由已被 Git 跟踪，请先检查 Git 索引：{private_route}")
    paths = (
        "AGENTS.override.md", "CLAUDE.local.md",
        ".agents/skills/agent-logger",
        ".cursor/rules/agent-logger.mdc",
    )
    tracked = tracked_paths(repository, paths) if visibility == "local" else []
    if visibility == "local":
        agents_file = repository / "AGENTS.md"
        if agents_file.is_file() and "agent-logger" in agents_file.read_text(encoding="utf-8-sig"):
            if tracked_paths(repository, ("AGENTS.md",)):
                tracked.append("AGENTS.md（含对话日志规则）")
    if log_visibility == "local":
        try:
            relative = Path(settings["log_root"]).relative_to(repository)
        except ValueError:
            relative = None
        if relative is not None:
            tracked += tracked_paths(repository, (str(relative),))
    if tracked:
        raise ValueError("本地模式不能隐藏已跟踪文件，请先检查 Git 索引：" + "、".join(tracked))
    target = repository / ".agents" / "skills" / SKILL_NAME
    if target.exists() and not update and target.resolve() != SKILL_DIR.resolve():
        copied_skill(target, False)
    cursor = repository / ".cursor" / "rules" / f"{SKILL_NAME}.mdc"
    if cursor.exists() and not update and cursor.read_text(encoding="utf-8-sig") != CURSOR_RULE:
        raise ValueError(f"Cursor 规则已存在且内容不同：{cursor}；确认更新后加 --update")
    agents = repository / "AGENTS.override.md"
    claude = repository / "CLAUDE.local.md"
    validate_block(agents)
    validate_block(claude)
    exclude = set_local_exclude(
        common_dir, visibility == "local", log_visibility == "local",
        settings["log_root"], repository
    )
    copied_skill(target, update)
    copy_current_route(target)
    merge_block(agents, AGENTS_BLOCK)
    merge_block(claude, CLAUDE_BLOCK)
    cursor.parent.mkdir(parents=True, exist_ok=True)
    cursor.write_text(CURSOR_RULE, encoding="utf-8")
    return {
        "repository": str(repository), "log_root": settings["log_root"],
        "excluded_fields": settings["excluded_fields"], "visibility": visibility,
        "log_visibility": log_visibility,
        "skill": str(target), "agents_override": str(agents),
        "claude_local": str(claude), "cursor_rule": str(cursor),
        "git_exclude": str(exclude),
    }


def register(update=False):
    destinations = (
        Path.home() / ".agents" / "skills" / SKILL_NAME,
        Path.home() / ".cursor" / "skills" / SKILL_NAME,
        Path.home() / ".claude" / "skills" / SKILL_NAME,
    )
    for target in destinations:
        copied_skill(target, update)
        copy_current_route(target)
    return {"registered": [str(path) for path in destinations]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("resolve", help="验证本机日志目录及记录字段")
    configure_parser = commands.add_parser("configure", help="把当前设备的配置写入 Skill 旁的 routes.json")
    configure_parser.add_argument("--path", required=True, help="日志根目录的绝对路径")
    configure_parser.add_argument("--create", action="store_true", help="按用户要求创建目录")
    configure_parser.add_argument(
        "--exclude-fields", help="不记录的字段，逗号分隔；空字符串表示全部记录"
    )
    install_parser = commands.add_parser("install", help="在指定 Git 仓库启用逐回合日志")
    install_parser.add_argument("--repo", required=True, help="目标 Git 仓库内的目录")
    install_parser.add_argument(
        "--visibility", required=True, choices=("local", "shared"),
        help="local 使用 .git/info/exclude；shared 允许提交生成的规则"
    )
    install_parser.add_argument(
        "--log-visibility", required=True, choices=("local", "shared"),
        help="日志位于目标仓库内时是否写入本地 Git exclude"
    )
    install_parser.add_argument("--update", action="store_true", help="确认后覆盖旧版 Skill/规则")
    register_parser = commands.add_parser("register", help="可选：安装为用户级 Skill")
    register_parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "resolve":
            result = resolve()
        elif args.command == "configure":
            fields = None if args.exclude_fields is None else [
                item.strip() for item in args.exclude_fields.split(",") if item.strip()
            ]
            result = configure(args.path, args.create, fields)
        elif args.command == "install":
            result = install(args.repo, args.visibility, args.log_visibility, args.update)
        else:
            result = register(args.update)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
