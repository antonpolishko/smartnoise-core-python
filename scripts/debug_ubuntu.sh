#!/usr/bin/env bash
set -e

# fixes matplotlib plotting bug on ubuntu
export QT_XKB_CONFIG_ROOT=/usr/share/X11/xkb

# enables full stack traces
export RUST_BACKTRACE=1

# reset all the files
bash scripts/clean.sh

# regenerate the sources for the package
python3 scripts/code_generation.py |& tee scripts/debug_build.log

# (re)installs the python package
python3 -m pip install -e . -v

# run tests
#python3 -m pytest -x -v |& tee debug_tests.log

# run a test application
python3 scripts/app.py |& tee scripts/debug_app.log

exit
