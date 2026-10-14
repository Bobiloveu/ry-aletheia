from __future__ import annotations

import io
import json
import struct
import zlib
from email.message import Message
from unittest.mock import Mock, patch

import pytest
import web_console


class ProjectionApi:
    def __init__(self):
        self.calls = []

    def latest(self, project):
        return {"id": "projection-demo", "project_id": project, "state": "ready", "revision": 3}

    def get(self, project, job):
        self.calls.append(("get", project, job))
        return self.latest(project)

    def create(self, project, source):
        self.calls.append(("create", project, source.name, source.read_bytes()))
        return {**self.latest(project), "state": "analyzing"}

    def preview(self, project, job, params):
        self.calls.append(("preview", project, job, params))
        return {**self.latest(project), "state": "processing"}

    def confirm(self, project, job, label, revision):
        self.calls.append(("confirm", project, job, label, revision))
        return {"id": "map-example"}

    def cancel(self, project, job):
        self.calls.append(("cancel", project, job))
        return {**self.latest(project), "state": "cancelled"}

    def preview_path(self, project, job, revision):
        self.calls.append(("image", project, job, revision))
        return self.image

    def source_preview(self, project, job):
        self.calls.append(("source", project, job))
        return struct.pack("<fff", -0.125, 0.25, 0.5), {
            "point_count": 1, "source_point_count": 20, "finite_point_count": 18,
            "origin": [1000000000.125, -2, 3], "bounds": [[1000000000, 1000000000.25], [-3, -1], [2, 4]]}


def handler(path, payload=None):
    item = object.__new__(web_console.ConsoleHandler)
    item.path = path
    item.headers = Message()
    item.headers["User-Agent"] = "test"
    item._json = Mock()
    item.send_error = Mock()
    item.send_response = Mock()
    item.send_header = Mock()
    item.end_headers = Mock()
    item.wfile = io.BytesIO()
    if payload is not None:
        body = json.dumps(payload).encode()
        item.headers["Content-Length"] = str(len(body))
        item.rfile = io.BytesIO(body)
    return item


def test_projection_http_restores_job_and_routes_actions_without_robot_calls():
    api = ProjectionApi()
    prefix = "/api/deployments/site-demo/map-projections"
    store = Mock()
    store.get.return_value = {"id": "site-demo"}
    with patch.object(web_console, "MAP_PROJECTIONS", api, create=True), patch.object(web_console, "DEPLOYMENTS", store):
        item = handler(prefix + "/latest")
        item.do_GET()
        assert item._json.call_args.args[0] == {"projection": api.latest("site-demo")}
        item = handler(prefix + "/projection-demo/preview", {"z_min": 0.2, "z_max": 1.5, "resolution": 0.05, "min_points": 1, "denoise": False})
        item.do_POST()
        assert item._json.call_args.args[1] == 202
        assert api.calls[-1][0] == "preview"
        item = handler(prefix + "/projection-demo/confirm", {"label": "大厅", "revision": 3})
        item.do_POST()
        assert item._json.call_args.args == ({"map": {"id": "map-example"}, "project": {"id": "site-demo"}}, 201)
        item = handler(prefix + "/projection-demo")
        item.do_DELETE()
        assert api.calls[-1] == ("cancel", "site-demo", "projection-demo")


def test_projection_http_rejects_non_objects_extra_confirm_fields_and_large_json():
    prefix = "/api/deployments/site-demo/map-projections/projection-demo/confirm"
    api = ProjectionApi()
    with patch.object(web_console, "MAP_PROJECTIONS", api, create=True):
        for payload in [[], {"label": "大厅", "revision": 3, "source": "/etc/passwd"}, {"label": "x" * 20000, "revision": 3}]:
            item = handler(prefix, payload)
            item.do_POST()
            assert item._json.call_args.args[1] == 400
    assert api.calls == []


def test_projection_upload_copies_exactly_one_pcd_and_rejects_other_files(tmp_path):
    api = ProjectionApi()
    store = Mock(root=tmp_path)
    prefix = "/api/deployments/site-demo/map-projections"
    with patch.object(web_console, "MAP_PROJECTIONS", api, create=True), patch.object(web_console, "DEPLOYMENTS", store):
        for filename, expected_status in [("大厅.pcd", 202), ("../outside.pcd", 400), ("map.yaml", 400)]:
            body = (f'--pcd-boundary\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode() + b"pcd fixture\r\n--pcd-boundary--\r\n"
            item = handler(prefix)
            item.headers["Content-Type"] = "multipart/form-data; boundary=pcd-boundary"
            item.headers["Content-Length"] = str(len(body))
            item.rfile = io.BytesIO(body)
            item.do_POST()
            assert item._json.call_args.args[1] == expected_status
    assert api.calls == [("create", "site-demo", "大厅.pcd", b"pcd fixture")]


def test_trajectory_upload_returns_bounded_xy_without_creating_projection(tmp_path):
    api = Mock()
    api.trajectory_preview.return_value = (struct.pack('<ff', .1, .2),
        {'point_count': 1, 'origin': [10,20], 'format':'xy-v1'})
    store = Mock(root=tmp_path)
    prefix = '/api/deployments/site-demo/map-projections/projection-demo/trajectory-preview.bin'
    body = b'--pcd\r\nContent-Disposition: form-data; name="file"; filename="track.pcd"\r\n\r\nPCD\r\n--pcd--\r\n'
    with patch.object(web_console, 'MAP_PROJECTIONS', api), patch.object(web_console, 'DEPLOYMENTS', store):
        item = handler(prefix)
        item.headers['Content-Type'] = 'multipart/form-data; boundary=pcd'
        item.headers['Content-Length'] = str(len(body))
        item.rfile = io.BytesIO(body)
        item.do_POST()
        assert item.wfile.getvalue() == struct.pack('<ff', .1, .2)
        assert ('X-Point-Format','xy-v1') in [c.args for c in item.send_header.call_args_list]
        api.create.assert_not_called()
        item = handler(prefix + '?unexpected=1')
        item.do_POST()
        assert item._json.call_args.args[1] == 400


def test_projection_png_requires_explicit_revision_and_uses_no_store(tmp_path):
    api = ProjectionApi()
    api.image = tmp_path / "map.pgm"
    api.image.write_bytes(b"P5\n2 1\n255\n\x00\xff")
    prefix = "/api/deployments/site-demo/map-projections/projection-demo/preview.png"
    with patch.object(web_console, "MAP_PROJECTIONS", api, create=True):
        item = handler(prefix)
        item.do_GET()
        assert item._json.call_args.args[1] == 400
        item = handler(prefix + "?revision=3")
        item.do_GET()
        assert api.calls[-1] == ("image", "site-demo", "projection-demo", 3)
        assert item.wfile.getvalue().startswith(b"\x89PNG")
        assert ("Cache-Control", "no-store") in [call.args for call in item.send_header.call_args_list]


def png_rows(body):
    offset, compressed = 8, b""
    while offset < len(body):
        length = struct.unpack_from(">I", body, offset)[0]
        kind = body[offset + 4:offset + 8]
        if kind == b"IDAT":
            compressed += body[offset + 8:offset + 8 + length]
        offset += length + 12
    return zlib.decompress(compressed)


def test_projection_monochrome_is_display_only_and_preserves_default_and_pgm(tmp_path):
    api = ProjectionApi()
    api.image = tmp_path / "map.pgm"
    original = b"P5\n4 1\n255\n\x00\xcd\xfe\xff"
    api.image.write_bytes(original)
    prefix = "/api/deployments/site-demo/map-projections/projection-demo/preview.png?revision=3"
    with patch.object(web_console, "MAP_PROJECTIONS", api):
        default = handler(prefix)
        default.do_GET()
        assert png_rows(default.wfile.getvalue()) == b"\x00\x00\xcd\xfe\xff"
        mono = handler(prefix + "&display=monochrome")
        mono.do_GET()
        assert png_rows(mono.wfile.getvalue()) == b"\x00\x00\xff\xff\xff"
        assert api.image.read_bytes() == original
        assert ("Cache-Control", "no-store") in [call.args for call in mono.send_header.call_args_list]


@pytest.mark.parametrize('query', ['revision=3&display=unknown', 'revision=3&display=',
    'revision=3&display=monochrome&display=monochrome', 'revision=3&other=1',
    'revision=3&revision=3', 'revision=3&display', 'revision=3&='])
def test_projection_image_rejects_unknown_duplicate_or_blank_query(query, tmp_path):
    api = ProjectionApi()
    api.image = tmp_path / 'map.pgm'
    api.image.write_bytes(b'P5\n1 1\n255\n\x00')
    with patch.object(web_console, 'MAP_PROJECTIONS', api):
        item = handler('/api/deployments/site-demo/map-projections/projection-demo/preview.png?' + query)
        item.do_GET()
        assert item._json.call_args is not None and item._json.call_args.args[1] == 400
    assert api.calls == []


def test_source_preview_route_returns_binary_sample_metadata_and_no_store():
    api = ProjectionApi()
    with patch.object(web_console, 'MAP_PROJECTIONS', api):
        item = handler('/api/deployments/site-demo/map-projections/projection-demo/source-preview.bin')
        item.do_GET()
    assert api.calls == [('source', 'site-demo', 'projection-demo')]
    assert item.wfile.getvalue() == struct.pack('<fff', -0.125, 0.25, 0.5)
    headers = dict(call.args for call in item.send_header.call_args_list)
    assert headers['Content-Type'] == 'application/octet-stream'
    assert headers['Cache-Control'] == 'no-store'
    assert headers['Content-Length'] == '12'
    assert headers['X-Point-Count'] == '1'
    assert headers['X-Source-Point-Count'] == '20'
    assert headers['X-Finite-Point-Count'] == '18'
    assert json.loads(headers['X-Point-Origin']) == [1000000000.125, -2, 3]
    assert json.loads(headers['X-Point-Bounds']) == [[1000000000, 1000000000.25], [-3, -1], [2, 4]]


def test_source_preview_rejects_query_before_reading_sample():
    api = ProjectionApi()
    with patch.object(web_console, 'MAP_PROJECTIONS', api):
        item = handler('/api/deployments/site-demo/map-projections/projection-demo/source-preview.bin?path=/etc/passwd')
        item.do_GET()
    assert item._json.call_args.args[1] == 400
    assert api.calls == []


@pytest.mark.parametrize('error,status', [(web_console.MapProjectionError('请重新上传 PCD'), 400),
    (web_console.MapProjectionConflict('尚未完成'), 409)])
def test_source_preview_reports_domain_errors(error, status):
    api = ProjectionApi()
    api.source_preview = Mock(side_effect=error)
    with patch.object(web_console, 'MAP_PROJECTIONS', api):
        item = handler('/api/deployments/site-demo/map-projections/projection-demo/source-preview.bin')
        item.do_GET()
    assert item._json.call_args.args == ({'error': str(error)}, status)


def test_detail_route_returns_preparing_without_blocking_then_color_wire_headers():
    api = ProjectionApi()
    api.source_detail = Mock(return_value=None)
    path = '/api/deployments/site-demo/map-projections/projection-demo/source-detail.bin'
    with patch.object(web_console, 'MAP_PROJECTIONS', api):
        pending = handler(path)
        pending.do_GET()
        assert pending._json.call_args.args == ({'state': 'preparing'}, web_console.HTTPStatus.ACCEPTED)
        metadata = api.source_preview('site-demo','projection-demo')[1]
        metadata.update(format='xyz-rgba-intensity-v1', attributes={'rgb': True, 'intensity': False, 'intensity_range': None, 'display_bounds': metadata['bounds']})
        body = struct.pack('<fffBBBBf',0,0,0,255,30,20,255,float('nan'))
        api.source_detail.return_value = body, metadata
        ready = handler(path)
        ready.do_GET()
    headers = dict(call.args for call in ready.send_header.call_args_list)
    assert ready.wfile.getvalue() == body
    assert headers['X-Point-Format'] == 'xyz-rgba-intensity-v1'
    assert json.loads(headers['X-Point-Attributes'])['rgb'] is True
