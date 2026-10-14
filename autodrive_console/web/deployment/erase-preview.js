import { mapPointToCanvas } from "./canvas-geometry.js";

export function eraseEditsForRender({
  savedEdits = [],
  activeMapId,
  activeStroke = null,
  pendingStroke = null,
  pendingPolygon = null,
}) {
  const edits = savedEdits.filter((edit) => edit.map_asset_id === activeMapId);
  if (activeStroke) edits.push(activeStroke);
  if (pendingStroke) edits.push(pendingStroke);
  if (pendingPolygon?.map_asset_id === activeMapId) edits.push(pendingPolygon);
  return edits;
}

export function paintEraseOperation(context, edit, {map, view, defaultRadius = .4}) {
  const toCanvas = point => mapPointToCanvas(point, map, view);
  const points = edit.points || [];
  if (!points.length) return;
  context.save();
  context.globalAlpha = 1;
  const color = edit.mode === "wall" ? "#000" : "#fff";
  if (edit.kind === "brush_erase") {
    const radius = Number(edit.radius_m || defaultRadius) * view.scale;
    const shape = edit.shape || "circle";
    context.strokeStyle = color;
    context.fillStyle = color;
    const first = toCanvas(points[0]);
    if (shape === "square") {
      const side = radius * 2;
      for (const point of points) {
        const next = toCanvas(point);
        context.fillRect(next.x - radius, next.y - radius, side, side);
      }
    } else {
      context.lineCap = "round";
      context.lineJoin = "round";
      context.lineWidth = radius * 2;
      context.beginPath();
      context.moveTo(first.x, first.y);
      for (const point of points.slice(1)) {
        const next = toCanvas(point);
        context.lineTo(next.x, next.y);
      }
      context.stroke();
      context.beginPath();
      context.arc(first.x, first.y, radius, 0, Math.PI * 2);
      context.fill();
    }
  } else if (points.length >= 3) {
    const first = toCanvas(points[0]);
    context.beginPath();
    context.moveTo(first.x, first.y);
    for (const point of points.slice(1)) {
      const next = toCanvas(point);
      context.lineTo(next.x, next.y);
    }
    context.closePath();
    context.fillStyle = color;
    context.fill();
  }
  context.restore();
}
// Read a binary edit layer using the same coverage/color thresholds as the
// styled outline and navigation export. Antialiasing must not create obstacles
// in cells that are less than half covered by a black brush.
export function readEditedMapPixels(context,{width,height,map,edits=[]}) {
  const source=context.getImageData(0,0,width,height);
  if(!edits.length)return source;
  context.clearRect(0,0,width,height);
  for(const edit of edits)paintEraseOperation(context,edit,{map,view:{x:0,y:0,scale:1/map.resolution_m}});
  const mask=context.getImageData(0,0,width,height).data;
  for(let i=0;i<mask.length;i+=4)if(mask[i+3]>=128) {
    const value=mask[i]>=128?255:0;
    source.data[i]=source.data[i+1]=source.data[i+2]=value;source.data[i+3]=255;
  }
  return source;
}
