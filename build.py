#!/usr/bin/env python3
"""
构建脚本 — 将 Content Hub 编译为独立可执行文件

支持平台:
  - Windows (.exe)
  - macOS (unix binary)
  - Linux (unix binary)

使用方法:
  python build.py          # 构建当前平台
  python build.py --clean  # 清理构建产物后重新构建
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR / "backend"
DIST_DIR = BASE_DIR / "dist"
BUILD_DIR = BASE_DIR / "build"


def clean():
    """清理之前的构建产物"""
    print("🧹 清理旧的构建产物...")
    for d in [DIST_DIR, BUILD_DIR]:
        if d.exists():
            shutil.rmtree(d)
            print(f"  已删除 {d}")
    spec_file = BASE_DIR / "content-hub.spec"
    if spec_file.exists():
        spec_file.unlink()
        print(f"  已删除 {spec_file}")


def build():
    """使用 PyInstaller 构建"""
    print("🔨 开始构建 Content Hub...")
    print(f"  Python: {sys.executable}")
    print(f"  平台: {sys.platform}")

    # 检查 PyInstaller
    try:
        import PyInstaller
        print(f"  PyInstaller: {PyInstaller.__version__}")
    except ImportError:
        print("❌ 未安装 PyInstaller，正在安装...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 构建参数
    name = "content-hub"
    entry = str(BACKEND_DIR / "cli.py")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", name,
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--specpath", str(BASE_DIR),
        # 添加 backend 目录下的所有模块
        "--add-data", f"{BACKEND_DIR / 'scrapers'}{os.pathsep}scrapers",
        "--add-data", f"{BACKEND_DIR / 'services'}{os.pathsep}services",
        # 隐式导入
        "--hidden-import", "aiosqlite",
        "--hidden-import", "sqlalchemy.ext.asyncio",
        "--hidden-import", "sqlalchemy",
        "--hidden-import", "httpx",
        "--hidden-import", "yt_dlp",
        "--hidden-import", "xhshow",
        "--hidden-import", "dashscope",
        "--hidden-import", "dashscope.audio.asr",
        "--hidden-import", "pydantic",
        # 收集所有 yt-dlp 子模块（它的提取器太多）
        "--collect-all", "yt_dlp",
        "--collect-all", "xhshow",
        "--collect-all", "dashscope",
        # 不弹出控制台窗口（仅 Windows）
        # "--noconsole",  # CLI 工具需要控制台
        "--clean",
        entry,
    ]

    print(f"\n  执行命令: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=str(BASE_DIR))

    if result.returncode != 0:
        print(f"\n❌ 构建失败 (exit code: {result.returncode})")
        sys.exit(1)

    # 检查输出
    ext = ".exe" if sys.platform == "win32" else ""
    output = DIST_DIR / f"{name}{ext}"
    if output.exists():
        size_mb = output.stat().st_size / 1024 / 1024
        print(f"\n✅ 构建成功!")
        print(f"   输出: {output}")
        print(f"   大小: {size_mb:.1f} MB")
        print(f"\n🚀 使用方法:")
        print(f"   {output} --help")
        print(f"   {output} search youtube Python 教程")
        print(f"   {output} scrape https://www.youtube.com/watch?v=xxx")
    else:
        print(f"\n❌ 未找到输出文件: {output}")
        sys.exit(1)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="构建 Content Hub 可执行文件")
    parser.add_argument("--clean", action="store_true", help="清理旧的构建产物后重新构建")
    parser.add_argument("--clean-only", action="store_true", help="仅清理，不构建")
    args = parser.parse_args()

    if args.clean or args.clean_only:
        clean()
    if not args.clean_only:
        build()


if __name__ == "__main__":
    main()
