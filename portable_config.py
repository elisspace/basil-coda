"""Read-only portable configuration. No credentials, mkdir, network or startup.

BASIL_CONFIG selects a TOML file with a [basil] table. BASIL_* environment
variables override it. Paths are absolute after expansion; executables are
single argv entries, never shell fragments.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import tomllib
from urllib.parse import urlsplit


def loopback_url(value):
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        port = None
    if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not port or
            parsed.username is not None or parsed.password is not None or
            parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('Endpoint must be loopback http://127.0.0.1:PORT without credentials or path')
    return f'http://127.0.0.1:{port}'


@dataclass(frozen=True)
class Config:
    state_dir: Path
    hermes_home: Path
    hermes_profile: str
    hermes_bin: str
    player_executable: str
    player_data_dir: Path
    rest_url: str
    cdp_url: str
    worker_unit: str

    @property
    def profile_dir(self):
        return self.hermes_home / 'profiles' / self.hermes_profile

    @property
    def skill(self):
        return self.profile_dir / 'skills/youtube-music-dj/SKILL.md'

    def apply(self):
        """Export resolved values before engine imports and for helper children."""
        for key, value in vars(self).items():
            os.environ['BASIL_' + key.upper()] = str(value)
        # Hermes CLI interprets HERMES_HOME as its active home, not a base path;
        # let its supported -p option resolve the named profile from the base.
        os.environ['HERMES_HOME'] = str(self.hermes_home)


def load():
    values = {}
    if os.environ.get('BASIL_CONFIG'):
        with Path(os.environ['BASIL_CONFIG']).expanduser().open('rb') as source:
            values = tomllib.load(source).get('basil', {})
        if not isinstance(values, dict):
            raise ValueError('Expected [basil] configuration table')
    defaults = {
        'state_dir': Path.home()/'.local/share/basil-coda/state',
        'hermes_home': Path.home()/'.hermes', 'hermes_profile': 'dj',
        'hermes_bin': 'hermes', 'player_executable': '',
        'player_data_dir': Path.home()/'.local/share/basil-coda/player',
        'rest_url': 'http://127.0.0.1:26538', 'cdp_url': 'http://127.0.0.1:26539',
        'worker_unit': 'hermes-dj-session',
    }
    unknown = set(values) - set(defaults)
    if unknown:
        raise ValueError('Unknown Basil configuration keys: ' + ', '.join(sorted(unknown)))
    for key, default in defaults.items():
        value = os.environ.get('BASIL_' + key.upper(), values.get(key, default))
        if not isinstance(value, (str, Path)) or '\x00' in str(value) or '\n' in str(value) or '\r' in str(value):
            raise ValueError('Configuration values must be single-line strings')
        if key.endswith('_dir') or key == 'hermes_home':
            value = Path(value).expanduser().resolve()
        defaults[key] = value
    for key in ('rest_url', 'cdp_url'):
        defaults[key] = loopback_url(defaults[key])
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', defaults['hermes_profile']):
        raise ValueError('Invalid Hermes profile name')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', defaults['worker_unit']):
        raise ValueError('Invalid worker unit name')
    return Config(**defaults)
