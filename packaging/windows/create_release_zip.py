from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RELEASE_DIR = ROOT / "dist" / "release"
PACKAGE_DIR = RELEASE_DIR / "auto_titration_windows"


INCLUDE_PATHS = [
    "AutoTitration.exe",
    "README.md",
    "requirements.txt",
    "requirements-yolo.txt",
    "auto_titrator",
    "tools",
    "website",
    "launchers",
    "vendor",
    "data/labeled",
    "data/fixtures",
    "data/chemistry_constants",
]


EXCLUDE_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "node_modules",
}


def copy_tree(src: Path, dst: Path) -> None:
    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        for name in names:
            if name in EXCLUDE_DIR_NAMES:
                ignored.add(name)
            if name.endswith((".pyc", ".pyo", ".tmp")):
                ignored.add(name)
        return ignored

    shutil.copytree(src, dst, ignore=ignore)


def copy_item(relative: str) -> None:
    if relative == "AutoTitration.exe":
        src = RELEASE_DIR / "AutoTitration.exe"
    else:
        src = ROOT / relative
    dst = PACKAGE_DIR / relative
    if not src.exists():
        print(f"skip missing: {relative}")
        return
    if src.is_dir():
        copy_tree(src, dst)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def write_quick_start() -> None:
    text = """Auto Titration Windows 실행 방법

1. AutoTitration.exe를 더블클릭한다.
2. 브라우저가 자동으로 열리면 일반 카메라, Mini2, 펌프 상태를 확인한다.
3. 처음 실행 시 필요한 Python 패키지를 자동 설치하므로 시간이 걸릴 수 있다.
4. Arduino를 나중에 꽂아도 앱이 자동 재연결을 시도한다.
5. Arduino가 없어도 녹화와 CSV 저장은 가능하다.

필요 조건
- Windows
- Python 3 설치
- 첫 실행 시 패키지 설치를 위한 인터넷 연결 권장
- Mini2 온도 변환용 vendor/hikmicro_analyzer DLL 폴더 포함
- 펌프 사용 시 Arduino USB 연결 및 IDE 시리얼 모니터 종료
"""
    (PACKAGE_DIR / "실행방법.txt").write_text(text, encoding="utf-8")


def main() -> int:
    global PACKAGE_DIR

    exe = RELEASE_DIR / "AutoTitration.exe"
    if not exe.exists():
        print(f"missing launcher exe: {exe}", file=sys.stderr)
        return 2

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    PACKAGE_DIR = RELEASE_DIR / f"auto_titration_windows_stage_{stamp}"
    if PACKAGE_DIR.exists():
        shutil.rmtree(PACKAGE_DIR)
    PACKAGE_DIR.mkdir(parents=True)

    for relative in INCLUDE_PATHS:
        copy_item(relative)

    (PACKAGE_DIR / "data" / "raw").mkdir(parents=True, exist_ok=True)
    write_quick_start()

    archive_base = RELEASE_DIR / f"auto-titration-windows-{stamp}"
    archive_path = shutil.make_archive(str(archive_base), "zip", PACKAGE_DIR)
    print(archive_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
