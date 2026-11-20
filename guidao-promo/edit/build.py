#!/usr/bin/env python3
"""One-click build: render frames, encode, validate."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

subprocess.run([sys.executable, 'edit/render.py'], check=True)
subprocess.run(['bash', 'edit/encode.sh'], check=True)
subprocess.run([sys.executable, 'edit/validate.py'], check=True)
