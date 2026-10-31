"""Assemble an explicitly untested Windows x64 portable distribution.

Uses the official embeddable Python runtime and binary wheels. This is not
cross-compilation and must not be mistaken for a Windows execution test.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
import urllib.request
import zipfile

PYTHON_VERSION = '3.14.10'
PYTHON_URL = 'https://www.python.org/ftp/python/3.14.10/python-3.14.10-embed-amd64.zip'
PYTHON_SHA256 = '90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159'


def extract(archive, destination):
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            output = (destination / item.filename).resolve()
            if not output.is_relative_to(destination.resolve()):
                raise ValueError('Archive contains a path outside its destination')
        z.extractall(destination)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',type=Path,default=Path('build/windows-downloads'))
    parser.add_argument('--output',type=Path,default=Path('dist/JC-ColorLab-Windows-x64-experimental'))
    parser.add_argument('--offline',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    version=tomllib.loads((root/'pyproject.toml').read_text())['project']['version']
    cache=args.cache.resolve();destination=args.output.resolve()
    if destination.exists():
        raise SystemExit('Output folder already exists; choose a new output folder.')
    cache.mkdir(parents=True,exist_ok=True)
    python_zip=cache / f'python-{PYTHON_VERSION}-embed-amd64.zip'
    wheel_dir=cache / 'wheels';wheel_dir.mkdir(exist_ok=True)
    if not args.offline:
        if not python_zip.exists():
            urllib.request.urlretrieve(PYTHON_URL,python_zip)
        dependencies=tomllib.loads((root/'pyproject.toml').read_text())['project']['dependencies']
        subprocess.run([sys.executable,'-m','pip','download','--only-binary=:all:','--platform','win_amd64','--python-version','314','--implementation','cp','--abi','cp314','--dest',str(wheel_dir),*dependencies,'colorama>=0.4.6'],check=True)
    if hashlib.sha256(python_zip.read_bytes()).hexdigest()!=PYTHON_SHA256:
        raise ValueError('Official Python runtime SHA-256 mismatch')
    wheels=sorted(wheel_dir.glob('*.whl'))
    if len(wheels)<14:
        raise ValueError('Incomplete Windows dependency set')
    runtime=destination/'runtime';runtime.mkdir(parents=True)
    extract(python_zip,runtime)
    site=runtime/'Lib'/'site-packages';site.mkdir(parents=True)
    manifest={'application_version':version,'platform':'Windows x64','status':'assembled on macOS; execution NOT tested','python':{'version':PYTHON_VERSION,'url':PYTHON_URL,'sha256':PYTHON_SHA256},'wheels':[]}
    for wheel in wheels:
        extract(wheel,site)
        manifest['wheels'].append({'file':wheel.name,'sha256':hashlib.sha256(wheel.read_bytes()).hexdigest()})
    # Wheel .data purelib/platlib files belong directly in site-packages.
    for data in site.glob('*.data'):
        for category in ('purelib','platlib'):
            folder=data/category
            if folder.exists():
                shutil.copytree(folder,site,dirs_exist_ok=True)
    # rawpy's LibRaw imports the standard VC++ runtime basename. NumPy's
    # wheel includes the same runtime with a delvewheel-generated suffix.
    # Keep its existing copy and supply the standard name beside python.exe.
    vc_runtime = sorted((site/'numpy.libs').glob('msvcp140-*.dll'))
    if len(vc_runtime) != 1:
        raise ValueError('Expected one NumPy-supplied MSVCP140 runtime')
    shutil.copy2(vc_runtime[0],runtime/'MSVCP140.dll')
    manifest['runtime_aliases'] = [{'source':str(vc_runtime[0].relative_to(destination)),
        'destination':'runtime/MSVCP140.dll',
        'sha256':hashlib.sha256(vc_runtime[0].read_bytes()).hexdigest(),
        'reason':'LibRaw imports the standard MSVCP140.dll basename'}]
    (runtime/'python314._pth').write_text('python314.zip\n.\nLib/site-packages\n../app\nimport site\n')
    shutil.copytree(root/'jc_colorlab',destination/'app'/'jc_colorlab',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ('README.md','LICENSE','THIRD_PARTY_NOTICES.md','CHANGELOG.md'):
        shutil.copy2(root/name,destination/name)
    shutil.copytree(root/'docs',destination/'docs')
    (destination/'Start-JC-ColorLab.cmd').write_bytes(b'@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\n"runtime\\python.exe" -m jc_colorlab\r\nif errorlevel 1 pause\r\n')
    (destination/'BUILD-MANIFEST.json').write_text(json.dumps(manifest,indent=2))
    (destination/'WINDOWS-READ-ME.txt').write_text(f'JC ColorLab v{version} — Windows x64 EXPERIMENTAL\n\nExtract the entire folder, then double-click Start-JC-ColorLab.cmd.\nPython and dependencies are included; normal operation is offline.\nDo not move Start-JC-ColorLab.cmd away from runtime/ and app/.\n\nThis package was assembled on macOS and has NOT been run on Windows.\nJ.C. Lu currently owns only a Mac and cannot test or maintain Windows.\nClose the local service using the Exit button in the web interface.\nAll third-party licenses remain in runtime/ and app/jc_colorlab/native/.\n',encoding='utf-8')
    print(f'Assembled untested Windows portable package: {destination}')


if __name__=='__main__':
    main()
