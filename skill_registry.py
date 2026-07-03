#!/usr/bin/env python3
"""GCP Skill Registry 管理脚本 — 创建、更新、查询 B 站 RPA 技能包。

用法示例：
  python skill_registry.py validate
  python skill_registry.py create
  python skill_registry.py list
  python skill_registry.py get --skill-id bilibili-rpa
  python skill_registry.py retrieve --query "bilibili up主 粉丝数"
  python skill_registry.py update --skill-id bilibili-rpa
  python skill_registry.py delete --skill-id bilibili-rpa
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import agentplatform
from dotenv import load_dotenv

# ==========================================
# 默认配置（可通过环境变量覆盖）
# ==========================================
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
LOCATION = os.getenv("GCP_LOCATION", "us-central1")
DEFAULT_SKILL_ID = os.getenv("SKILL_ID", "bilibili-rpa")
DEFAULT_SKILL_DIR = os.getenv(
    "SKILL_DIR",
    str(Path(__file__).resolve().parent / "skills" / "bilibili-rpa"),
)
DEFAULT_DISPLAY_NAME = os.getenv("SKILL_DISPLAY_NAME", "Bilibili RPA Skill")
DEFAULT_DESCRIPTION = os.getenv(
    "SKILL_DESCRIPTION",
    "指导 Agent 完成 B 站 UP 主粉丝数读取、抓取、写回 Excel 的标准工作流。",
)

SKILL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,62}[a-z0-9]$")


def skill_resource_name(skill_id: str) -> str:
    return f"projects/{PROJECT_ID}/locations/{LOCATION}/skills/{skill_id}"


def get_client() -> agentplatform.Client:
    return agentplatform.Client(project=PROJECT_ID, location=LOCATION)


def validate_skill_dir(skill_dir: Path) -> None:
    """校验本地 Skill 目录结构（SKILL.md + frontmatter name 与目录名一致）。"""
    if not skill_dir.is_dir():
        raise FileNotFoundError(f"Skill 目录不存在: {skill_dir}")

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(f"缺少必需文件: {skill_md}")

    content = skill_md.read_text(encoding="utf-8")
    if not content.startswith("---"):
        raise ValueError("SKILL.md 必须以 YAML frontmatter（---）开头")

    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError("SKILL.md frontmatter 格式不正确")

    frontmatter = parts[1]
    name_match = re.search(r"^name:\s*(.+)$", frontmatter, re.MULTILINE)
    if not name_match:
        raise ValueError("SKILL.md frontmatter 缺少 name 字段")

    skill_name = name_match.group(1).strip().strip('"').strip("'")
    if skill_name != skill_dir.name:
        raise ValueError(
            f"frontmatter name='{skill_name}' 与目录名 '{skill_dir.name}' 不一致"
        )
    if not re.match(r"^[a-z0-9-]+$", skill_name):
        raise ValueError(
            "GCP Skill Registry 要求 name 仅含小写字母、数字和连字符（如 bilibili-rpa）"
        )

    desc_match = re.search(r"^description:\s*(.+)$", frontmatter, re.MULTILINE)
    if not desc_match and "description: >" not in frontmatter:
        raise ValueError("SKILL.md frontmatter 缺少 description 字段")

    print(f"✅ Skill 目录校验通过: {skill_dir}")
    print(f"   name={skill_name}")


def validate_skill_id(skill_id: str) -> None:
    if skill_id.startswith("gcp-"):
        raise ValueError("skill_id 不能以 gcp- 开头（保留给内置技能）")
    if not SKILL_ID_PATTERN.match(skill_id):
        raise ValueError(
            "skill_id 须为 1–63 位小写字母/数字/连字符，且以字母开头、字母或数字结尾"
        )


def cmd_validate(args: argparse.Namespace) -> None:
    skill_dir = Path(args.skill_dir).resolve()
    validate_skill_dir(skill_dir)
    validate_skill_id(args.skill_id)
    print(f"✅ skill_id 格式合法: {args.skill_id}")


def cmd_create(args: argparse.Namespace) -> None:
    skill_dir = Path(args.skill_dir).resolve()
    validate_skill_dir(skill_dir)
    validate_skill_id(args.skill_id)

    client = get_client()
    print(f"📤 正在创建 Skill: {args.skill_id} ({LOCATION}) ...")

    result = client.skills.create(
        skill_id=args.skill_id,
        display_name=args.display_name,
        description=args.description,
        config={
            "local_path": str(skill_dir),
            "wait_for_completion": True,
        },
    )
    print(f"✅ 创建完成: {result.name if hasattr(result, 'name') else result}")


def cmd_list(args: argparse.Namespace) -> None:
    client = get_client()
    pager = client.skills.list()
    count = 0
    for skill in pager:
        count += 1
        state = getattr(skill, "state", None) or "-"
        print(f"- {skill.display_name}")
        print(f"    name:  {skill.name}")
        print(f"    state: {state}")
        if skill.description:
            desc = skill.description.replace("\n", " ")[:120]
            print(f"    desc:  {desc}...")
    if count == 0:
        print("（当前项目/区域下暂无 Skill）")


def cmd_get(args: argparse.Namespace) -> None:
    client = get_client()
    name = skill_resource_name(args.skill_id)
    skill = client.skills.get(name=name)
    print(f"name:         {skill.name}")
    print(f"displayName:  {skill.display_name}")
    print(f"description:  {skill.description}")
    print(f"state:        {getattr(skill, 'state', '-')}")
    print(f"createTime:   {getattr(skill, 'create_time', '-')}")
    print(f"updateTime:   {getattr(skill, 'update_time', '-')}")


def cmd_retrieve(args: argparse.Namespace) -> None:
    client = get_client()
    response = client.skills.retrieve(
        query=args.query,
        config={"top_k": args.top_k},
    )
    skills = response.retrieved_skills or []
    if not skills:
        print("未找到匹配 Skill")
        return
    for i, item in enumerate(skills, 1):
        print(f"{i}. {item.skill_name}")
        print(f"   {item.description}")


def cmd_update(args: argparse.Namespace) -> None:
    skill_dir = Path(args.skill_dir).resolve()
    validate_skill_dir(skill_dir)
    validate_skill_id(args.skill_id)

    client = get_client()
    name = skill_resource_name(args.skill_id)
    print(f"📤 正在更新 Skill: {name} ...")

    config: dict = {
        "local_path": str(skill_dir),
        "wait_for_completion": True,
    }
    if args.display_name:
        config["display_name"] = args.display_name
    if args.description:
        config["description"] = args.description

    result = client.skills.update(name=name, config=config)
    print(f"✅ 更新完成: {result.name if hasattr(result, 'name') else result}")


def cmd_delete(args: argparse.Namespace) -> None:
    if not args.yes:
        confirm = input(f"确认删除 Skill '{args.skill_id}'? [y/N] ")
        if confirm.lower() != "y":
            print("已取消")
            return

    client = get_client()
    name = skill_resource_name(args.skill_id)
    print(f"🗑️  正在删除 Skill: {name} ...")
    client.skills.delete(name=name, config={"wait_for_completion": True})
    print("✅ 删除完成")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="GCP Skill Registry 管理 — Bilibili RPA Skill",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--project",
        default=PROJECT_ID,
        help=f"GCP 项目 ID（默认: {PROJECT_ID}）",
    )
    parser.add_argument(
        "--location",
        default=LOCATION,
        help=f"区域（默认: {LOCATION}）",
    )
    parser.add_argument(
        "--skill-id",
        default=DEFAULT_SKILL_ID,
        help=f"Skill ID（默认: {DEFAULT_SKILL_ID}）",
    )
    parser.add_argument(
        "--skill-dir",
        default=DEFAULT_SKILL_DIR,
        help="本地 Skill 目录路径",
    )
    parser.add_argument(
        "--display-name",
        default=DEFAULT_DISPLAY_NAME,
        help="Skill 显示名称",
    )
    parser.add_argument(
        "--description",
        default=DEFAULT_DESCRIPTION,
        help="Skill 描述",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="校验本地 Skill 目录结构")

    sub.add_parser("create", help="上传并创建 Skill（长时间运行操作）")
    sub.add_parser("list", help="列出已注册 Skill")
    sub.add_parser("get", help="获取 Skill 详情")

    p_retrieve = sub.add_parser("retrieve", help="语义检索 Skill")
    p_retrieve.add_argument(
        "--query",
        required=True,
        help='检索语句，例如 "bilibili up主 粉丝数"',
    )
    p_retrieve.add_argument("--top-k", type=int, default=5, help="返回数量上限")

    sub.add_parser("update", help="更新 Skill 内容与元数据")

    p_delete = sub.add_parser("delete", help="删除 Skill")
    p_delete.add_argument("-y", "--yes", action="store_true", help="跳过确认")

    return parser


def main() -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    global PROJECT_ID, LOCATION
    PROJECT_ID = args.project
    LOCATION = args.location

    handlers = {
        "validate": cmd_validate,
        "create": cmd_create,
        "list": cmd_list,
        "get": cmd_get,
        "retrieve": cmd_retrieve,
        "update": cmd_update,
        "delete": cmd_delete,
    }

    try:
        handlers[args.command](args)
        return 0
    except Exception as exc:
        print(f"❌ 错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
