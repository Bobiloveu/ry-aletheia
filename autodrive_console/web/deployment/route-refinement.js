import {buildRouteGrid} from './route-planner.js';

// Refine only a bounded window. Keep exact task anchors and all obstacles;
// large maps never require a second full-resolution distance field.
export function buildLocalRouteGrid({rgba,width,height,map,virtualWalls=[],radiusM},start,end,{maxCells=900000}={}) {
  const resolution=map.resolution_m,origin=map.origin||[0,0,0];
  const angle=origin[2]||0,c=Math.cos(angle),s=Math.sin(angle);
  const raster=p=>({x:((p.x-origin[0])*c+(p.y-origin[1])*s)/resolution,
    y:height-(-(p.x-origin[0])*s+(p.y-origin[1])*c)/resolution});
  const a=raster(start),b=raster(end);
  if(![a,b].every(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)&&p.x>=0&&p.y>=0&&p.x<width&&p.y<height))return null;
  const margin=Math.ceil(Math.max(2,(radiusM||0)*4)/resolution);
  const x0=Math.max(0,Math.floor(Math.min(a.x,b.x))-margin),y0=Math.max(0,Math.floor(Math.min(a.y,b.y))-margin);
  const x1=Math.min(width,Math.floor(Math.max(a.x,b.x))+margin+1),y1=Math.min(height,Math.floor(Math.max(a.y,b.y))+margin+1);
  const w=x1-x0,h=y1-y0;
  if(w*h>maxCells)return null;
  const pixels=new Uint8ClampedArray(w*h*4);
  for(let y=0;y<h;y++)pixels.set(rgba.subarray(((y0+y)*width+x0)*4,((y0+y)*width+x1)*4),y*w*4);
  const localX=x0*resolution,localY=(height-y1)*resolution;
  const localMap={...map,width:w,height:h,origin:[origin[0]+c*localX-s*localY,origin[1]+s*localX+c*localY,angle]};
  return buildRouteGrid({rgba:pixels,width:w,height:h,map:localMap,virtualWalls,radiusM,maxCells});
}
