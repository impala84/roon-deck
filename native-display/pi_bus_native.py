#!/usr/bin/env python3
"""Old entry point, kept for one release.

The display now starts from roondeck_native.py. An installed updater from before
that rename still expects this file to exist, so it starts the new program.
Remove this file once every device is running a release that names the new file.
"""
import os
import sys
from pathlib import Path

target = Path(__file__).resolve().with_name("roondeck_native.py")
os.execv(sys.executable, [sys.executable, str(target), *sys.argv[1:]])
