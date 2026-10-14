"""Verify the HTTP boundary forwards only the explicitly supported selection."""
import io
import json
from types import SimpleNamespace

import pytest
import web_console


@pytest.mark.parametrize('manual', [False, True])
def test_apply_http_forwards_optional_config_path(monkeypatch, manual):
    payload = {'x': 1, 'y': 2, 'yaw': .3, 'source_map_id':'a'*16,'request_id':'manual-http-test'}
    if manual:
        payload['config_path'] = '/opt/ry/config/localization/floor.yaml'
    encoded = json.dumps(payload).encode()
    calls = []
    responses = []
    handler = object.__new__(web_console.ConsoleHandler)
    handler.headers = {'Content-Length': str(len(encoded))}
    handler.rfile = io.BytesIO(encoded)
    handler._json = lambda body, *args: responses.append((body, args))
    monkeypatch.setattr(web_console, 'SETTINGS', SimpleNamespace(load=lambda: object()))
    monkeypatch.setattr(web_console, 'MANUAL_RELOCALIZATION', SimpleNamespace(
        apply=lambda settings, pose: calls.append(pose) or {'phase': 'calling_service'}))
    handler._observation_action('/api/observation/relocalization/apply')
    assert calls == [payload]
    assert responses[0][0]['phase'] == 'calling_service'


def test_apply_http_rejects_raw_ros_map_path(monkeypatch):
    payload = {'x': 1, 'y': 2, 'yaw': 0, 'map_path': '/private.yaml'}
    encoded = json.dumps(payload).encode()
    handler = object.__new__(web_console.ConsoleHandler)
    handler.headers = {'Content-Length': str(len(encoded))}
    handler.rfile = io.BytesIO(encoded)
    responses = []
    handler._json = lambda body, status=200: responses.append((body, status))
    monkeypatch.setattr(web_console, 'SETTINGS', SimpleNamespace(load=lambda: object()))
    handler._observation_action('/api/observation/relocalization/apply')
    assert responses[0][1] == 400
    assert '不支持的字段' in responses[0][0]['error']


@pytest.mark.parametrize('payload', [{'request_id':'lost'}, {'request_id':'lost','x':1}, {}])
def test_resolve_http_only_forwards_the_request_identifier(monkeypatch,payload):
    encoded=json.dumps(payload).encode();calls=[];responses=[]
    handler=object.__new__(web_console.ConsoleHandler)
    handler.headers={'Content-Length':str(len(encoded))};handler.rfile=io.BytesIO(encoded)
    handler._json=lambda body,status=200:responses.append((body,status))
    monkeypatch.setattr(web_console,'SETTINGS',SimpleNamespace(load=lambda:object()))
    monkeypatch.setattr(web_console,'MANUAL_RELOCALIZATION',SimpleNamespace(
        resolve_operation=lambda request_id:calls.append(request_id) or {'operation_outcome':'not_admitted'}))
    handler._observation_action('/api/observation/relocalization/resolve')
    assert calls==(['lost'] if set(payload)=={'request_id'} else [])
    assert responses[0][1]==(200 if calls else 400)


def test_get_request_outcome_uses_specific_history_not_latest_status(monkeypatch):
    handler=object.__new__(web_console.ConsoleHandler)
    handler.path='/api/observation/relocalization?request_id=previous-request'
    handler.headers={};responses=[];calls=[]
    handler._json=lambda body,*args:responses.append(body)
    monkeypatch.setattr(web_console,'MANUAL_RELOCALIZATION',SimpleNamespace(
        operation_status=lambda request_id:calls.append(request_id) or {'operation_id':request_id,'operation_outcome':'failed'},
        status=lambda *_:pytest.fail('request-specific query must not return another operation')))
    handler.do_GET()
    assert calls==['previous-request']
    assert responses==[{'operation_id':'previous-request','operation_outcome':'failed'}]
