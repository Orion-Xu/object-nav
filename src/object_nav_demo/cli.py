from __future__ import annotations

import argparse
import json
import sys

from .app_factory import build_offline_demo
from .command_parser import CommandParser
from .config import default_config, load_yaml
from .models import jsonable
from .vocabulary_manager import VocabularyManager


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="目标可见条件下的短距离局部导航 Demo")
    sub = parser.add_subparsers(dest="subcommand", required=True)
    sub.add_parser("list", help="列出配置目标和策略")
    sub.add_parser("doctor", help="检查 Python、GPU、模型和 ROS 基础环境")
    parse_cmd = sub.add_parser("parse", help="解析受控中文指令")
    parse_cmd.add_argument("command")
    parse_cmd.add_argument("--backend", choices=("world", "fallback"), default="world")
    demo = sub.add_parser("demo", help="运行确定性 Mock 闭环")
    demo.add_argument("command")
    demo.add_argument("--log", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    vocabulary = VocabularyManager(default_config("vocabulary.yaml"))
    system = load_yaml(default_config("system.yaml"))
    if args.subcommand == "doctor":
        from .environment_doctor import main as doctor_main
        return doctor_main()
    if args.subcommand == "list":
        for item in vocabulary.policies:
            print(f"{item.canonical_label:16} {item.navigation_mode.value:11} {'/'.join(item.aliases_zh)}")
        return 0
    if args.subcommand == "parse":
        supported = ({item.canonical_label for item in vocabulary.policies} if args.backend == "world"
                     else set(system["detector"]["fallback_supported"]))
        result = CommandParser(vocabulary).parse(args.command, supported)
        print(json.dumps(jsonable(result), ensure_ascii=False, indent=2))
        return 0 if result.accepted else 2
    preliminary = CommandParser(vocabulary).parse(args.command, {item.canonical_label for item in vocabulary.policies})
    if not preliminary.accepted or preliminary.policy is None:
        print(preliminary.reason, file=sys.stderr)
        return 2
    machine = build_offline_demo(preliminary.policy.canonical_label, args.log)
    state = machine.run(args.command)
    print(json.dumps({"state": state.value, "reason": machine.failure_reason,
                      "backend": machine.detector.info.backend,
                      "model_version": machine.detector.info.model_version}, ensure_ascii=False))
    return 0 if state.value == "ARRIVED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
