import {paintStyledVirtualWalls} from './map-architecture.js';

// Export the display raster at its native resolution. UI, routes, origin marks
// and difference highlights belong to the editor, not to the viewing image.
export function createMapImageCanvas({document,surface,map,virtualWalls=[]}) {
  if(!surface||!map||surface.width!==map.width||surface.height!==map.height
    ||!Number.isFinite(map.resolution_m)||map.resolution_m<=0)throw Error('美化地图尚未就绪，请稍后重试');
  const canvas=document.createElement('canvas');
  canvas.width=map.width;canvas.height=map.height;
  const context=canvas.getContext('2d');
  if(!context)throw Error('无法生成地图图片');
  context.fillStyle='#e7ecf2';context.fillRect(0,0,canvas.width,canvas.height);
  context.drawImage(surface,0,0);
  const view={x:0,y:0,scale:1/map.resolution_m};
  // Manual edits and wall-side floor classification are baked into surface.
  // Export exactly that result, without painting erase history over it again.
  paintStyledVirtualWalls(context,{map,view,walls:virtualWalls});
  return canvas;
}
