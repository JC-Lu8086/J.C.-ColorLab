"""Publish a prerelease after CI has produced both platform archives."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tomllib
import zipfile


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    tag = f"v{version}"
    if os.environ.get("RELEASE_TAG") != tag:
        raise SystemExit("Release tag must match the project version")
    notes = root / "docs" / "releases" / f"{tag}.md"
    if not notes.is_file():
        raise SystemExit("Release notes are required")
    output = root / "release"
    archives = [output / f"JC-ColorLab-{tag}-{suffix}.zip" for suffix in ("macOS-arm64", "Windows-x64-experimental", "source")]
    for archive in archives[:2]:
        with zipfile.ZipFile(archive) as z:
            if z.testzip() is not None:
                raise SystemExit(f"Invalid archive: {archive.name}")
    subprocess.run(["git", "archive", "--format=zip", "--prefix=JC-ColorLab/", f"--output={archives[2]}", "HEAD"], check=True)
    sums = output / f"SHA256SUMS-{tag}.txt"
    checksums = []
    for archive in archives:
        with archive.open("rb") as stream:
            checksums.append(f"{hashlib.file_digest(stream, 'sha256').hexdigest()}  {archive.name}")
    sums.write_text("\n".join(checksums) + "\n", encoding="utf-8")
    assets = [*archives, sums]
    query = subprocess.run(["gh", "release", "view", tag, "--json", "isDraft"], capture_output=True, text=True)
    title = f"JC ColorLab {tag} alpha · 六语界面与 240MP 支持"
    if query.returncode == 0:
        if not json.loads(query.stdout)["isDraft"]:
            raise SystemExit("Refusing to replace an already published release")
        subprocess.run(["gh", "release", "edit", tag, "--title", title, "--notes-file", str(notes), "--prerelease", "--target", os.environ["GITHUB_SHA"]], check=True)
    else:
        subprocess.run(["gh", "release", "create", tag, "--draft", "--prerelease", "--title", title, "--notes-file", str(notes), "--target", os.environ["GITHUB_SHA"]], check=True)
    subprocess.run(["gh", "release", "upload", tag, *map(str, assets), "--clobber"], check=True)
    uploaded = json.loads(subprocess.check_output(["gh", "release", "view", tag, "--json", "assets"], text=True))["assets"]
    sizes = {asset["name"]: asset["size"] for asset in uploaded}
    if any(sizes.get(asset.name) != asset.stat().st_size for asset in assets):
        raise SystemExit("Release remains a draft: uploaded assets did not match expected sizes")
    subprocess.run(["gh", "release", "edit", tag, "--draft=false", "--prerelease"], check=True)


if __name__ == "__main__":
    main()
