"""Collect exact installed dependency versions and their supplied notices.

This collects distribution metadata, not just a manually maintained license list.
Run in the clean build environment. No network access is performed.
"""

from __future__ import annotations

import importlib.metadata as metadata
import json
from pathlib import Path
import re
import shutil
import sys

from packaging.requirements import Requirement

ROOTS = [
    "numpy", "scipy", "Pillow", "opencv-contrib-python-headless", "rawpy",
    "tifffile", "Flask", "Werkzeug", "pyinstaller",
]


def collect(destination: Path) -> list[dict]:
    destination.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    queue = list(ROOTS)
    records = []
    while queue:
        name = queue.pop(0)
        key = re.sub(r"[-_.]+", "-", name).lower()
        if key in seen:
            continue
        seen.add(key)
        dist = metadata.distribution(name)
        folder = destination / f"{key}-{dist.version}"
        folder.mkdir(parents=True, exist_ok=True)
        files = []
        for path in dist.files or []:
            filename = path.name.lower()
            if (filename.startswith(("license", "licence", "copying", "notice", "authors"))
                    or filename == "metadata"):
                source = Path(dist.locate_file(path))
                if source.is_file():
                    relative = Path(*[part for part in path.parts if part not in ("..", ".")])
                    target = folder / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    files.append(str(target.relative_to(destination)))
        records.append({
            "name": dist.metadata.get("Name", name),
            "version": dist.version,
            "license_expression": dist.metadata.get("License-Expression"),
            "license": dist.metadata.get("License"),
            "project_urls": dist.metadata.get_all("Project-URL") or [],
            "notices": sorted(files),
        })
        for raw_requirement in dist.requires or []:
            requirement = Requirement(raw_requirement)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                queue.append(requirement.name)

    # Python's own copyright and bundled-module licenses are part of the runtime.
    runtime_license = Path(sys.base_prefix) / "LICENSE.txt"
    if runtime_license.is_file():
        shutil.copyfile(runtime_license, destination / "PYTHON-LICENSE.txt")
    (destination / "DEPENDENCIES.json").write_text(
        json.dumps(sorted(records, key=lambda item: item["name"].lower()),
                   indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (destination / "PYTHON-VERSION.txt").write_text(sys.version + "\n", encoding="utf-8")
    return records


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("build/licenses")
    records = collect(target)
    print(f"Collected {len(records)} dependency records into {target}")

