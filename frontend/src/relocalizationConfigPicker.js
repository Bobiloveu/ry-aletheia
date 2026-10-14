// A one-operation selection; never persisted to browser or robot settings.
export function createRelocalizationConfigPicker({ root, request, onChange }) {
  const get = (name) => root.querySelector(`#relocalizationConfig${name}`);
  const elements = Object.fromEntries(['Mode', 'Manual', 'Selected', 'Browse', 'Browser',
    'Directory', 'Up', 'Root', 'Close', 'Entries', 'Message'].map(name => [name, get(name)]));
  let mode = 'auto';
  let selected = '';
  let editable = false;
  let generation = 0;
  let directory;
  let knownRoot = '';
  // Only directory metadata is cached, never YAML contents or a validated selection.
  // Keep it local to this operation and bounded even when browsing a large tree.
  const listings = new Map();
  const reads = new Map();
  const listingKey = path => path || knownRoot;

  function cancelReadsExcept(key) {
    for (const [path, read] of reads) {
      if (path === key) continue;
      read.controller.abort();
      reads.delete(path);
    }
  }
  function clearListings() {
    listings.clear();
    knownRoot = '';
  }
  function readDirectory(path, priority = 'auto') {
    const key = listingKey(path);
    const cached = listings.get(key);
    if (cached && Date.now() - cached.loadedAt < 15_000) {
      listings.delete(key);
      listings.set(key, cached);
      return Promise.resolve(cached.result);
    }
    listings.delete(key);
    if (reads.has(key)) return reads.get(key).promise;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(
      new DOMException('目录读取超时，请重试', 'TimeoutError')), 5000);
    const read = { controller };
    read.promise = Promise.resolve().then(() => {
      if (controller.signal.aborted) throw controller.signal.reason;
      return request(`/api/observation/relocalization/configs?path=${encodeURIComponent(path)}`,
        { signal: controller.signal, priority });
    }).then(result => {
      if (controller.signal.aborted) throw controller.signal.reason;
      knownRoot = result.root;
      listings.delete(result.path);
      listings.set(result.path, { result, loadedAt: Date.now() });
      while (listings.size > 20) listings.delete(listings.keys().next().value);
      return result;
    }).catch(error => {
      throw controller.signal.aborted ? controller.signal.reason : error;
    }).finally(() => {
      clearTimeout(timer);
      if (reads.get(key) === read) reads.delete(key);
    });
    reads.set(key, read);
    return read.promise;
  }
  async function prefetch(result, token) {
    // One low-priority read at a time; never recursively scan the robot tree.
    for (const child of (result.directories || []).slice(0, 6)) {
      if (token !== generation || !editable || mode !== 'manual') return;
      try { await readDirectory(child.path, 'low'); }
      catch { return; /* Keep the usable listing and stop speculative reads on failure. */ }
    }
  }

  function render() {
    elements.Mode.value = mode;
    elements.Mode.disabled = !editable;
    elements.Manual.hidden = mode !== 'manual';
    elements.Browse.disabled = !editable;
    elements.Selected.textContent = selected || '尚未选择定位配置';
    elements.Selected.title = selected;
  }
  function close() {
    generation++;
    cancelReadsExcept();
    elements.Browser.hidden = true;
    elements.Browse.setAttribute('aria-expanded', 'false');
  }
  async function browse(path = '') {
    if (!editable || mode !== 'manual') return;
    const token = ++generation;
    cancelReadsExcept(listingKey(path));
    elements.Browser.hidden = false;
    elements.Browse.setAttribute('aria-expanded', 'true');
    elements.Entries.replaceChildren();
    elements.Message.textContent = '正在读取小车定位配置目录…';
    elements.Up.disabled = true;
    elements.Root.disabled = true;
    try {
      const result = await readDirectory(path);
      if (token !== generation || !editable || mode !== 'manual') return;
      directory = result;
      elements.Directory.textContent = result.path;
      elements.Up.disabled = !result.parent;
      elements.Root.disabled = result.path === result.root;
      const entries = [];
      for (const [items, isDirectory] of [[result.directories, true], [result.files, false]]) {
        for (const item of items || []) {
          const button = root.ownerDocument.createElement('button');
          button.type = 'button';
          button.className = 'relocalization-config-entry';
          button.textContent = isDirectory ? `目录：${item.name}` : item.name;
          button.title = item.path;
          button.addEventListener('click', () => {
            if (!editable || token !== generation) return;
            if (isDirectory) return browse(item.path);
            selected = item.path;
            close();
            render();
            elements.Browse.focus();
            onChange(true);
          });
          entries.push(button);
        }
      }
      elements.Entries.replaceChildren(...entries);
      elements.Message.textContent = entries.length ? '' : '此目录没有定位 YAML，可返回上一级。';
      void prefetch(result, token);
    } catch (error) {
      if (token !== generation) return;
      elements.Message.textContent = `${error.message || '目录读取失败'}；可重新选择或切回自动。`;
    }
  }
  elements.Mode.addEventListener('change', () => {
    if (!editable) return;
    mode = elements.Mode.value === 'manual' ? 'manual' : 'auto';
    selected = '';
    directory = undefined;
    close();
    clearListings();
    render();
    onChange(true);
    if (mode === 'manual') return browse();
  });
  elements.Browse.addEventListener('click', () => browse(directory?.path || ''));
  elements.Up.addEventListener('click', () => directory?.parent && browse(directory.parent));
  elements.Root.addEventListener('click', () => browse());
  elements.Close.addEventListener('click', () => { close(); elements.Browse.focus(); });
  render();
  return {
    setEditable(value) {
      editable = value;
      if (!editable && !elements.Browser.hidden) close();
      if (!editable) clearListings();
      render();
    },
    reset() {
      mode = 'auto';
      selected = '';
      directory = undefined;
      close();
      clearListings();
      render();
      onChange(false);
    },
    ready: () => mode === 'auto' || !!selected,
    payload(pose) {
      if (mode === 'auto') return { ...pose };
      if (!selected) throw Error('请先选择定位 YAML 文件');
      return { ...pose, config_path: selected };
    },
    summary: () => mode === 'auto' ? '沿用当前定位配置' : `加载所选定位配置，并切换到配置对应的二维地图：${selected}`,
    close,
  };
}
