// Derived viewing geometry only. Never used by navigation or robot map export.
import {cleanDisplayRegions} from './map-regions.js';
import {buildWallEnvelope} from './map-wall-envelope.js';
import {shadeVirtualEnclosures} from './map-virtual-regions.js';
import {repairShortWallGaps} from './map-short-wall-gaps.js';
import {buildMapContours} from './map-architecture.js';
const directions=[[1,0],[1,.25],[1,.5],[1,.75],[1,1],[.75,1],[.5,1],[.25,1],
  [0,1],[-.25,1],[-.5,1],[-.75,1],[-1,1],[-1,.75],[-1,.5],[-1,.25]];

function repairGaps(source,width,height,resolution) {
  const added=new Uint8Array(source.length);
  const inside=(x,y)=>x>=0&&y>=0&&x<width&&y<height;
  function crossSection(x,y,dx,dy) {
    for(let sy=-1;sy<=1;sy++)for(let sx=-1;sx<=1;sx++) {
      if(Math.abs(sx*dx+sy*dy)>.8)continue;
      if(inside(x+sx,y+sy)&&source[(y+sy)*width+x+sx])return true;
    }
    return false;
  }
  function supported(x,y,dx,dy,steps) {
    let hits=0;
    for(let k=0;k<steps;k++) {
      const xx=Math.round(x+dx*k),yy=Math.round(y+dy*k);
      if(!inside(xx,yy))return false;
      if(crossSection(xx,yy,dx,dy))hits++;
    }
    return hits>=Math.ceil(steps*.75);
  }
  for(let index=0;index<source.length;index++) {
    if(!source[index])continue;
    const x=index%width,y=Math.floor(index/width);
    for(const [dx,dy] of directions) {
      const distance=resolution*Math.hypot(dx,dy);
      const gap=Math.min(16,Math.floor(.30/distance+1e-8));
      const support=Math.max(4,Math.min(24,Math.ceil(.35/distance)));
      const nx=Math.round(x+dx),ny=Math.round(y+dy);
      if(!gap || !inside(nx,ny) || crossSection(nx,ny,dx,dy))continue;
      for(let k=2;k<=gap+1;k++) {
        const xx=Math.round(x+dx*k),yy=Math.round(y+dy*k);
        if(!inside(xx,yy))break;
        if(!source[yy*width+xx])continue;
        if(supported(x,y,-dx,-dy,support)&&supported(xx,yy,dx,dy,support)) {
          for(let j=1;j<k;j++)added[Math.round(y+dy*j)*width+Math.round(x+dx*j)]=1;
        }
        break;
      }
    }
  }
  return added;
}

function retainFeatures(source,added,width,height,resolution,protectedPoints) {
  const visited=new Uint8Array(source.length),mask=new Uint8Array(source.length);
  const queue=new Uint32Array(source.length);
  const minimumSpan=Math.max(3,Math.ceil(.20/resolution));
  const protectedAt=(x,y)=>protectedPoints.some(p=>(x-p.x)**2+(y-p.y)**2<=p.radius**2);
  for(let seed=0;seed<source.length;seed++) {
    if(visited[seed]||!(source[seed]||added[seed]))continue;
    let head=0,tail=1,minX=width,maxX=0,minY=height,maxY=0,protectedFeature=false;
    queue[0]=seed;visited[seed]=1;
    while(head<tail) {
      const index=queue[head++],x=index%width,y=Math.floor(index/width);
      minX=Math.min(minX,x);maxX=Math.max(maxX,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y);
      if(!protectedFeature&&protectedPoints.length&&protectedAt(x,y))protectedFeature=true;
      for(let yy=Math.max(0,y-1);yy<=Math.min(height-1,y+1);yy++) {
        for(let xx=Math.max(0,x-1);xx<=Math.min(width-1,x+1);xx++) {
          const next=yy*width+xx;
          if(!visited[next]&&(source[next]||added[next])){visited[next]=1;queue[tail++]=next;}
        }
      }
    }
    const w=maxX-minX+1,h=maxY-minY+1;
    // Keep coherent strokes, attached jambs/corners, and compact tiny objects.
    // Area alone must not erase a narrow wall or a small solid pillar.
    const keep=protectedFeature || (tail>=3&&Math.max(w,h)>=minimumSpan) || (tail>=2&&tail/(w*h)>=.40);
    if(keep)for(let j=0;j<tail;j++)mask[queue[j]]=1;
  }
  return mask;
}

function continuousFloor(rgba,width,height,resolution) {
  const radius=Math.max(1,Math.min(24,Math.round(.15/resolution)));
  const horizontal=new Uint16Array(width*height),floor=new Uint8Array(width*height);
  const free=index=>rgba[index*4]>=250&&rgba[index*4+3]>0?1:0;
  for(let y=0;y<height;y++) {
    const offset=y*width;let count=0;
    for(let x=0;x<=Math.min(width-1,radius);x++)count+=free(offset+x);
    for(let x=0;x<width;x++) {
      horizontal[offset+x]=count;
      if(x-radius>=0)count-=free(offset+x-radius);
      if(x+radius+1<width)count+=free(offset+x+radius+1);
    }
  }
  const sums=new Uint16Array(width),columns=new Uint8Array(width);
  for(let x=0;x<width;x++)columns[x]=Math.min(width-1,x+radius)-Math.max(0,x-radius)+1;
  for(let y=0;y<=Math.min(height-1,radius);y++)
    for(let x=0;x<width;x++)sums[x]+=horizontal[y*width+x];
  for(let y=0;y<height;y++) {
    const rows=Math.min(height-1,y+radius)-Math.max(0,y-radius)+1;
    const row=y*width,remove=(y-radius)*width,add=(y+radius+1)*width;
    for(let x=0;x<width;x++) {
      if(sums[x]>=Math.max(2,Math.ceil(columns[x]*rows*.24)))floor[row+x]=1;
      if(y>=radius)sums[x]-=horizontal[remove+x];
      if(y+radius+1<height)sums[x]+=horizontal[add+x];
    }
  }
  return floor;
}

export function beautifyMap({rgba,width,height,resolution,protectedPoints=[],removeIsolated=false,virtualWalls=[],passagePoints=[]},progress=()=>{}) {
  if(!Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1||width*height>64000000
    ||rgba.length!==width*height*4||!Number.isFinite(resolution)||resolution<=0)throw Error('地图显示数据无效');
  if(!Array.isArray(protectedPoints)||protectedPoints.length>256
    ||protectedPoints.some(p=>![p.x,p.y,p.radius].every(Number.isFinite)||p.radius<0))throw Error('特征保护范围无效');
  const source=new Uint8Array(width*height);let original=0;
  for(let i=0;i<source.length;i++)if(rgba[i*4]<205&&rgba[i*4+3]){source[i]=1;original++;}
  progress('repair');const additions=repairGaps(source,width,height,resolution);
  progress('features');const mask=removeIsolated?retainFeatures(source,additions,width,height,resolution,protectedPoints):source.map((point,i)=>point||additions[i]);
  repairShortWallGaps({rgba,source,mask,width,height,resolution});
  const barriers=buildWallEnvelope({rgba,source,mask,width,height,resolution});
  progress('floor');const floor=continuousFloor(rgba,width,height,resolution);
  progress('regions');const regionStats=cleanDisplayRegions({rgba,mask,barriers,floor,width,height,resolution});
  const virtualStats=shadeVirtualEnclosures({rgba,mask,floor,width,height,resolution,virtualWalls,passagePoints});
  let removedCount=0,addedCount=0;
  for(let i=0;i<mask.length;i++){if(source[i]&&!mask[i])removedCount++;if(mask[i]&&!source[i])addedCount++;}
  // The presentation layer is a floor plan, not a recolored point cloud.
  // Keep mask/evidence intact for QA and raw view, but never pool hidden scan
  // points back over the solid unknown regions at reduced display scales.
  const features=new Uint32Array(),shades=new Uint8Array();
  const removed=new Uint32Array(removedCount),added=new Uint32Array(addedCount);
  const output=new Uint8ClampedArray(rgba.length);
  const floorBits=new Uint8Array(Math.ceil(floor.length/8));
  const floorColor=[255,255,255],unknownColor=[231,236,242];
  progress('render');
  for(let i=0,r=0,a=0;i<mask.length;i++) {
    const color=floor[i]?floorColor:unknownColor;
    if(floor[i])floorBits[i>>3]|=1<<(i&7);
    output[i*4]=color[0];output[i*4+1]=color[1];output[i*4+2]=color[2];output[i*4+3]=rgba[i*4+3];
    if(source[i]&&!mask[i])removed[r++]=i;
    if(mask[i]&&!source[i])added[a++]=i;
  }
  const architecture=buildMapContours({floor,width,height,resolution});
  return {rgba:output,features,shades,removed,added,mask,floor,floorBits,architecture,
    stats:{original,retained:original-removedCount,removed:removedCount,added:addedCount,...regionStats,...virtualStats}};
}
