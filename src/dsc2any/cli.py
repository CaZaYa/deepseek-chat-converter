"""命令行入口。"""

from __future__ import annotations

import argparse
import sys

from .core import APP_NAME, APP_VERSION, FORMATS, ConversionError, Options, convert, run_directory


def _configure_console() -> None:
    """让 Windows 控制台按 UTF-8 显示中文，避免 cmd/PowerShell 乱码。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv=None) -> int:
    _configure_console()
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv:
        print(f"{APP_NAME} {APP_VERSION} —— 命令行版本")
        print("这是命令行工具，需要提供导出包和输出目录。")
        print(r'示例：DeepSeek2Any-CLI.exe "D:\deepseek_data.zip" "D:\输出目录" --format chatbox')
        print("图形界面请双击 DeepSeek2Any.exe。")
        try:
            input("\n按回车键退出…")
        except EOFError:
            pass
        return 2

    if len(argv) == 1 and argv[0].lower().endswith(".zip"):
        return interactive(argv[0])

    parser = argparse.ArgumentParser(prog=APP_NAME, description="把 DeepSeek 导出包转换成通用聊天记录格式。")
    parser.add_argument("zip_path", help="DeepSeek 导出的 deepseek_data-*.zip")
    parser.add_argument("out_dir", help="输出目录")
    parser.add_argument("--format", choices=[fmt[0] for fmt in FORMATS], default="markdown")
    parser.add_argument("--with-thinking", action="store_true", help="包含思考过程")
    parser.add_argument("--chunk-size", type=int, default=200, help="ChatGPT JSON 每文件会话数，0 不拆分")
    parser.add_argument("--name", default=None, help="本次输出子文件夹名（默认按时间戳）")
    parser.add_argument("--template", default=None, help="cherry-mobile 格式需要：手机端导出的备份 zip")
    parser.add_argument("--select", default="", help="只导出标题包含这些关键词的会话，逗号分隔")
    parser.add_argument("--keep-template", action="store_true", help="cherry-mobile: 保留模板已有会话并追加（默认清空模板会话）")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    args = parser.parse_args(argv)

    try:
        target = run_directory(args.out_dir, args.name)
        report = convert(
            args.zip_path,
            str(target),
            fmt=args.format,
            options=Options(
                with_thinking=args.with_thinking,
                chunk_size=args.chunk_size,
                template=args.template,
                select=tuple(item.strip() for item in args.select.split(",") if item.strip()),
                keep_template=args.keep_template,
            ),
            log=print,
        )
    except ConversionError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1

    print(f"输出目录：{report.output_dir}")
    return 0


def interactive(zip_arg: str) -> int:
    """把 zip 拖到 exe 上时：问一下格式，其余用默认值。"""
    from pathlib import Path

    zip_path = Path(zip_arg)
    print(f"导出包：{zip_path}")
    print("选择输出格式：")
    print("  1  Chatbox 备份包")
    print("  2  Markdown 文集（默认）")
    print("  3  JSONL")
    print("  4  ChatGPT JSON")
    try:
        choice = input("输入 1-4 后回车：").strip() or "2"
    except EOFError:
        choice = "2"
    fmt = {"1": "chatbox", "2": "markdown", "3": "jsonl", "4": "chatgpt"}.get(choice, "markdown")

    out_dir = run_directory(zip_path.with_name(zip_path.stem + "_export"))
    try:
        report = convert(
            str(zip_path), str(out_dir), fmt=fmt,
            options=Options(with_thinking=True), log=print,
        )
    except ConversionError as error:
        print(f"错误：{error}", file=sys.stderr)
        try:
            input("按回车键退出…")
        except EOFError:
            pass
        return 1

    print(f"\n输出目录：{report.output_dir}")
    try:
        input("按回车键退出…")
    except EOFError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
