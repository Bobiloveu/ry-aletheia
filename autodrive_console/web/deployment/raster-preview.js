/** Screen-space occupancy accumulation: every source obstacle votes, even below one pixel. */
export function rasterizeObstacles(cells, imageWidth, view, radius = .5) {
  const width = Math.ceil(view.width), height = Math.ceil(view.height);
  const mask = new Uint8Array(width * height);
  // Most full-map views collapse many obstacle cells into the same screen pixel.
  // Avoid a fill/rectangle loop for each of those votes on million-cell maps.
  if (radius === .5 && view.scale <= 1) {
    let previousRow = -1, sy = -1;
    for (let i = 0; i < cells.length; i++) {
      const cell = cells[i], row = Math.floor(cell / imageWidth);
      if (row !== previousRow) {
        previousRow = row;
        sy = Math.floor(view.y + (row + .5) * view.scale);
      }
      if (sy < 0 || sy >= height) continue;
      const sx = Math.floor(view.x + (cell - row * imageWidth + .5) * view.scale);
      if (sx >= 0 && sx < width) mask[sy * width + sx] = 1;
    }
    return mask;
  }
  const half = Math.max(view.scale / 2, radius);
  for (const cell of cells) {
    const cx = view.x + (cell % imageWidth + .5) * view.scale;
    const cy = view.y + (Math.floor(cell / imageWidth) + .5) * view.scale;
    const left = Math.floor(cx - half + .5), top = Math.floor(cy - half + .5);
    const right = Math.max(left + 1, Math.ceil(cx + half - .5));
    const bottom = Math.max(top + 1, Math.ceil(cy + half - .5));
    if (right <= 0 || left >= width || bottom <= 0 || top >= height) continue;
    for (let y = Math.max(0, top); y < Math.min(height, bottom); y++) {
      mask.fill(1, y * width + Math.max(0, left), y * width + Math.min(width, right));
    }
  }
  return mask;
}

export function trajectoryTransform(origin, result, view) {
  const scale = view.scale / result.resolution_m;
  return {scale, x: view.x + (origin[0] - result.origin[0]) * scale,
    y: view.y + result.height * view.scale - (origin[1] - result.origin[1]) * scale};
}

export function decodeTrajectory(buffer, headers) {
  const count = Number(headers.get('X-Point-Count'));
  const origin = JSON.parse(headers.get('X-Point-Origin'));
  if (headers.get('X-Point-Format') !== 'xy-v1' || !Number.isInteger(count) || count < 1 || count > 10000000
      || buffer.byteLength !== count * 8 || !Array.isArray(origin) || origin.length !== 2 || !origin.every(Number.isFinite)) {
    throw Error('轨迹预览数据无效，请重新选择文件。');
  }
  const data = new DataView(buffer);
  const points = new Float32Array(count * 2);
  for (let i = 0; i < points.length; i++) {
    points[i] = data.getFloat32(i * 4, true);
    if (!Number.isFinite(points[i])) throw Error('轨迹包含无效坐标。');
  }
  return {points, origin};
}

export function bindRasterPreview({canvas, document, schedule = globalThis.requestAnimationFrame, cancel = globalThis.cancelAnimationFrame}) {
  let cells = null, result = null, view = null, trajectory = null, radius = .5, frame = null;
  function paint() {
    frame = null;
    if (!cells || !view) return;
    const context = canvas.getContext('2d', {alpha:false});
    // Work is bounded by the visible CSS viewport, never a huge zoomed canvas.
    canvas.width = Math.ceil(view.width);
    canvas.height = Math.ceil(view.height);
    const mask = rasterizeObstacles(cells, result.width, view, radius);
    const output = context.createImageData(canvas.width, canvas.height);
    output.data.fill(255);
    for (let i = 0; i < mask.length; i++) if (mask[i]) {
      output.data[i*4] = output.data[i*4+1] = output.data[i*4+2] = 0;
    }
    context.putImageData(output, 0, 0);
    if (trajectory) {
      const t = trajectoryTransform(trajectory.origin, result, view);
      context.fillStyle = '#168ba3';
      const points = trajectory.points;
      for (let i = 0; i < points.length; i += 2) {
        const x = t.x + points[i] * t.scale, y = t.y - points[i+1] * t.scale;
        if (x >= -2 && y >= -2 && x <= canvas.width + 2 && y <= canvas.height + 2) context.fillRect(x-1, y-1, 2, 2);
      }
    }
  }
  const redraw = () => { if (cells && view && frame === null) frame = schedule(paint); };
  return {
    setImage(image, metadata) {
      const scratch = document.createElement('canvas');
      scratch.width = image.naturalWidth; scratch.height = image.naturalHeight;
      const ctx = scratch.getContext('2d', {willReadFrequently:true});
      ctx.drawImage(image, 0, 0);
      const rgba = ctx.getImageData(0, 0, scratch.width, scratch.height).data;
      let count = 0;
      for (let i = 0; i < rgba.length; i += 4) if (rgba[i] === 0) count++;
      cells = new Uint32Array(count);
      for (let i = 0, j = 0; i < rgba.length; i += 4) if (rgba[i] === 0) cells[j++] = i / 4;
      result = metadata;
      scratch.width = scratch.height = 0;
      redraw();
    },
    clearImage() { cells = result = null; },
    setView(next) { view = next; redraw(); },
    setRadius(next) { if (Number.isFinite(next) && next >= .5 && next <= 4) { radius = next; redraw(); } },
    setTrajectory(next) { trajectory = next; redraw(); },
    dispose() { if (frame !== null) cancel(frame); cells = result = view = trajectory = null; },
  };
}
