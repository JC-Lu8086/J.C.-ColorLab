#!/bin/zsh
set -eu
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  if ! python3 -c 'import sys; assert (3, 11) <= sys.version_info[:2] < (3, 15)' 2>/dev/null; then
    print "JC ColorLab requires Python 3.11–3.14. Install Python 3.12 or use the standalone .app."
    read -r "reply?Press Return to close. "
    exit 1
  fi
  python3 -m venv .venv
  .venv/bin/python -m pip install .
fi
.venv/bin/python -m jc_colorlab

