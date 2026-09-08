export function drawDeploymentCanvas({
  context,
  canvasBox,
  activeMap,
  mapImage,
  liveMapImage,
  mappingPreview,
  project,
  view,
  drawGrid,
  drawMapEdits,
  drawMapRoutes,
  drawComponentSymbol,
  mapPointToCanvas,
}) {
  context.clearRect(0, 0, canvasBox.width, canvasBox.height);
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, canvasBox.width, canvasBox.height);
  if (!activeMap || !mapImage) {
    if (!liveMapImage || !mappingPreview?.width || !mappingPreview?.height) return;
    const scale = Math.min(
      (canvasBox.width - 48) / mappingPreview.width,
      (canvasBox.height - 48) / mappingPreview.height,
    );
    const width = mappingPreview.width * scale;
    const height = mappingPreview.height * scale;
    context.imageSmoothingEnabled = false;
    context.drawImage(liveMapImage, (canvasBox.width - width) / 2, (canvasBox.height - height) / 2, width, height);
    context.strokeStyle = "#0a84ff";
    context.strokeRect((canvasBox.width - width) / 2, (canvasBox.height - height) / 2, width, height);
    return;
  }
  drawGrid(canvasBox.width, canvasBox.height);
  const pixels = view.scale * activeMap.resolution_m;
  context.save();
  context.imageSmoothingEnabled = false;
  context.drawImage(mapImage, view.x, view.y, activeMap.width * pixels, activeMap.height * pixels);
  context.strokeStyle = "#38d59a";
  context.lineWidth = 1.5;
  context.strokeRect(view.x, view.y, activeMap.width * pixels, activeMap.height * pixels);
  context.save();
  context.beginPath();
  context.rect(view.x, view.y, activeMap.width * pixels, activeMap.height * pixels);
  context.clip();
  drawMapEdits();
  context.restore();
  drawMapRoutes();
  for (const point of (project?.waypoints || []).filter((item) => item.map_asset_id === activeMap.id && !item.generated_by)) {
    const { x, y } = mapPointToCanvas(point, activeMap, view);
    const palette = { start: "#39dcad", target: "#ffbd61", map_transition: "#b995ef" };
    context.fillStyle = palette[point.kind] || "#5bb8ff";
    context.beginPath();
    context.arc(x, y, point.kind === "map_transition" ? 7 : 5, 0, Math.PI * 2);
    context.fill();
    if (point.kind === "map_transition") {
      context.strokeStyle = "#fff";
      context.lineWidth = 1.5;
      context.beginPath();
      context.arc(x, y, 3, 0, Math.PI * 2);
      context.stroke();
    }
    context.fillStyle = "rgba(18, 28, 34, .9)";
    context.font = "600 10px system-ui, sans-serif";
    context.textAlign = "left";
    context.fillText(point.label, x + 8, y - 8);
  }
  for (const item of (project?.components || []).filter((component) => component.map_asset_id === activeMap.id)) {
    const { x, y } = mapPointToCanvas(item, activeMap, view);
    drawComponentSymbol(item, x, y);
  }
  context.restore();
}
