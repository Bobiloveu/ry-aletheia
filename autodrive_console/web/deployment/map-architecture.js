// Viewing geometry only: trace the accepted passage mask, never reinterpret
// unknown scan points as rooms or modify the underlying occupancy evidence.
import {mapPointToCanvas} from './canvas-geometry.js';

function applyWallStyle(context,resolution,scale) {
  context.strokeStyle='#8b99a7';
  context.lineWidth=Math.max(.8,Math.min(2,.06/resolution)*scale);
  context.lineJoin='round';context.lineCap='round';
}

// Virtual walls remain authoritative over manual erase overlays. They need
// their own viewing stroke even when both sides belong to the white passage.
export function paintStyledVirtualWalls(context,{walls=[],map,view}) {
  const selected=walls.filter(w=>w.map_asset_id===map.id).map(w=>Array.isArray(w.points)?w.points:[w.start,w.end])
    .filter(points=>points.length>=2&&points.every(p=>Number.isFinite(p?.x)&&Number.isFinite(p?.y)));
  if(!selected.length)return;
  context.save();
  try {
    context.beginPath();context.rect(view.x,view.y,map.width*view.scale*map.resolution_m,map.height*view.scale*map.resolution_m);context.clip();
    applyWallStyle(context,map.resolution_m,view.scale*map.resolution_m);
    context.beginPath();
    for(const points of selected) {
      const first=mapPointToCanvas(points[0],map,view);context.moveTo(first.x,first.y);
      for(const p of points.slice(1)){const next=mapPointToCanvas(p,map,view);context.lineTo(next.x,next.y);}
    }
    context.stroke();
  }finally{context.restore();}
}

export function buildMapContours({floor,width,height,resolution,maxVertices=250_000}) {
  const edges=new Uint8Array(floor.length),vertices=[],offsets=[0];
  for(let y=0;y<height;y++)for(let x=0;x<width;x++) {
    const i=y*width+x;
    if(!floor[i])continue;
    edges[i]=(y===0||!floor[i-width]?1:0)|(x===width-1||!floor[i+1]?2:0)
      |(y===height-1||!floor[i+width]?4:0)|(x===0||!floor[i-1]?8:0);
  }
  // Clockwise directed edges keep floor on the right. At a shared diagonal
  // vertex, a right turn closes each region instead of joining their corners.
  const dx=[1,0,-1,0],dy=[0,1,0,-1];
  function cell(x,y,d) {
    if(d===1||d===2)x--;
    if(d===2||d===3)y--;
    return x<0||y<0||x>=width||y>=height?-1:y*width+x;
  }
  for(let seed=0;seed<edges.length;seed++)while(edges[seed]) {
    let d=0;while(!(edges[seed]&(1<<d)))d++;
    const sx=seed%width+(d===1||d===2?1:0),sy=Math.floor(seed/width)+(d>=2?1:0);
    let x=sx,y=sy,previous=d;
    vertices.push(x,y);
    do {
      if(d!==previous){vertices.push(x,y);previous=d;}
      if(vertices.length/2>maxVertices)return {vertices:new Uint32Array(),offsets:new Uint32Array([0]),resolution,limited:true};
      edges[cell(x,y,d)]&=~(1<<d);
      x+=dx[d];y+=dy[d];
      if(x===sx&&y===sy)break;
      for(const next of [(d+1)%4,d,(d+3)%4,(d+2)%4]) {
        const i=cell(x,y,next);
        if(i>=0&&(edges[i]&(1<<next))){d=next;break;}
      }
    }while(true);
    offsets.push(vertices.length/2);
  }
  return {vertices:Uint32Array.from(vertices),offsets:Uint32Array.from(offsets),resolution,limited:false};
}

export function paintMapContours(context,model,{x=0,y=0,scale=1,viewport=null}={}) {
  if(!model?.vertices.length)return;
  const {vertices,offsets,resolution}=model;
  context.save();
  try {
    applyWallStyle(context,resolution,scale);
    context.beginPath();
    for(let p=1;p<offsets.length;p++) {
      const start=offsets[p-1],end=offsets[p];
      if(viewport) {
        // Stroke only visible edges. Closing a partially clipped contour
        // would invent a line between unrelated boundary fragments.
        const margin=context.lineWidth;let open=false,complete=true;
        for(let i=start;i<end;i++) {
          const next=i+1<end?i+1:start;
          const ax=x+vertices[i*2]*scale,ay=y+vertices[i*2+1]*scale;
          const bx=x+vertices[next*2]*scale,by=y+vertices[next*2+1]*scale;
          if(Math.max(ax,bx)<-margin||Math.min(ax,bx)>viewport.width+margin
            ||Math.max(ay,by)<-margin||Math.min(ay,by)>viewport.height+margin) {
            open=false;complete=false;continue;
          }
          if(!open)context.moveTo(ax,ay);
          context.lineTo(bx,by);open=true;
        }
        if(complete)context.closePath();
        continue;
      }
      context.moveTo(x+vertices[start*2]*scale,y+vertices[start*2+1]*scale);
      for(let i=start+1;i<end;i++)context.lineTo(x+vertices[i*2]*scale,y+vertices[i*2+1]*scale);
      context.closePath();
    }
    context.stroke();
  }finally {context.restore();}
}
