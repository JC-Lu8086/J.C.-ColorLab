"""Build on the target OS; no cross-compilation or publication is performed."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from collect_licenses import collect


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a local JC ColorLab desktop package")
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument("--work-dir", type=Path, default=Path("build"))
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    output = (project / args.dist_dir).resolve()
    work = (project / args.work_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    notices = work / "licenses"
    collect(notices)
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--name", "JC ColorLab", "--paths", str(project),
        "--distpath", str(output), "--workpath", str(work / "pyinstaller"),
        "--specpath", str(work), "--collect-submodules", "jc_colorlab",
        "--add-data", f"{project / 'jc_colorlab' / 'static'}:jc_colorlab/static",
        "--collect-all", "rawpy", "--collect-all", "cv2",
        "--hidden-import", "jc_colorlab.__main__",
        "--add-data", f"{notices}:licenses",
        "--add-data", f"{project / 'LICENSE'}:.",
        "--add-data", f"{project / 'THIRD_PARTY_NOTICES.md'}:.",
        "--add-data", f"{project / 'docs'}:docs",
    ]
    if sys.platform == "darwin":
        command += ["--windowed", "--osx-bundle-identifier", "org.jclu.jccolorlab"]
    elif sys.platform == "win32":
        command += ["--windowed", "--add-data", f"{project / 'jc_colorlab' / 'native'}:jc_colorlab/native"]
    command.append(str(project / "scripts" / "desktop_entry.py"))
    environment = dict(os.environ)
    environment["PYINSTALLER_CONFIG_DIR"] = str(work / "cache")
    subprocess.run(command, cwd=project, check=True, env=environment)
    # Keep the legal notices accessible alongside the app as well as inside it.
    shutil.copytree(notices, output / "licenses", dirs_exist_ok=True)
    for name in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md"):
        shutil.copy2(project / name, output / name)
    shutil.copytree(project / "docs", output / "docs", dirs_exist_ok=True)
    print(f"Built {platform.system()} {platform.machine()} package in {output}")
    print("This build is local and unsigned; no release was uploaded.")


if __name__ == "__main__":
    main()

