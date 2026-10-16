"""Low-frequency, local gateway accounting; never touches video pixels or peers."""
from __future__ import annotations

import json
import http.client
import socket
import logging
import threading
import time
from urllib.parse import urlsplit

LOGGER = logging.getLogger('ry_aletheia.video')


class VideoBandwidthMonitor:
    SAMPLE_SECONDS = 5.0
    LOG_SECONDS = 30.0
    # Diagnostic time alignment only, never a media/control gate. At a normal
    # 5 s sample, allow at most 50 ms request uncertainty or endpoint skew.
    MAX_WINDOW_SKEW_FRACTION = .01

    def __init__(self, api_url, streams, *, clock=time.monotonic):
        # api_url and streams come only from VideoManager's validated config.
        self.url = api_url.removesuffix('/paths/list') + '/webrtcsessions/list'
        parsed = urlsplit(self.url)
        self._host, self._port, self._endpoint = parsed.hostname, parsed.port, parsed.path
        self._source_endpoint = urlsplit(api_url).path
        self._socket = None
        self._socket_lock = threading.Lock()
        self.paths = {stream['path']: stream['name'] for stream in streams}
        self.clock = clock
        self.thread = None
        self._stop = threading.Event()
        self._previous = None
        self._previous_sources = None
        self._last_signature = None
        self._last_logged_at = 0.0

    @staticmethod
    def _shutdown(sock):
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _read_page(self, page, endpoint):
        connection = http.client.HTTPConnection(self._host, self._port, timeout=.5)
        deadline = time.monotonic() + .5
        watchdog = sock = None
        try:
            connection.connect()
            sock = connection.sock
            with self._socket_lock:
                self._socket = sock
            if self._stop.is_set():
                raise InterruptedError('统计已停止')
            # Socket idle timeouts alone do not bound slow headers or bodies.
            # Interrupt this exact socket at the absolute deadline, without
            # touching any media socket or retaining a detached request worker.
            watchdog = threading.Timer(max(0, deadline - time.monotonic()), self._shutdown, args=(sock,))
            watchdog.daemon = True
            watchdog.start()
            connection.request('GET', f'{endpoint}?itemsPerPage=100&page={page}', headers={'Accept':'application/json'})
            with connection.getresponse() as response:
                if response.status != 200:
                    raise ValueError('网关统计状态无效')
                body = response.read(512 * 1024 + 1)
            if time.monotonic() >= deadline:
                raise TimeoutError('统计请求超过总期限')
            if len(body) > 512 * 1024:
                raise ValueError('统计响应超限')
            return json.loads(body)
        finally:
            if watchdog is not None:
                watchdog.cancel()
            connection.close()
            with self._socket_lock:
                if self._socket is sock:
                    self._socket = None

    def _read_items(self, endpoint):
        result = []
        page, pages = 0, 1
        while page < pages and not self._stop.is_set():
            document = self._read_page(page, endpoint)
            if not isinstance(document, dict) or not isinstance(document.get('items'), list):
                raise ValueError('统计响应无效')
            pages = document.get('pageCount', 1)
            if type(pages) is not int or not 0 <= pages <= 8:
                raise ValueError('统计分页超限')
            if len(document['items']) > 100 or pages == 0 and document['items']:
                raise ValueError('统计分页无效')
            if any(not isinstance(item, dict) for item in document['items']):
                raise ValueError('统计条目无效')
            result.extend(document['items'])
            page += 1
        return result

    def _read_sessions(self):
        result = {}
        for item in self._read_items(self._endpoint):
            if not isinstance(item.get('path'), str):
                raise ValueError('会话路径无效')
            if item['path'] not in self.paths or item.get('state') != 'read':
                continue
            identifier, counter = item.get('id'), item.get('outboundBytes', item.get('bytesSent'))
            if not isinstance(identifier, str) or not identifier or identifier in result:
                raise ValueError('会话身份无效')
            if type(counter) is not int or not 0 <= counter <= 2**64 - 1:
                raise ValueError('会话计数无效')
            result[identifier] = (self.paths[item['path']], counter)
        return result

    def _source_rates(self):
        rates = dict.fromkeys(self.paths.values())
        total = window = None
        started = self.clock()
        try:
            current = {}
            seen = set()
            for item in self._read_items(self._source_endpoint):
                path = item.get('name')
                if not isinstance(path, str):
                    raise ValueError('源路径无效')
                if path not in self.paths:
                    continue
                if path in seen:
                    raise ValueError('源路径重复')
                seen.add(path)
                if item.get('online', item.get('ready')) is not True:
                    continue
                source = item.get('source')
                if not isinstance(source, dict) or not isinstance(source.get('id'), str) or not source['id']:
                    raise ValueError('源身份无效')
                epoch = item.get('onlineTime', item.get('readyTime'))
                if not isinstance(epoch, str) or not epoch:
                    raise ValueError('源上线时间无效')
                counter = item.get('inboundBytes', item.get('bytesReceived'))
                if type(counter) is not int or not 0 <= counter <= 2**64 - 1:
                    raise ValueError('源计数无效')
                current[self.paths[path]] = ((source['id'], epoch), counter)
            now = self.clock()
            if self._previous_sources is not None:
                before, previous, previous_started = self._previous_sources
                elapsed = now - before
                if elapsed > 0:
                    window = (previous_started, before, started, now)
                    for name, (identity, counter) in current.items():
                        old = previous.get(name)
                        if old is not None and identity == old[0] and counter >= old[1]:
                            rates[name] = (counter - old[1]) * 8 / elapsed / 1_000_000
            self._previous_sources = (now, current, started)
            if rates and all(value is not None for value in rates.values()):
                total = sum(rates.values())
        except (OSError, http.client.HTTPException, ValueError, UnicodeDecodeError, RuntimeError):
            # Keep the transport sample valid, but never bridge a source gap.
            self._previous_sources = None
        return rates, total, window

    @classmethod
    def _windows_aligned(cls, transport, source):
        if transport is None or source is None:
            return False
        tolerance = min(transport[3] - transport[1], source[3] - source[1]) * cls.MAX_WINDOW_SKEW_FRACTION
        return tolerance > 0 and all(abs(a - b) <= tolerance for a, b in zip(transport, source)) and all(
            window[1] - window[0] <= tolerance and window[3] - window[2] <= tolerance
            for window in (transport, source))

    def sample_once(self):
        started = self.clock()
        try:
            current = self._read_sessions()
        except (OSError, http.client.HTTPException, ValueError, UnicodeDecodeError, RuntimeError):
            self._previous = None
            self._previous_sources = None
            if not self._stop.is_set():
                self._report({'state':'unavailable', 'connections':None}, self.clock())
            return {'state':'unavailable', 'total_mbps':None}
        if self._stop.is_set():
            return {'state':'stopped', 'total_mbps':None}
        now = self.clock()
        counts = {name:0 for name in self.paths.values()}
        for name, _ in current.values(): counts[name] += 1
        rates = {name:None for name in counts}
        state, elapsed, transport_window = 'warming', None, None
        if not current:
            state = 'idle'
            rates = dict.fromkeys(counts, 0.0)
        elif self._previous is not None:
            before, previous, previous_started = self._previous
            elapsed = now - before
            compatible = current.keys() == previous.keys() and all(
                name == previous[key][0] and count >= previous[key][1]
                for key, (name, count) in current.items())
            if compatible and elapsed > 0:
                state = 'active'
                transport_window = (previous_started, before, started, now)
                rates = dict.fromkeys(counts, 0.0)
                for key, (name, count) in current.items():
                    rates[name] += (count - previous[key][1]) * 8 / elapsed / 1_000_000
        self._previous = (now, current, started)
        source_rates, encoded_total, source_window = self._source_rates()
        if self._stop.is_set():
            return {'state':'stopped', 'total_mbps':None}
        aligned = self._windows_aligned(transport_window, source_window)
        expected = {name: (source_rates[name] * count if source_rates[name] is not None and aligned else None)
                    if count else 0.0 for name, count in counts.items()}
        expected_total = sum(expected.values()) if state in {'idle', 'active'} and all(
            value is not None for value in expected.values()) else None
        total = sum(rates.values()) if state in {'idle','active'} else None
        ratio = total / expected_total if expected_total and total is not None else None
        data = {'state':state, 'interval_seconds':elapsed, 'connections':len(current),
                'total_mbps':total,
                'encoded_mbps':encoded_total,
                'expected_mbps':expected_total, 'send_ratio':ratio,
                'streams':{name:{'mbps':rates[name], 'connections':count, 'encoded_mbps':source_rates[name],
                                 'expected_mbps':expected[name]} for name,count in counts.items()}}
        self._report(data, now)
        return data

    def _report(self, data, now):
        amplified = (data.get('send_ratio') is not None and data['send_ratio'] >= 2 and
                     data['total_mbps'] - data['expected_mbps'] >= .5)
        signature = (data['state'], data['connections'], tuple(
            (name, row['connections']) for name,row in data.get('streams', {}).items()),
            data.get('send_ratio') is not None, amplified)
        if signature == self._last_signature and (data['state'] != 'active' or now - self._last_logged_at < self.LOG_SECONDS):
            return
        self._last_signature, self._last_logged_at = signature, now
        if data['state'] == 'unavailable':
            message = '视频带宽统计暂不可用：本机网关计数读取失败；不影响视频播放，恢复后重新采样'
            LOGGER.warning(message)
        elif data['state'] == 'warming':
            message = f"视频带宽（网关统计）：连接数={data['connections']}；连接或计数变化，正在建立采样基线"
            LOGGER.info(message)
        else:
            def metric(value, unit):
                return '未知' if value is None else f'{value:.3f} {unit}'
            details = ', '.join(f"{name}={row['mbps']:.3f} Mbps/{row['connections']}连接"
                                f"（编码={metric(row['encoded_mbps'], 'Mbps')}）"
                                for name,row in data['streams'].items())
            window = f"最近{data['interval_seconds']:.1f}秒" if data['state']=='active' else '无人观看'
            message = (f"视频带宽（网关统计）：总发送={data['total_mbps']:.3f} Mbps "
                       f"({data['total_mbps']/8:.3f} MB/s)，连接数={data['connections']}，{window}；{details}；"
                       '不含IP/以太网/Wi-Fi额外开销')
            message += (f"；编码输入={metric(data['encoded_mbps'], 'Mbps')}"
                        f"，按观看数折算={metric(data['expected_mbps'], 'Mbps')}"
                        f"，发送倍率={'未知' if data['send_ratio'] is None else format(data['send_ratio'], '.2f')}"
                        '（近似窗口、不同层级计数，不等同于重传率）')
            if amplified:
                message += '；发送量明显高于源输入，需对照编码输出与传输统计'
                LOGGER.warning(message)
            else:
                LOGGER.info(message)
        print(message, flush=True)  # The runner's existing stdout is video-runtime.log.

    def start(self):
        if self.thread is not None and self.thread.is_alive():
            return True
        self._stop.clear()
        self._previous = None
        self._previous_sources = None
        self._last_signature = None
        def run():
            while not self._stop.is_set():
                self.sample_once()
                self._stop.wait(self.SAMPLE_SECONDS)
        try:
            self.thread = threading.Thread(target=run, name='video-bandwidth', daemon=True)
            self.thread.start()
        except (RuntimeError, OSError):
            self.thread = None
            self._report({'state':'unavailable', 'connections':None}, self.clock())
            return False
        return True

    def stop(self):
        self._stop.set()
        with self._socket_lock:
            self._shutdown(self._socket)
        if self.thread is not None and self.thread.ident is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=1)
