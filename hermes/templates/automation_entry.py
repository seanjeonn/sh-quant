#!/usr/bin/env python3
"""Copy as an allowlisted investops-<mode>.py under the active profile scripts.
No credentials, quotes, model output or arbitrary command is handled here.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

MODES = {'investops-canary.py': 'canary', 'investops-daily.py': 'daily',
         'investops-continue.py': 'continue', 'investops-weekly.py': 'weekly',
         'investops-deadline.py': 'deadline'}


def regular(path, private=False):
    for p in [path, *path.parents]:
        if p.is_symlink():
            raise ValueError()
    s = path.stat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or s.st_nlink != 1:
        raise ValueError()
    bad_mode = stat.S_IMODE(s.st_mode) != 0o600 if private else bool(s.st_mode & 0o022)
    if bad_mode:
        raise ValueError()


def main():
    entry = Path(__file__).absolute()
    mode = MODES[entry.name]
    home = entry.parent.parent
    if entry.parent.name != 'scripts' or home.name != 'investops' or home.parent.name != 'profiles':
        raise ValueError()
    given = os.environ.get('HERMES_HOME')
    if given and Path(given) != home:
        raise ValueError()
    regular(entry, private=True)
    config_path = home / 'private/automation/config.json'
    for directory in (home, entry.parent, home/'private', config_path.parent):
        s=directory.stat()
        if directory.is_symlink() or not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode)!=0o700:
            raise ValueError()
    regular(config_path, private=True)
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:raise ValueError()
            result[k]=v
        return result
    config=json.loads(config_path.read_text(),object_pairs_hook=pairs)
    repo=home/'workspaces/sh-quant-automation'
    if config['profile_home']!=str(home) or config['repo']!=str(repo):
        raise ValueError()
    module=repo/'tools/automation_supervisor.py'
    regular(module)
    if hashlib.sha256(module.read_bytes()).hexdigest()!=config['supervisor_sha256']:
        raise ValueError()
    env=dict(os.environ,HERMES_HOME=str(home),TZ='Asia/Seoul')
    os.execve(sys.executable,[sys.executable,'-B',str(module),'--config',str(config_path),'--mode',mode],env)


if __name__=='__main__':
    try:
        main()
    except Exception:
        print('investops automation blocked: entry integrity/profile check failed')
        raise SystemExit(1)
