"""A fresh checkout must resume the included site without private databases or new builds."""
import json

import pytest
from fastapi.testclient import TestClient

from se_team.office.import_project import import_website
from se_team.office.server import create_app
from se_team.office.store import Store
from tests.test_flow_smoke import make_dummy_spec


def included_website(tmp_path):
    source = tmp_path/'websites/BurningUpp'
    (source/'frontend').mkdir(parents=True)
    (source/'backend').mkdir()
    (source/'frontend/index.html').write_text('<h1>Existing site</h1>')
    (source/'backend/main.py').write_text('from fastapi import FastAPI\napp=FastAPI()\n')
    (source/'project-spec.json').write_text(make_dummy_spec('existing project').model_dump_json())
    return source


def test_import_uses_same_source_and_spec_without_queuing_model_work(tmp_path):
    source=included_website(tmp_path)
    store=Store(tmp_path/'workspace/office')
    project=import_website(store,source)
    assert store.project_dir(project['id'])==source
    assert project['spec_json'] is not None
    assert store.claim_command() is None
    snapshot=store.snapshot(project['id'])
    assert snapshot['revisions'][0]['status']=='needs_attention'
    assert snapshot['revisions'][0]['qa'] is None
    assert (source/'frontend/index.html').read_text()=='<h1>Existing site</h1>'
    assert not (tmp_path/'websites/BurningUpp-2').exists()


def test_import_is_idempotent_and_preserves_local_spec_chat_and_data(tmp_path):
    source=included_website(tmp_path)
    store=Store(tmp_path/'workspace/office')
    project=import_website(store,source)
    updated=make_dummy_spec('latest local requirement').model_dump_json()
    store.set_spec(project['id'],updated)
    store.message(project['id'],'user','my local conversation')
    (source/'data').mkdir();(source/'data/user.sqlite3').write_bytes(b'existing local data')
    before=store.snapshot(project['id'])
    again=import_website(store,source)
    assert again['id']==project['id'] and again['spec_json']==updated
    assert store.snapshot(project['id'])==before
    assert (source/'data/user.sqlite3').read_bytes()==b'existing local data'


def test_import_requires_valid_source_inside_websites(tmp_path):
    source=included_website(tmp_path)
    store=Store(tmp_path/'other')
    with pytest.raises(ValueError,match='directly inside'):
        import_website(store,source)
    store=Store(tmp_path/'workspace/office')
    (source/'project-spec.json').write_text('{}')
    with pytest.raises(ValueError):
        import_website(store,source)
    assert store.rows('SELECT * FROM projects')==[]


def test_imported_site_is_browsable_and_previewable_from_fresh_office(tmp_path,monkeypatch):
    source=included_website(tmp_path)
    app=create_app(tmp_path/'workspace/office',start_worker=False)
    project=import_website(app.state.store,source)
    monkeypatch.setattr(app.state.preview,'start',lambda pid,rid,path:{'running':True,'url':'http://127.0.0.1:12345/','source':str(path)})
    with TestClient(app) as client:
        boot=client.get('/office-api/bootstrap').json()
        assert boot['projects'][0]['id']==project['id']
        base=f"/office-api/projects/{project['id']}"
        assert client.get(base+'/file',params={'path':'frontend/index.html'}).json()['content']=='<h1>Existing site</h1>'
        response=client.post(base+'/preview',json={},headers={'X-Office-Token':boot['token']})
        assert response.status_code==200 and response.json()['source']==str(source)
