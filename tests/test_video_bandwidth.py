"""Gateway-byte accounting uses real loopback HTTP and observable log output."""
import json
import threading
import time
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from autodrive_console.video_bandwidth import VideoBandwidthMonitor


@pytest.fixture
def gateway():
    state = SimpleNamespace(items=[], sources=[], source_status=200, source_trickle=None, source_pages=None, page_count=1, status=200, malformed=False, queries=[], pages=None, trickle=None, started=threading.Event())
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state.queries.append(self.path)
            page = int(parse_qs(urlparse(self.path).query).get('page',['0'])[0])
            is_source = urlparse(self.path).path == '/v3/paths/list'
            items = (state.source_pages[page] if state.source_pages is not None else state.sources) if is_source else (state.pages[page] if state.pages is not None else state.items)
            payload = {'items':items, 'pageCount':(len(state.source_pages) if state.source_pages is not None else 1) if is_source else state.page_count, 'itemCount':len(items)}
            body = b'not JSON' if state.malformed else json.dumps(payload).encode()
            phase = state.source_trickle if is_source else state.trickle
            state.started.set()
            if phase == 'headers':
                header = f'HTTP/1.0 {state.status} OK\r\nContent-Length: {len(body)}\r\n\r\n'.encode()
                try:
                    for value in header:
                        self.wfile.write(bytes([value])); self.wfile.flush(); time.sleep(.03)
                except (OSError, ValueError): return
                try: self.wfile.write(body)
                except OSError: pass
                return
            self.send_response(state.source_status if is_source else state.status)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                if phase == 'body':
                    for value in body:
                        self.wfile.write(bytes([value])); self.wfile.flush(); time.sleep(.03)
                else: self.wfile.write(body)
            except OSError: pass
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval':.01}, daemon=True)
    thread.start()
    state.url = f'http://127.0.0.1:{server.server_port}/v3/paths/list'
    try: yield state
    finally: server.shutdown(); thread.join(2); server.server_close()


def session(identifier, path, size, *, legacy=False):
    item = {'id':identifier, 'path':path, 'state':'read', 'peerConnectionEstablished':True,
            'remoteAddr':'192.168.1.8:1234', 'localCandidate':'host/udp/127.0.0.1/8189',
            'remoteCandidate':'host/udp/192.168.1.8/55555', 'bytesSent':size,
            'bytesReceived':100, 'outboundRTPPackets':10, 'outboundRTCPPackets':1}
    if not legacy: item['outboundBytes'] = size
    return item


def monitor(gateway):
    clock = [0.0]
    result = VideoBandwidthMonitor(gateway.url, [{'name':'front_camera','path':'front'},
        {'name':'detection_camera','path':'detect'}], clock=lambda:clock[0])
    return result, clock


def test_byte_deltas_sum_multiple_viewers_and_ignore_unowned_streams(gateway, capsys):
    m, clock = monitor(gateway)
    gateway.items = [session('a','front',1000000), session('b','front',9000000,legacy=True),
                     session('c','detect',300000), session('other','unowned',999999999)]
    assert m.sample_once()['state'] == 'warming'
    clock[0] = 5
    gateway.items = [session('a','front',1500000), session('b','front',9500000,legacy=True),
                     session('c','detect',550000), session('other','unowned',9999999999)]
    data = m.sample_once()
    assert data['total_mbps'] == pytest.approx(2.0)
    assert data['connections'] == 3
    assert data['streams']['front_camera']['mbps'] == 1.6
    assert data['streams']['front_camera']['connections'] == 2
    assert data['streams']['detection_camera']['mbps'] == .4
    assert data['streams']['detection_camera']['connections'] == 1
    output = capsys.readouterr().out
    assert '2.000 Mbps' in output and 'front_camera=1.600' in output
    assert '网关' in output and '192.168.1.8' not in output
    assert {urlparse(q).path for q in gateway.queries} == {'/v3/webrtcsessions/list', '/v3/paths/list'}


def test_new_session_or_counter_reset_never_becomes_a_large_bandwidth_spike(gateway):
    m, clock = monitor(gateway)
    gateway.items = [session('a','front',1000000)]
    m.sample_once(); clock[0] = 5
    gateway.items = [session('a','front',100)]
    assert m.sample_once()['total_mbps'] is None
    clock[0] = 10; gateway.items = [session('a','front',500100)]
    assert m.sample_once()['total_mbps'] == pytest.approx(.8)
    clock[0] = 15; gateway.items = [session('replacement','front',9000000000)]
    assert m.sample_once()['total_mbps'] is None
    clock[0] = 20; gateway.items = [session('replacement','front',9000500000)]
    assert m.sample_once()['total_mbps'] == pytest.approx(.8)


def test_active_logging_is_periodic_and_idle_logging_is_not_repeated(gateway, capsys):
    m, clock = monitor(gateway)
    m.sample_once(); capsys.readouterr()
    for n in range(1,9): clock[0]=n*5; m.sample_once()
    assert capsys.readouterr().out == ''
    gateway.items=[session('a','front',0)]; m.sample_once(); capsys.readouterr()
    clock[0]=45; gateway.items=[session('a','front',625000)]; m.sample_once()
    assert '1.000 Mbps' in capsys.readouterr().out
    for n in range(10,15):
        clock[0]=n*5; gateway.items=[session('a','front',(n-8)*625000)]; m.sample_once()
    assert capsys.readouterr().out == ''
    clock[0]=75; gateway.items=[session('a','front',4375000)]; m.sample_once()
    assert '1.000 Mbps' in capsys.readouterr().out
    clock[0]=80; gateway.items=[]; assert m.sample_once()['total_mbps']==0
    assert '0.000 Mbps' in capsys.readouterr().out


@pytest.mark.parametrize('failure',['http','json','counter','counter_large','path','overflow','duplicate'])
def test_bad_statistics_are_unavailable_not_a_false_zero_and_recover(gateway, capsys, failure):
    m, clock = monitor(gateway)
    gateway.items=[session('a','front',100)]
    m.sample_once(); capsys.readouterr()
    if failure=='http': gateway.status=503
    elif failure=='json': gateway.malformed=True
    elif failure=='counter': gateway.items[0]['outboundBytes']=-1
    elif failure=='counter_large': gateway.items[0]['outboundBytes']=2**1024
    elif failure=='path': gateway.items[0]['path']={}
    elif failure=='overflow': gateway.page_count=999
    elif failure=='duplicate': gateway.items*=2
    clock[0]=5
    assert m.sample_once()['state']=='unavailable'
    assert '暂不可用' in capsys.readouterr().out
    clock[0]=10; m.sample_once()
    assert capsys.readouterr().out==''
    gateway.status=200; gateway.malformed=False; gateway.page_count=1
    gateway.items=[session('a','front',99999999)]; clock[0]=15
    assert m.sample_once()['state']=='warming'
    gateway.items=[session('a','front',100624999)]; clock[0]=20
    assert m.sample_once()['total_mbps']==pytest.approx(1.0)


def test_sampling_thread_stops_without_leaking_or_duplicate_workers(gateway):
    m, _ = monitor(gateway)
    m.start(); first=m.thread; m.start()
    try:
        assert m.thread is first
        assert first.is_alive()
    finally: m.stop()
    assert not first.is_alive()


def test_multiple_pages_account_for_all_viewers(gateway):
    m, clock=monitor(gateway)
    gateway.page_count=2
    gateway.pages=[[session(str(i),'front',1000000) for i in range(100)], [session('last','front',1000000)]]
    m.sample_once();clock[0]=5
    gateway.pages=[[session(str(i),'front',1006250) for i in range(100)], [session('last','front',1006250)]]
    data=m.sample_once()
    assert data['connections']==101
    assert data['total_mbps']==pytest.approx(1.01)


@pytest.mark.parametrize('phase',['headers','body'])
def test_statistics_request_has_a_total_deadline_even_if_bytes_keep_arriving(gateway, phase):
    m, _ = monitor(gateway);gateway.trickle=phase
    before=time.monotonic();data=m.sample_once()
    assert data['state']=='unavailable'
    assert time.monotonic()-before<1


def test_stopping_interrupts_an_active_statistics_read(gateway):
    m, _=monitor(gateway);gateway.trickle='body'
    m.start()
    try:
        assert gateway.started.wait(1)
        m.stop()
        assert not m.thread.is_alive()
    finally:m.stop()


def test_statistics_thread_resource_failure_is_nonfatal(gateway):
    m, _=monitor(gateway)
    with patch('autodrive_console.video_bandwidth.threading.Thread.start',side_effect=RuntimeError('cannot start thread')):
        assert m.start() is False
    m.stop()  # A never-started thread must not raise during video teardown.


def test_bandwidth_is_visible_in_structured_tool_logs_and_runtime_stdout(gateway, tmp_path, capsys):
    import logging
    from autodrive_console.tool_logging import ToolLogStore
    root = logging.getLogger('ry_aletheia')
    with patch.object(root, 'handlers', []):
        store=ToolLogStore(tmp_path/'logs');store.configure()
        try:
            m,clock=monitor(gateway)
            gateway.items=[session('a','front',0)];m.sample_once()
            clock[0]=5;gateway.items=[session('a','front',625000)];m.sample_once()
            entry=store.entries()[0]
            assert entry['source']=='video'
            assert entry['level']=='INFO'
            assert '1.000 Mbps' in entry['message']
            assert entry['message'] in capsys.readouterr().out
        finally:
            for handler in root.handlers:handler.close()


def source(identifier, path, size, *, legacy=False, online=True):
    item = {'name':path, 'ready':online, 'source':{'type':'rtspSession', 'id':identifier},
            'readyTime':'2026-10-15T12:00:00Z', 'bytesReceived':size}
    if not legacy: item['inboundBytes'] = size
    return item


def test_encoded_input_is_viewer_weighted_before_comparing_transport(gateway, capsys):
    m, clock=monitor(gateway)
    gateway.items=[session('a','front',0),session('b','front',0),session('c','detect',0)]
    gateway.sources=[source('pub1','front',0),source('pub2','detect',0,legacy=True)]
    assert m.sample_once()['expected_mbps'] is None
    clock[0]=5
    gateway.sources=[source('pub1','front',625000),source('pub2','detect',312500,legacy=True)]
    gateway.items=[session('a','front',656250),session('b','front',656250),session('c','detect',328125)]
    data=m.sample_once()
    assert data['encoded_mbps']==pytest.approx(1.5)
    assert data['expected_mbps']==pytest.approx(2.5)
    assert data['send_ratio']==pytest.approx(1.05)
    assert data['streams']['front_camera']['encoded_mbps']==pytest.approx(1)
    assert data['streams']['front_camera']['expected_mbps']==pytest.approx(2)
    output=capsys.readouterr().out
    assert '编码输入=1.500 Mbps' in output and '发送倍率=1.05' in output


@pytest.mark.parametrize('change',['publisher','counter','epoch','unready','missing','http','invalid'])
def test_source_discontinuity_is_unknown_without_losing_session_rate(gateway, change):
    m,clock=monitor(gateway)
    gateway.items=[session('a','front',0)]
    gateway.sources=[source('pub','front',1000000)]
    m.sample_once();clock[0]=5
    gateway.items=[session('a','front',625000)]
    gateway.sources=[source('pub','front',1625000)]
    assert m.sample_once()['send_ratio']==pytest.approx(1)
    clock[0]=10;gateway.items=[session('a','front',1250000)]
    gateway.sources=[source('pub','front',2250000)]
    if change=='publisher':gateway.sources[0]['source']['id']='newpub'
    elif change=='counter':gateway.sources[0]['inboundBytes']=1
    elif change=='epoch':gateway.sources[0]['readyTime']='new epoch'
    elif change=='unready':gateway.sources[0]['ready']=False
    elif change=='missing':gateway.sources=[]
    elif change=='http':gateway.source_status=503
    elif change=='invalid':gateway.sources[0]['inboundBytes']=True
    data=m.sample_once()
    assert data['state']=='active' and data['total_mbps']==pytest.approx(1)
    assert data['expected_mbps'] is None and data['send_ratio'] is None
    assert data['streams']['front_camera']['encoded_mbps'] is None


def test_transport_amplification_logs_transition_without_waiting_thirty_seconds(gateway,capsys):
    m,clock=monitor(gateway)
    gateway.items=[session('a','front',0)];gateway.sources=[source('pub','front',0)]
    m.sample_once();clock[0]=5
    gateway.items=[session('a','front',625000)];gateway.sources=[source('pub','front',625000)]
    m.sample_once();capsys.readouterr()
    clock[0]=10;gateway.items=[session('a','front',6875000)];gateway.sources=[source('pub','front',1250000)]
    data=m.sample_once()
    assert data['send_ratio']==pytest.approx(10)
    output=capsys.readouterr().out
    assert '发送量明显高于源输入' in output and '不等同于重传率' in output
    clock[0]=15;gateway.items=[session('a','front',13125000)];gateway.sources=[source('pub','front',1875000)]
    m.sample_once();assert capsys.readouterr().out==''


def test_source_failure_recovery_requires_two_fresh_source_snapshots(gateway):
    m,clock=monitor(gateway)
    gateway.items=[session('a','front',0)];gateway.sources=[source('pub','front',0)]
    m.sample_once();clock[0]=5;gateway.items=[session('a','front',625000)];gateway.source_status=503
    assert m.sample_once()['send_ratio'] is None
    clock[0]=10;gateway.items=[session('a','front',1250000)];gateway.source_status=200
    gateway.sources=[source('pub','front',100000000)]
    assert m.sample_once()['send_ratio'] is None
    clock[0]=15;gateway.items=[session('a','front',1875000)];gateway.sources=[source('pub','front',100625000)]
    assert m.sample_once()['send_ratio']==pytest.approx(1)


def test_partial_source_warmup_does_not_claim_complete_encoded_total(gateway):
    m,clock=monitor(gateway)
    gateway.items=[session('a','front',0)]
    gateway.sources=[source('p','front',0),source('q','detect',0)]
    m.sample_once();clock[0]=5;gateway.items=[session('a','front',625000)]
    gateway.sources=[source('p','front',625000),source('new','detect',100000000)]
    data=m.sample_once()
    assert data['encoded_mbps'] is None
    assert data['streams']['front_camera']['encoded_mbps']==pytest.approx(1)
    assert data['send_ratio']==pytest.approx(1)  # Unwatched warm source does not invalidate the watched comparison.


@pytest.mark.parametrize('phase',['headers','body'])
def test_source_request_deadline_preserves_transport_sample(gateway,phase):
    m,clock=monitor(gateway)
    gateway.items=[session('a','front',0)];m.sample_once();clock[0]=5
    gateway.items=[session('a','front',625000)];gateway.source_trickle=phase
    before=time.monotonic();data=m.sample_once()
    assert time.monotonic()-before<1
    assert data['total_mbps']==pytest.approx(1) and data['send_ratio'] is None


def test_source_pagination_counts_only_owned_publishers(gateway):
    m,clock=monitor(gateway)
    gateway.source_pages=[[source(str(i),'unowned'+str(i),0) for i in range(100)], [source('p','front',0)]]
    gateway.items=[session('a','front',0)];m.sample_once();clock[0]=5
    gateway.items=[session('a','front',625000)];gateway.source_pages[-1]=[source('p','front',625000)]
    assert m.sample_once()['send_ratio']==pytest.approx(1)
    assert any('/paths/list?' in q and 'page=1' in q for q in gateway.queries)


@pytest.mark.parametrize('change',['missing','unready'])
def test_source_disappearance_does_not_turn_partial_sum_into_encoded_total(gateway,change):
    m,clock=monitor(gateway)
    gateway.items=[session('a','front',0)]
    gateway.sources=[source('p','front',0),source('q','detect',0)]
    m.sample_once();clock[0]=5;gateway.items=[session('a','front',625000)]
    gateway.sources=[source('p','front',625000),source('q','detect',625000,online=False)]
    if change=='missing':gateway.sources.pop()
    data=m.sample_once()
    assert data['encoded_mbps'] is None
    assert data['streams']['front_camera']['encoded_mbps']==pytest.approx(1)


def test_misaligned_source_window_cannot_report_transport_amplification(gateway,capsys):
    m,clock=monitor(gateway)
    gateway.items=[session('a','front',0)];gateway.sources=[source('p','front',0)]
    original=m._read_items
    def read(endpoint):
        if endpoint.endswith('/paths/list') and clock[0]==0:
            clock[0]=.4
            gateway.sources=[source('p','front',1200000)]
        return original(endpoint)
    with patch.object(m,'_read_items',side_effect=read):m.sample_once()
    capsys.readouterr();clock[0]=5.4
    gateway.items=[session('a','front',1250000)];gateway.sources=[source('p','front',1250000)]
    data=m.sample_once()
    assert data['total_mbps']>0 and data['streams']['front_camera']['encoded_mbps']>0
    assert data['send_ratio'] is None and data['expected_mbps'] is None
    assert '发送量明显高于源输入' not in capsys.readouterr().out
