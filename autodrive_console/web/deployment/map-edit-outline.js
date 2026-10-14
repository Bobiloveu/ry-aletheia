import {buildMapContours,paintMapContours} from './map-architecture.js';
import {eraseEditsForRender,paintEraseOperation} from './erase-preview.js';
import {mapPointToCanvas} from './canvas-geometry.js';

// Rebuild only edited tiles from semantic floor bits. Sampling the outlined
// bitmap would mistake its antialiased wall pixels for unknown cells.
export function buildEditedMapTile({floorBits,map,x,y,width,height,erase}) {
  const floor=new Uint8Array(width*height),rgba=new Uint8ClampedArray(width*height*4);
  for(let row=0;row<height;row++)for(let col=0;col<width;col++) {
    const i=row*width+col,source=(y+row)*map.width+x+col;
    floor[i]=erase[i*4+3]>=128 ? (erase[i*4]>=128 ? 1 : 0) : (floorBits[source>>3]>>(source&7))&1;
    rgba[i*4]=floor[i]?255:231;rgba[i*4+1]=floor[i]?255:236;
    rgba[i*4+2]=floor[i]?255:242;rgba[i*4+3]=255;
  }
  return {floor,rgba,architecture:buildMapContours({floor,width,height,resolution:map.resolution_m})};
}

function segmentIntersects(a,b,left,top,right,bottom) {
  let from=0,to=1;
  for(const [start,delta,min,max] of [[a.x,b.x-a.x,left,right],[a.y,b.y-a.y,top,bottom]]) {
    if(!delta){if(start<min||start>max)return false;continue;}
    const first=(min-start)/delta,last=(max-start)/delta;
    from=Math.max(from,Math.min(first,last));to=Math.min(to,Math.max(first,last));
    if(from>to)return false;
  }
  return true;
}
function intersectsTile(group,left,top,right,bottom,halo) {
  const {points,radius,edit}=group;
  left-=halo+radius;top-=halo+radius;right+=halo+radius;bottom+=halo+radius;
  if(edit.kind==='brush_erase')return segmentIntersects(points[0],points.at(-1),left,top,right,bottom);
  // Polygon edges crossing the tile, or a tile entirely inside the polygon.
  let winding=0;
  for(let i=0,j=points.length-1;i<points.length;j=i++) {
    const a=points[j],b=points[i];
    if(segmentIntersects(a,b,left,top,right,bottom))return true;
    const cross=(b.x-a.x)*(top-a.y)-(left-a.x)*(b.y-a.y);
    if(a.y<=top){if(b.y>top&&cross>0)winding++;}
    else if(b.y<=top&&cross<0)winding--;
  }
  return winding!==0;
}

export function createMapEditOutline(document) {
  const tileSize=256,halo=2;
  let bits=null,key='',baseKey='',patches=[],cache=new Map();
  function clear(){bits=null;key=baseKey='';patches=[];cache.clear();}
  function paint({context,floorBits,map,view,edits=[],canvasBox=null}) {
    if(!floorBits)return false;
    const selected=eraseEditsForRender({savedEdits:edits,activeMapId:map.id});
    const nextBaseKey=JSON.stringify([map.id,map.width,map.height,map.origin,map.resolution_m]);
    const nextKey=JSON.stringify(selected);
    if(bits!==floorBits||baseKey!==nextBaseKey||key!==nextKey) {
      if(bits!==floorBits||baseKey!==nextBaseKey)cache.clear();
      const nativeView={x:0,y:0,scale:1/map.resolution_m};
      // Split strokes so appending a sample only invalidates the tail tiles.
      // Square brushes deliberately stamp points rather than connect them.
      const operations=[];
      for(const edit of selected) {
        const points=edit.points||[];
        if(edit.kind==='brush_erase'&&points.length>1) {
          if(edit.shape==='square')for(const point of points)operations.push({...edit,points:[point]});
          else for(let i=1;i<points.length;i++)operations.push({...edit,points:points.slice(i-1,i+1)});
        }else if(points.length)operations.push(edit);
      }
      const bounded=operations.map(edit=>{
        const points=(edit.points||[]).map(p=>mapPointToCanvas(p,map,nativeView));
        if(!points.length)return null;
        const radius=edit.kind==='brush_erase'?Number(edit.radius_m||.4)/map.resolution_m:0;
        let left=Infinity,top=Infinity,right=-Infinity,bottom=-Infinity;
        for(const p of points){left=Math.min(left,p.x-radius);top=Math.min(top,p.y-radius);right=Math.max(right,p.x+radius);bottom=Math.max(bottom,p.y+radius);}
        return {edit,points,radius,signature:JSON.stringify(edit),left:Math.max(0,Math.floor(left)-halo),top:Math.max(0,Math.floor(top)-halo),
          right:Math.min(map.width,Math.ceil(right)+halo),bottom:Math.min(map.height,Math.ceil(bottom)+halo)};
      }).filter(b=>b&&b.left<b.right&&b.top<b.bottom);
      const tiles=new Map();
      for(const b of bounded)for(let ty=Math.floor(b.top/tileSize);ty<=Math.floor((b.bottom-1)/tileSize);ty++)
        for(let tx=Math.floor(b.left/tileSize);tx<=Math.floor((b.right-1)/tileSize);tx++) {
          if(!intersectsTile(b,tx*tileSize,ty*tileSize,(tx+1)*tileSize,(ty+1)*tileSize,halo))continue;
          const id=`${tx},${ty}`;
          if(!tiles.has(id))tiles.set(id,{tx,ty,groups:[]});
          tiles.get(id).groups.push(b);
        }
      const next=[],nextCache=new Map();
      for(const [id,{tx,ty,groups}] of tiles) {
        const signature=JSON.stringify(groups.map(g=>g.signature)),cached=cache.get(id);
        if(cached?.signature===signature){next.push(cached.patch);nextCache.set(id,cached);continue;}
        const left=tx*tileSize,top=ty*tileSize,right=Math.min(map.width,left+tileSize),bottom=Math.min(map.height,top+tileSize);
        const x=Math.max(0,left-halo),y=Math.max(0,top-halo);
        const width=Math.min(map.width,right+halo)-x,height=Math.min(map.height,bottom+halo)-y;
        const surface=document.createElement('canvas');surface.width=width;surface.height=height;
        const ctx=surface.getContext('2d',{willReadFrequently:true});
        for(const b of groups)
          paintEraseOperation(ctx,b.edit,{map,view:{x:-x,y:-y,scale:nativeView.scale}});
        const erase=ctx.getImageData(0,0,width,height).data;
        const result=buildEditedMapTile({floorBits,map,x,y,width,height,erase});
        const output=ctx.createImageData(width,height);output.data.set(result.rgba);ctx.putImageData(output,0,0);
        paintMapContours(ctx,result.architecture);
        const patch={surface,architecture:result.architecture,x,y,left,top,width:right-left,height:bottom-top};
        next.push(patch);nextCache.set(id,{signature,patch});
      }
      bits=floorBits;key=nextKey;baseKey=nextBaseKey;patches=next;cache=nextCache;
    }
    const scale=view.scale*map.resolution_m;
    context.save();
    try {
      context.imageSmoothingEnabled=true;
      for(const p of patches) {
        const x=view.x+p.left*scale,y=view.y+p.top*scale,w=p.width*scale,h=p.height*scale;
        if(canvasBox&&(x+w<0||y+h<0||x>canvasBox.width||y>canvasBox.height))continue;
        context.drawImage(p.surface,p.left-p.x,p.top-p.y,p.width,p.height,x,y,w,h);
        if(scale>1) {
          context.save();
          try {
            context.beginPath();context.rect(x,y,w,h);context.clip();
            paintMapContours(context,p.architecture,{x:view.x+p.x*scale,y:view.y+p.y*scale,scale,viewport:canvasBox});
          }finally{context.restore();}
        }
      }
    }finally{context.restore();}
    return true;
  }
  return {paint,clear};
}
