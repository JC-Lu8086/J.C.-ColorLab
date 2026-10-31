"""Package an already built desktop app; invoked by the release workflow."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tomllib


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    tag = f"v{version}"
    if os.environ.get("RELEASE_TAG") != tag:
        raise SystemExit("Release tag must match the project version")
    expected = {"darwin": {"arm64"}, "win32": {"amd64", "x86_64"}}
    if platform.machine().lower() not in expected.get(sys.platform, set()):
        raise SystemExit("Unsupported release platform or architecture")
    if args.validate:
        return
    suffix = "macOS-arm64" if sys.platform == "darwin" else "Windows-x64-experimental"
    name = f"JC-ColorLab-{tag}-{suffix}"
    staging = root / "build" / "release-staging" / name
    staging.mkdir(parents=True, exist_ok=False)
    dist = root / "dist"
    app = "JC ColorLab.app" if sys.platform == "darwin" else "JC ColorLab"
    shutil.copytree(dist / app, staging / app, symlinks=True)
    for entry in ("licenses", "docs"):
        shutil.copytree(dist / entry, staging / entry)
    for entry in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md"):
        shutil.copy2(dist / entry, staging / entry)
    environment = subprocess.check_output([sys.executable, "-m", "pip", "freeze", "--all"], text=True)
    (staging / "build-environment.txt").write_text(environment, encoding="utf-8")
    (staging / "BUILD.txt").write_text(
        f"Version: {tag}\nCommit: {os.environ.get('GITHUB_SHA', 'local')}\n"
        f"Platform: {platform.platform()}\nArchitecture: {platform.machine()}\n",
        encoding="utf-8",
    )
    output = root / "release"
    output.mkdir(exist_ok=True)
    archive = output / f"{name}.zip"
    if sys.platform == "darwin":
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(staging / app)], check=True)
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(staging), str(archive)], check=True)
    else:
        shutil.make_archive(str(archive.with_suffix("")), "zip", staging.parent, staging.name)
    print(archive)


if __name__ == "__main__":
    main()
