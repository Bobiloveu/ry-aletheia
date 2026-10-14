/** Validate the bounded, read-only point-cloud wire payload before GPU allocation. */
export function decodePointPreview(buffer, headers) {
  const integer = (name) => {
    const value = headers.get(name);
    if (!/^[1-9][0-9]{0,9}$/.test(value || '')) throw new Error('点云预览统计无效，请重新上传点云。');
    return Number(value);
  };
  const sampleCount = integer('X-Point-Count');
  const pointCount = integer('X-Source-Point-Count');
  const finiteCount = integer('X-Finite-Point-Count');
  const format = headers.get('X-Point-Format');
  const dense = format === 'xyz-rgba-intensity-v1';
  if (format && !dense) throw new Error('点云显示格式不支持，请刷新页面。');
  const stride = dense ? 20 : 12;
  if (pointCount > 10000000 || sampleCount > (dense ? 10000000 : 100000) || (dense && sampleCount !== finiteCount) || sampleCount > finiteCount || finiteCount > pointCount || buffer.byteLength !== sampleCount * stride) throw new Error('点云预览数据不完整，请重新读取。');
  let origin, bounds;
  try { origin = JSON.parse(headers.get('X-Point-Origin')); bounds = JSON.parse(headers.get('X-Point-Bounds')); }
  catch { throw new Error('点云预览坐标信息无效。'); }
  if (!Array.isArray(origin) || origin.length !== 3 || !origin.every(Number.isFinite)
    || !Array.isArray(bounds) || bounds.length !== 3 || !bounds.every((pair) => Array.isArray(pair) && pair.length === 2 && pair.every(Number.isFinite) && pair[0] <= pair[1])) throw new Error('点云预览坐标信息无效。');
  const localBounds = bounds.map((pair, axis) => pair.map((value) => value - origin[axis]));
  if (!localBounds.flat().every(Number.isFinite)) throw new Error('点云坐标跨度过大。');
  const view = new DataView(buffer);
  const positions = new Float32Array(sampleCount * 3);
  for (let index = 0; index < positions.length; index += 1) {
    const coordinate = view.getFloat32(Math.floor(index / 3) * stride + (index % 3) * 4, true);
    if (!Number.isFinite(coordinate)) throw new Error('点云包含无效预览坐标。');
    positions[index] = coordinate;
  }
  let attributes = {rgb:false,intensity:false,intensity_range:null,display_bounds:bounds};
  const colors = new Uint8Array(sampleCount * 4);
  const intensities = new Float32Array(sampleCount);
  intensities.fill(NaN);
  if (dense) {
    try { attributes = JSON.parse(headers.get('X-Point-Attributes')); } catch { throw new Error('点云颜色信息无效。'); }
    const validPair = pair => Array.isArray(pair) && pair.length === 2 && pair.every(Number.isFinite) && pair[0] <= pair[1];
    if (!attributes || typeof attributes.rgb !== 'boolean' || typeof attributes.intensity !== 'boolean'
      || (attributes.intensity && !validPair(attributes.intensity_range))
      || !Array.isArray(attributes.display_bounds) || attributes.display_bounds.length !== 3
      || !attributes.display_bounds.every((pair,axis)=>validPair(pair) && pair[0] >= bounds[axis][0] && pair[1] <= bounds[axis][1])) throw new Error('点云显示范围或颜色信息无效。');
    for (let index = 0; index < sampleCount; index += 1) {
      for(let channel=0;channel<4;channel+=1) colors[index*4+channel] = view.getUint8(index*stride+12+channel);
      const intensity = view.getFloat32(index*stride+16,true);
      if (intensity === Infinity || intensity === -Infinity) throw new Error('点云强度信息无效。');
      intensities[index] = intensity;
    }
  }
  const displayBounds = attributes.display_bounds.map((pair,axis)=>pair.map(value=>value-origin[axis]));
  if (!displayBounds.flat().every(Number.isFinite)) throw new Error('点云显示坐标跨度过大。');
  return { positions, colors, intensities, attributes, displayBounds, defaultColorMode:attributes.rgb?'rgb':'height', sampleCount, pointCount, finiteCount, origin, bounds, localBounds };
}

export function readViewerLocation(search) {
  const query = new URLSearchParams(search);
  const project = query.get('project');
  const projection = query.get('projection');
  if (!/^[a-zA-Z0-9_-]{1,160}$/.test(project || '') || !/^projection-[a-f0-9]{32}$/.test(projection || '')) throw new Error('源点云入口已失效，请从部署向导重新打开。');
  const low = query.get('z_min');
  const high = query.get('z_max');
  const band = low !== null && high !== null && low.trim() && high.trim() && Number.isFinite(Number(low)) && Number.isFinite(Number(high)) && Number(low) < Number(high) ? [Number(low),Number(high)] : null;
  return { url: `/api/deployments/${encodeURIComponent(project)}/map-projections/${projection}/source-detail.bin`, band };
}

/** Keep display-only slice geometry inside the observed source extent. */
export function clipDisplayBand(band, bounds) {
  if (!band) return null;
  const low = Math.max(band[0], bounds[0]);
  const high = Math.min(band[1], bounds[1]);
  return low <= high ? [low,high] : null;
}

/** Private display synchronization, accepted only from the embedding parent. */
export function readEmbeddedBand(event, origin, parent) {
  const data = event.data;
  if (event.origin !== origin || event.source !== parent || data?.type !== 'aletheia-pcd-band') return null;
  const band = data.band;
  return Array.isArray(band) && band.length === 2 && band.every(Number.isFinite) && band[0] < band[1] ? [...band] : null;
}
