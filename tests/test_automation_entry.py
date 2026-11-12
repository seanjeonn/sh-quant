"""OFFLINE SYNTHETIC profile/entry fixtures, never model/API jobs."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]

class AutomationEntry(unittest.TestCase):
    def fixture(self, td):
        template = ROOT / 'hermes/templates/automation_entry.py'
        self.assertTrue(template.is_file(), 'guarded active-profile cron entry missing')
        home = Path(td).resolve() / 'profiles/investops'
        home.mkdir(parents=True, mode=0o700)
        scripts = home / 'scripts'; scripts.mkdir(mode=0o700)
        private = home / 'private'; private.mkdir(mode=0o700)
        confdir = private / 'automation'; confdir.mkdir(mode=0o700)
        repo = home / 'workspaces/sh-quant-automation'
        tools = repo / 'tools'; tools.mkdir(parents=True)
        module = tools / 'automation_supervisor.py'
        module.write_text("import os,sys\nassert sys.argv[-2:]==['--mode','canary']\nassert os.environ['HERMES_HOME'].endswith('/profiles/investops')\nprint('SYNTHETIC_ENTRY_OK')\n")
        module.chmod(0o644)
        config = confdir / 'config.json'
        config.write_text(json.dumps({'profile_home':str(home),'repo':str(repo),'supervisor_sha256':hashlib.sha256(module.read_bytes()).hexdigest()}))
        config.chmod(0o600)
        entry = scripts / 'investops-canary.py'; entry.write_bytes(template.read_bytes()); entry.chmod(0o600)
        return home, entry, module, config

    def invoke(self, home, entry, extra=None):
        env = dict(os.environ, HERMES_HOME=str(home));env.update(extra or {})
        return subprocess.run([sys.executable, '-B', str(entry)], env=env, capture_output=True,text=True, timeout=10)

    def test_valid_entry_executes_only_pinned_module(self):
        with tempfile.TemporaryDirectory() as td:
            home,entry,_,_=self.fixture(td)
            result=self.invoke(home,entry)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(result.stdout.strip(),'SYNTHETIC_ENTRY_OK')

    def test_other_profile_or_module_drift_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            home,entry,module,_=self.fixture(td)
            result=self.invoke(home,entry,{'HERMES_HOME':str(home.parent/'default')})
            self.assertNotEqual(result.returncode,0)
            self.assertNotIn('SYNTHETIC_ENTRY_OK',result.stdout)
            module.write_text("print('SYNTHETIC_ENTRY_OK')\n")
            result=self.invoke(home,entry)
            self.assertNotEqual(result.returncode,0)
            self.assertNotIn('SYNTHETIC_ENTRY_OK',result.stdout)

    def test_unsafe_permissions_and_entry_alias_are_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            home,entry,_,config=self.fixture(td)
            config.chmod(0o644)
            self.assertNotEqual(self.invoke(home,entry).returncode,0)
            config.chmod(0o600)
            alias=entry.with_name('investops-unknown.py');alias.write_bytes(entry.read_bytes());alias.chmod(0o600)
            self.assertNotEqual(self.invoke(home,alias).returncode,0)

if __name__=='__main__':unittest.main()
