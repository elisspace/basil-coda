"""Resolve the shared portable configuration before engine globals bind.

The JSON CLI is a nonsecret bridge for the standalone Node DOM helper. It does
not inspect credentials, create state directories, contact services or start work.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from portable_config import load

CONFIG = load()
CONFIG.apply()

if __name__ == '__main__':
    print(json.dumps({key: str(value) for key, value in vars(CONFIG).items()}))
