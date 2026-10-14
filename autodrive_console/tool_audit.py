"""Bounded diagnostic records at tool operation boundaries, never robot data."""
from __future__ import annotations

import contextvars
import functools
import logging
import re
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from urllib.parse import urlsplit


REQUEST_CONTEXT = contextvars.ContextVar("tool_request_context", default={})
CONTEXT_FIELDS = ("request_id", "event", "method", "path", "operation", "status", "duration_ms")
_HTTP_LOG = logging.getLogger("ry_aletheia.http")
_BROWSER_LOG = logging.getLogger("ry_aletheia.browser")


def safe_message(value: object, *, limit: int = 1200) -> str:
    """Retain diagnostic text while removing URL credentials and common secrets."""
    text = str(value)
    def clean_url(match):
        try:
            url = urlsplit(match.group(0))
            host = url.netloc.rsplit("@", 1)[-1]
            return f"{url.scheme}://{host}{url.path}"
        except ValueError:
            return "[URL]"
    text = re.sub(r"\b(?:https?|wss?|rtsps?|mqtts?)://[^\s<>\"']+", clean_url, text, flags=re.I)
    text = re.sub(r"(?<!\w)(/[^\s?<>\"']*)\?[^\s<>\"']*", r"\1", text)
    text = re.sub(r"\bBearer\s+[^\s,;]+", "Bearer [redacted]", text, flags=re.I)
    text = re.sub(r"\b(password|passwd|token|secret|authorization|cookie|api[_-]?key)[\"']?\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)", r"\1=[redacted]", text, flags=re.I)
    text = re.sub(r"\b(?:data|blob):[^\s<>\"']+", "[resource]", text, flags=re.I)
    # TimeoutExpired repr includes the complete argv, including supervisorctl
    # -p credentials. Preserve the timeout/error, never serialize the command.
    text = re.sub(r"\bCommand\s+.*(?= (?:timed out after [0-9.]+ seconds|returned non-zero exit status \d+))", "Command [redacted]", text, flags=re.S)
    text = re.sub(r"\bCommand\s+(?:\[[^\]]*\]|'[^']*'|\"[^\"]*\")", "Command [redacted]", text)
    return text[:limit]


def inject_client_diagnostics(body: bytes) -> bytes:
    script = b'<script src="/platform/client-diagnostics.js"></script>'
    if b'src="/platform/client-diagnostics.js"' in body:
        return body
    return re.sub(br"(<head(?:\s[^>]*)?>)", lambda m: m.group(1) + script, body, count=1, flags=re.I)


def _feature(path: str) -> str:
    for prefix, label in (
        ("/api/system/upgrade", "软件升级"),
        ("/api/deployment-component-defaults", "部署组件默认参数"),
        ("/api/deployments", "部署地图与任务线路"), ("/api/mapping", "建图"),
        ("/api/vehicle-control", "手动控制"), ("/api/vehicle-execution-status", "车辆执行状态"),
        ("/api/observation", "实时观测与地图导航"), ("/api/video", "视频"),
        ("/api/acceptance", "部署验收"), ("/api/runs", "测试执行"),
        ("/api/cases", "用例管理"), ("/api/reports", "报告"),
        ("/api/bag-recordings", "诊断录包"), ("/api/robot-logs", "机器人日志"),
        ("/api/tool-logs", "工具日志"), ("/api/software-inventory", "软件资产"),
        ("/api/scenario-setup", "场景方案"), ("/api/settings", "运行配置"),
        ("/api/autostart", "开机启动"), ("/api/upgrade", "软件升级"),
        ("/api/supervisor", "进程管理"), ("/api/system", "工具生命周期"),
        ("/api/report-files/", "报告查看"),
        ("/report-files/", "报告查看"), ("/reports/", "报告导出"),
    ):
        if path.startswith(prefix):
            return label
    return "工具接口"


class _OutcomeGate:
    """Remember only bounded endpoint state; emit first error, repeats, recovery."""
    def __init__(self, interval=30.0, capacity=1024):
        self.interval, self.capacity = interval, capacity
        self._states = OrderedDict()
        self._lock = threading.Lock()

    def admit(self, key, outcome, now):
        with self._lock:
            previous = self._states.pop(key, None)
            changed = previous is None or previous[0] != outcome
            recovered = previous is not None and previous[0] != "ok" and outcome == "ok"
            emit = changed or now - previous[1] >= self.interval
            last = now if emit else previous[1]
            self._states[key] = (outcome, last)
            while len(self._states) > self.capacity:
                self._states.popitem(last=False)
            return emit, recovered


_OUTCOMES = _OutcomeGate()
_QUIET_POSTS = {
    "/api/observation/client-log", "/api/observation/client-metrics", "/api/observation/live-layers", "/api/observation/heartbeat",
    "/api/vehicle-control/heartbeat", "/api/vehicle-control/vector", "/api/vehicle-control/command",
}


class HttpAudit:
    def __init__(self, method: str, path: str):
        self.method = method
        self.path = urlsplit(path).path[:480]
        self.request_id = uuid.uuid4().hex[:12]
        self.operation = _feature(self.path)
        self.started = time.monotonic()
        self.status = 200
        self.reason = ""
        self.warning = ""
        self.summary = ""
        self.interrupted = False
        self.is_api = self.path.startswith("/api/")
        self.is_client_event = self.path == "/api/tool-logs/client-events"
        self.write = self.is_api and method in {"POST", "PUT", "PATCH", "DELETE"} and self.path not in _QUIET_POSTS and not self.is_client_event
        self.read_action = method == "GET" and (
            self.path.endswith(("/download", "/export", "/report", "/task-compiler/preview", "/topology", "/tail"))
            or self.path.startswith(("/report-files/", "/reports/"))
            or self.path.startswith("/api/report-files/")
            or self.path.startswith("/api/robot-logs/downloads/") and self.path.endswith("/file")
            or re.fullmatch(r"/api/reports/[^/]+/native", self.path) is not None
            or self.path in {"/api/scenario-setup/file", "/api/scenario-setup/browse", "/api/observation/relocalization/configs"}
        )

    @contextmanager
    def context(self):
        token = REQUEST_CONTEXT.set({"request_id": self.request_id, "method": self.method, "path": self.path, "operation": self.operation})
        try:
            yield
        finally:
            REQUEST_CONTEXT.reset(token)

    def _extra(self, event):
        return {**REQUEST_CONTEXT.get(), "request_id": self.request_id, "method": self.method, "path": self.path,
                "operation": self.operation, "event": event, "status": self.status,
                "duration_ms": round((time.monotonic() - self.started) * 1000, 2)}

    def begin(self):
        if self.write or self.read_action and self.path.endswith("/tail"):
            _HTTP_LOG.info("%s：开始 %s %s request=%s", self.operation, self.method, self.path, self.request_id, extra=self._extra("operation_started"))

    def response(self, status, payload=None):
        self.status = int(status)
        if not isinstance(payload, dict):
            return
        identities = []
        for key in ("project", "map", "component", "waypoint", "task_line", "run", "plan", "job"):
            data = payload.get(key)
            identity = data.get("id", data.get(f"{key}_id")) if isinstance(data, dict) else None
            if isinstance(identity, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", identity):
                identities.append(f"{key}={identity}")
        self.summary = " ".join(identities)
        for key in ("error", "capture_error"):
            if isinstance(payload.get(key), str) and payload[key]:
                self.reason = safe_message(payload[key])
                return
        issues = payload.get("validationIssues")
        if isinstance(issues, list) and issues:
            self.reason = safe_message("；".join(f"{item.get('filename', '')}: {item.get('message', '')}" for item in issues[:5] if isinstance(item, dict)))
        # Compilers and topology checks can communicate rejection in an HTTP 200.
        for data in (payload, payload.get("preview"), payload.get("topology")):
            if not isinstance(data, dict):
                continue
            errors = data.get("errors")
            if isinstance(errors, list) and errors:
                self.reason = safe_message("；".join(str(item) for item in errors[:5]))
                return
            warnings = data.get("warnings")
            if isinstance(warnings, list) and warnings:
                self.warning = safe_message("；".join(str(item) for item in warnings[:5]))

    def finish(self, *, interrupted=False, exception=False):
        if self.is_client_event:
            return  # Reporter cannot recursively produce HTTP diagnostics.
        interrupted = interrupted or self.interrupted
        failed = (self.status >= 400 or bool(self.reason) or exception) and not interrupted
        if exception:
            self.status = 500
        outcome = "interrupted" if interrupted else str(self.status) if failed else "warning" if self.warning else "ok"
        if not self.is_api and not self.read_action and not exception:
            return
        emit, recovered = _OUTCOMES.admit((self.method, self.path), outcome, time.monotonic())
        # Failures on read polling/control pulses are bounded. Explicit writes are
        # retained individually; successful read polls do not occupy the ledger.
        if not (self.write or exception or emit and (failed or recovered or self.read_action or self.warning)):
            return
        level = logging.ERROR if exception or self.status >= 500 else logging.WARNING if failed or self.warning else logging.INFO
        state = "连接中断" if interrupted else "异常" if exception else "失败" if failed else "恢复" if recovered else "完成"
        detail = "；" + "；".join(item for item in (self.summary, self.reason or self.warning) if item) if self.summary or self.reason or self.warning else ""
        _HTTP_LOG.log(level, "%s：%s %s %s status=%s %.1fms request=%s%s", self.operation, state,
                      self.method, self.path, self.status, (time.monotonic() - self.started) * 1000,
                      self.request_id, detail, extra=self._extra("operation_" + ("interrupted" if interrupted else "failed" if failed else "recovered" if recovered else "completed")), exc_info=exception)


def audit_request(function):
    @functools.wraps(function)
    def wrapped(handler, *args, **kwargs):
        audit = HttpAudit(getattr(handler, "command", function.__name__.removeprefix("do_")), handler.path)
        handler._tool_audit = audit
        with audit.context():
            audit.begin()
            try:
                result = function(handler, *args, **kwargs)
            except (BrokenPipeError, ConnectionResetError):
                audit.finish(interrupted=True)
                raise
            except Exception:
                audit.finish(exception=True)
                handler._tool_exception_logged = True
                raise
            else:
                audit.finish()
                return result
            finally:
                handler._tool_audit = None
    return wrapped


class BrowserEventRecorder:
    EVENTS = {"browser_error", "unhandled_rejection", "resource_error", "request_failed", "operation_failed", "operation_completed"}

    def __init__(self, *, clock=time.monotonic, maximum=60):
        self.clock, self.maximum = clock, maximum
        self._clients = OrderedDict()
        self._duplicates = _OutcomeGate(capacity=1024)
        self._lock = threading.Lock()

    def record(self, payload, client: str) -> bool:
        if not isinstance(payload, dict) or set(payload) - {"level", "event", "page", "message", "operation"}:
            raise ValueError("浏览器诊断格式无效")
        level, event, page, message = (payload.get(key) for key in ("level", "event", "page", "message"))
        operation = payload.get("operation", "")
        if (not isinstance(level, str) or level not in {"INFO", "WARNING", "ERROR"}
                or not isinstance(event, str) or event not in self.EVENTS
                or not isinstance(page, str) or not page.startswith("/") or page.startswith("//") or "?" in page or "#" in page or "\\" in page or re.search(r"[\x00-\x20\x7f]", page) or len(page) > 240
                or not isinstance(message, str) or not message.strip() or len(message) > 1200
                or not isinstance(operation, str) or len(operation) > 160):
            raise ValueError("浏览器诊断内容无效")
        now = self.clock()
        with self._lock:
            start, count = self._clients.pop(client, (now, 0))
            if now - start >= 60:
                start, count = now, 0
            self._clients[client] = (start, count + 1)
            while len(self._clients) > 512:
                self._clients.popitem(last=False)
            if count >= self.maximum:
                raise OverflowError("浏览器诊断提交过于频繁")
        page, operation, message = safe_message(page, limit=240), safe_message(operation, limit=160), safe_message(message)
        emit, _ = self._duplicates.admit((client, level, event, page, operation, message), "event", now)
        if not emit:
            return False
        _BROWSER_LOG.log(getattr(logging, level), "浏览器 %s %s %s：%s", page, event, operation, message,
                         extra={"event": event, "path": page, "operation": operation})
        return True
