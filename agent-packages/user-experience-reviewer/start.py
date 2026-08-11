#!/usr/bin/env python3
import os, sys
from pathlib import Path
here = Path(__file__).resolve().parent
server = here / "scripts" / "standalone_server.py"
if not server.is_file(): server = here.parent / "_shared" / "standalone_server.py"
os.execv(sys.executable, [sys.executable, str(server), "--package-dir", str(here), *sys.argv[1:]])

