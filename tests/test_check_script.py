"""The handoff checker supports slower CI CPUs without changing agent deadlines."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest


def load_checker():
    path=Path(__file__).resolve().parents[1]/'scripts/check.py'
    spec=importlib.util.spec_from_file_location('handoff_checker',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_website_test_deadline_is_configurable(tmp_path,monkeypatch):
    from se_team.tools.sandbox import SandboxManager
    checker=load_checker()
    monkeypatch.setattr(checker,'ROOT',tmp_path)
    monkeypatch.setattr('sys.argv',['check.py','--website','--website-timeout','180'])
    def run(box,path,timeout):
        assert path=='tests' and timeout==180
        return {'output':'','passed':True,'tests_passed':1,'tests_executed':1}
    monkeypatch.setattr(SandboxManager,'run_tests',run)
    with patch.dict("os.environ"):
        assert checker.main()==0


def test_checker_rejects_nonpositive_deadline(monkeypatch):
    checker=load_checker()
    monkeypatch.setattr('sys.argv',['check.py','--website-timeout','0'])
    with pytest.raises(SystemExit) as result:
        checker.main()
    assert result.value.code==2
