/* Loaded synchronously before first-party page scripts, including Vue entries. */
(() => {
  if (globalThis.RYAletheiaDiagnostics || typeof window === 'undefined') return;
  const endpoint = '/api/tool-logs/client-events';
  const nativeFetch = globalThis.fetch;
  const recent = new Map();
  const reportedErrors = new WeakSet();
  let windowStarted = Date.now(), sent = 0, inFlight = 0, leaving = false;
  const ignoredPath = path => path === endpoint || path.startsWith('/api/observation/client-');
  const errorText = error => typeof error === 'string' ? error : typeof error?.message === 'string' ? error.message : '未知浏览器异常';
  function clean(value, limit = 1200) {
    return errorText(value).slice(0, 8192)
      .replace(/(?:https?|wss?|rtsps?|mqtts?):\/\/[^\s<>"')]+/gi, text => {
        try { const url = new URL(text); return `${url.protocol}//${url.host}${url.pathname}`; }
        catch { return '[URL]'; }
      })
      .replace(/(?:data|blob):[^\s<>"')]+/gi, '[资源]')
      .replace(/\/[^\s<>"']*/g, path => path.split(/[?#]/)[0])
      .replace(/\b(?:authorization|cookie|password|passwd|token|secret|api[_-]?key)["']?\s*[:=]\s*(?:"[^"]*"|'[^']*'|(?:Bearer\s+)?[^\s,;]+)/gi, '[已隐藏]')
      .replace(/[\u0000-\u001f\u007f]/g, ' ').slice(0, limit);
  }
  function report(input) {
    let started = false;
    try {
      if (leaving || typeof nativeFetch !== 'function' || !input) return false;
      const now = Date.now();
      if (now - windowStarted >= 60000) { windowStarted = now; sent = 0; }
      for (const [key, time] of recent) if (now - time >= 30000) recent.delete(key);
      const payload = {
        level: ['INFO', 'WARNING', 'ERROR'].includes(input.level) ? input.level : 'ERROR',
        event: input.event,
        page: clean(globalThis.location?.pathname || '/', 160),
        message: clean(input.message),
      };
      if (!['browser_error','unhandled_rejection','resource_error','request_failed','operation_failed','operation_completed'].includes(payload.event)) return false;
      if (input.operation) payload.operation = clean(input.operation, 160);
      const key = JSON.stringify(payload);
      if (recent.has(key) || sent >= 60 || inFlight >= 2) return false;
      // Never queue, retry or report the reporter's own failure.
      recent.set(key, now); sent++; inFlight++; started = true;
      Promise.resolve(nativeFetch.call(globalThis, endpoint, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify(payload), keepalive: true,
      })).catch(() => {}).finally(() => { inFlight--; });
      return true;
    } catch { if (started) inFlight--; return false; }
  }
  function requestInfo(input, options) {
    try {
      const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url, globalThis.location.href);
      if (url.origin !== globalThis.location.origin || !url.pathname.startsWith('/api/') || ignoredPath(url.pathname)) return null;
      // Planned shutdown/restart probes intentionally fail while the process exits.
      if (url.pathname === '/api/system/upgrade' && (url.searchParams.has('shutdownProbe') || url.searchParams.has('restartProbe'))) return null;
      return `${String(options?.method || input?.method || 'GET').toUpperCase()} ${url.pathname}`;
    } catch { return null; }
  }
  function requestFailure(error, input, options, status) {
    if (error?.name === 'AbortError') return;
    const operation = requestInfo(input, options);
    if (!operation) return;
    if (status === 404 && operation === 'GET /api/acceptance/plans/current') return;
    if (error && typeof error === 'object') {
      if (reportedErrors.has(error)) return;
      reportedErrors.add(error);
    }
    report({event:'request_failed',level:'ERROR',operation,message:status ? `请求失败（HTTP ${status}）` : '请求连接失败'});
  }
  function failure(operation, error) {
    if (error?.name === 'AbortError' || error && typeof error === 'object' && reportedErrors.has(error)) return;
    if (error && typeof error === 'object') reportedErrors.add(error);
    report({event:'operation_failed',level:'ERROR',operation,message:errorText(error)});
  }
  globalThis.RYAletheiaDiagnostics = {report, failure, requestFailure};
  if (typeof nativeFetch === 'function') globalThis.fetch = function(input, options) {
    // Retain the original arguments, Response and rejection object. No body is read.
    return nativeFetch.apply(this, arguments).then(response => {
      if (!response.ok) requestFailure(null, input, options, response.status);
      return response;
    }, error => { requestFailure(error, input, options); throw error; });
  };
  // XHR is still used for upload progress in legacy and Vue pages.
  const xhr = globalThis.XMLHttpRequest?.prototype;
  if (xhr) {
    const open = xhr.open;
    xhr.open = function(method, url) {
      const result = open.apply(this, arguments);
      let aborted = false;
      const onAbort = () => { aborted = true; };
      this.addEventListener('abort', onAbort, {once:true});
      this.addEventListener('loadend', () => {
        this.removeEventListener('abort', onAbort);
        if (!aborted && (!this.status || this.status >= 400)) requestFailure(null, url, {method}, this.status);
      }, {once:true});
      return result;
    };
  }
  window.addEventListener('error', event => {
    const target = event.target;
    if (target?.tagName && ['SCRIPT','LINK','IMG'].includes(target.tagName)) {
      report({event:'resource_error',level:'ERROR',operation:'resource.load',message:`${target.tagName} 加载失败：${clean(target.src || target.href || '')}`});
    } else {
      report({event:'browser_error',level:'ERROR',message:errorText(event.error || event.message),operation:event.filename ? `${clean(event.filename)}:${event.lineno || 0}:${event.colno || 0}` : 'page.script'});
    }
  }, true);
  window.addEventListener('unhandledrejection', event => {
    if (event.reason?.name === 'AbortError' || event.reason && typeof event.reason === 'object' && reportedErrors.has(event.reason)) return;
    report({event:'unhandled_rejection',level:'ERROR',message:errorText(event.reason),operation:'page.promise'});
  });
  window.addEventListener('pagehide', () => { leaving = true; });
  window.addEventListener('pageshow', () => { leaving = false; });
})();
