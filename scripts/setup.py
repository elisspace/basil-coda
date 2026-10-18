#!/usr/bin/env python3
"""Offline, non-activating Basil installer. Copies only public source allowlist."""
import argparse
import json
from pathlib import Path
import shutil
import sys

SOURCE = Path(__file__).resolve().parents[1]
FILES = ('server.py', 'history.py', 'volume.py', 'portable_config.py', 'diagnostics.py',
         'basil.py', 'persona.md', 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md')
TREES = ('engine', 'web', 'docs', 'scripts', 'deploy')
TREE_SUFFIXES = {
    'engine': {'.py', '.mjs'},
    'web': {'.html', '.css', '.js', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.ico', '.woff2'},
    'docs': {'.md'},
    'deploy': {'.service', '.toml'},
}


def public_source(path, tree):
    if '__pycache__' in path.parts or 'fixtures' in path.parts or path.name.startswith('test_'):
        return False
    if tree == 'scripts':
        return path.name in ('setup.py', 'hermes-dj-player')
    if tree == 'deploy':
        return path.name in ('basil-coda.service', 'config.example.toml')
    return not path.name.startswith('.') and path.suffix in TREE_SUFFIXES[tree]


def quote_unit(value):
    # ExecStart ':' suppresses dollar expansion; percent specifiers still escape.
    value = str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    return '"' + value + '"'


def install(prefix):
    prefix = prefix.expanduser().resolve()
    if '\\' in str(prefix) or any(ord(char) < 32 or ord(char) == 127 for char in str(prefix)):
        raise ValueError('Unsupported prefix: backslashes and control characters cannot be represented safely in the generated service')
    destination = prefix/'share/basil-coda'
    launcher = prefix/'bin/basil-coda'
    config = prefix/'etc/basil-coda/config.toml'
    unit = prefix/'share/basil-coda.service'
    for path in (destination, launcher, config, unit):
        if path.exists() or path.is_symlink():
            raise ValueError('Refusing to overwrite existing installation: ' + str(path))
    # Check all source inputs before making directories.
    for name in FILES + TREES:
        if not (SOURCE/name).exists():
            raise ValueError('Incomplete release: missing ' + name)
    selected = [SOURCE/name for name in FILES]
    for tree in TREES:
        selected.extend(p for p in (SOURCE/tree).rglob('*') if p.is_file() and public_source(p, tree))
    for source in selected:
        if source.is_symlink() or not source.resolve().is_relative_to(SOURCE):
            raise ValueError('Release contains a source symlink; refuse to copy: ' + str(source))
        if source.suffix in ('.sqlite', '.db', '.log') or source.name in ('player-client.json', 'session.json', 'web-chat.json', '.env'):
            raise ValueError('Private runtime file found in release input: ' + str(source))
    for source in selected:
        target = destination/source.relative_to(SOURCE)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('# Public configuration only; never put tokens or credentials here.\n[basil]\n'
                      '# Paths default to the invoking user HOME, not the installer account.\n'
                      'hermes_profile = "dj"\nhermes_bin = "hermes"\nplayer_executable = ""\n'
                      'rest_url = "http://127.0.0.1:26538"\ncdp_url = "http://127.0.0.1:26539"\n')
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text('#!/usr/bin/env python3\nimport os, sys\n'
                        'os.environ.setdefault("BASIL_CONFIG", ' + repr(str(config)) + ')\n'
                        'os.execv(' + repr(sys.executable) + ', [' + repr(sys.executable) + ', "-B", '
                        + repr(str(destination/'basil.py')) + '] + sys.argv[1:])\n')
    launcher.chmod(0o755)
    unit.write_text('[Unit]\nDescription=Basil Coda loopback listening room\nAfter=network.target\n\n'
                    '[Service]\nType=simple\nUMask=0077\nWorkingDirectory=' + str(destination).replace('%', '%%') + '\n'
                    'ExecStart=:' + quote_unit(launcher) + ' serve\nRestart=on-failure\nRestartSec=3\n'
                    'Environment=PYTHONDONTWRITEBYTECODE=1\n\n[Install]\nWantedBy=default.target\n')
    print(json.dumps({'installed': str(destination), 'launcher': str(launcher), 'config': str(config),
                      'service_example': str(unit), 'activated': False,
                      'note': 'No services/profile/player/credentials installed or started. Run basil-coda doctor.'}, indent=2))


def main():
    if sys.version_info < (3, 11):
        raise SystemExit('Python >=3.11 required')
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    setup = sub.add_parser('install')
    setup.add_argument('--prefix', type=Path, default=Path.home()/'.local')
    args = parser.parse_args()
    try:
        install(args.prefix)
    except (OSError, ValueError) as error:
        parser.exit(1, str(error)+'\n')


if __name__ == '__main__':
    main()
