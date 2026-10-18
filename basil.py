#!/usr/bin/env python3
"""Basil CLI: serving/doctor are safe; player launch requires explicit command."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit
from portable_config import load


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    serve = sub.add_parser('serve')
    serve.add_argument('--port', type=int, default=8847)
    doctor = sub.add_parser('doctor')
    doctor.add_argument('--probe', action='store_true')
    sub.add_parser('player', help='Explicitly open the configured dedicated Pear player; may start media')
    args = parser.parse_args()
    config = load()
    config.apply()
    if args.command == 'doctor':
        from diagnostics import report
        import json
        print(json.dumps(report(config, probe=args.probe), indent=2))
    elif args.command == 'serve':
        os.execv(sys.executable, [sys.executable, '-B', str(Path(__file__).with_name('server.py')), '--port', str(args.port)])
    else:
        import shutil
        player = shutil.which(config.player_executable) if config.player_executable else None
        if not player:
            parser.error('Set player_executable to an independently installed Pear Desktop executable first')
        # Config controls executable only; never accept flags that override loopback/data isolation.
        os.execv(player, [player, '--user-data-dir='+str(config.player_data_dir),
                         '--remote-debugging-address=127.0.0.1',
                         '--remote-debugging-port='+str(urlsplit(config.cdp_url).port)])


if __name__ == '__main__':
    main()
