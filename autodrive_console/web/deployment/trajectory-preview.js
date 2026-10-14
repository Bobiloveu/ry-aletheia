import { decodeTrajectory } from './raster-preview.js';

export function createTrajectoryPreview({fetchImpl = globalThis.fetch, onChange = () => {}} = {}) {
  let scope = null, epoch = 0, abort = null;
  let state = {trajectory:null, visible:true, busy:false, name:'', error:''};
  const emit = () => onChange({...state});
  function remove() {
    epoch++; abort?.abort(); abort = null;
    state = {trajectory:null, visible:true, busy:false, name:'', error:''}; emit();
  }
  return {
    setScope(project, job) {
      const next = project && job ? `/api/deployments/${encodeURIComponent(project)}/map-projections/${encodeURIComponent(job)}` : null;
      if (next !== scope) { scope = next; remove(); }
    },
    async upload(file) {
      if (!scope || !file || state.busy) return;
      const generation = ++epoch;
      abort = new AbortController();
      state = {...state, busy:true, error:''}; emit();
      const body = new FormData(); body.append('file', file, file.name || 'trajectory.pcd');
      try {
        const response = await fetchImpl(`${scope}/trajectory-preview.bin`, {method:'POST', body, signal:abort.signal});
        if (!response.ok) { const error = await response.json(); throw Error(error.error || '轨迹读取失败。'); }
        if (Number(response.headers.get('Content-Length')) > 80000000) throw Error('轨迹预览超过大小限制。');
        const buffer = await response.arrayBuffer();
        if (generation !== epoch) return;
        state = {...state, trajectory:decodeTrajectory(buffer,response.headers), name:file.name || '轨迹 PCD', visible:true};
      } catch (error) { if (generation === epoch) { globalThis.RYAletheiaDiagnostics?.failure?.('deployment.trajectory-preview',error); state = {...state, error:error.message}; } }
      finally { if (generation === epoch) { state = {...state, busy:false}; abort = null; emit(); } }
    },
    show(visible) { state = {...state, visible}; emit(); },
    remove,
    dispose() { epoch++; abort?.abort(); state.trajectory = null; },
  };
}

export function bindTrajectoryPreview({root, raster}) {
  const $ = id => root.getElementById(id);
  const picker = $('pcdTrajectoryFile');
  const controller = createTrajectoryPreview({onChange(state) {
    raster.setTrajectory(state.visible ? state.trajectory : null);
    picker.disabled = state.busy;
    $('pcdTrajectoryVisible').disabled = !state.trajectory;
    $('pcdTrajectoryVisible').checked = state.visible;
    $('pcdTrajectoryRemove').hidden = !state.trajectory && !state.busy;
    $('pcdTrajectoryStatus').textContent = state.error || (state.busy ? '正在读取轨迹…' : state.trajectory
      ? `${state.name} · ${(state.trajectory.points.length/2).toLocaleString('zh-CN')} 个点` : '可选；须与地图使用同一坐标系。仅预览，不写入地图，刷新后需重新选择。');
    $('pcdTrajectoryStatus').classList.toggle('is-error', Boolean(state.error));
  }});
  picker.addEventListener('change', () => { const file = picker.files?.[0]; picker.value = ''; if (file) controller.upload(file); });
  $('pcdTrajectoryVisible').addEventListener('change', () => controller.show($('pcdTrajectoryVisible').checked));
  $('pcdTrajectoryRemove').addEventListener('click', controller.remove);
  return {
    render(view) {
      const available = view.projection?.analysis && !['cancelled','imported'].includes(view.projection.state) && !view.file;
      controller.setScope(available ? view.projectId : null, available ? view.projection.id : null);
      $('pcdTrajectoryControls').hidden = !available;
    },
    dispose:controller.dispose,
  };
}
