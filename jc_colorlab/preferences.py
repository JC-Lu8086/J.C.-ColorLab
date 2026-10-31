"""Non-image user preferences. Copyright 2026 J.C. Lu. MIT."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

LANGUAGES = ('zh-CN', 'en', 'fr', 'ja', 'de', 'ru')


def preference_path():
    override = os.environ.get('JC_COLORLAB_PREFERENCES')
    if override:
        return Path(override)
    if sys.platform == 'darwin':
        root = Path.home() / 'Library' / 'Application Support'
    elif sys.platform == 'win32':
        root = Path(os.environ.get('APPDATA', str(Path.home() / 'AppData' / 'Roaming')))
    else:
        root = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
    return root / 'JC ColorLab' / 'preferences.json'


def read_language(path):
    if path is None:
        return None
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8')).get('language')
        return value if value in LANGUAGES else None
    except (OSError, ValueError, AttributeError):
        return None


def save_language(path, language):
    if language not in LANGUAGES:
        raise ValueError('Unsupported language')
    if path is None:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'language': language}), encoding='utf-8')
    temporary.replace(path)
