import {visitMapComponents} from './map-components.js';
// Saved virtual walls partition the viewing raster only. They never enter the
// physical obstacle mask or the robot's PGM. Manual erases are painted later.
export function shadeVirtualEnclosures({rgba,mask,floor,width,height,resolution=.05,virtualWalls=[],passagePoints=[]}) {
  if(!virtualWalls.length)return {closedVirtualRegions:0,virtualGreyPixels:0};
  const length=width*height,cuts=new Uint8Array(length);
  const radius=Math.max(0,Math.min(8,Math.floor(.10/resolution+1e-8)));
  function segment(a,b) {
    if(!a||!b||![a.x,a.y,b.x,b.y].every(Number.isFinite))return;
    const dx=b.x-a.x,dy=b.y-a.y;
    if(!Number.isFinite(dx)||!Number.isFinite(dy))return;
    // Clip before rasterization so far-away endpoints cannot produce an
    // unbounded loop, and walls entering the image still partition correctly.
    let lo=0,hi=1;
    // Map world bounds include x=width/y=height. Those legal boundary lines
    // cover the outermost cells, rather than being discarded by clipping.
    for(const [p,q] of [[-dx,a.x],[dx,width-a.x],[-dy,a.y],[dy,height-a.y]]) {
      if(p===0){if(q<0)return;continue;}
      const t=q/p;if(p<0)lo=Math.max(lo,t);else hi=Math.min(hi,t);
      if(lo>hi)return;
    }
    const x0=a.x+lo*dx,y0=a.y+lo*dy,x1=a.x+hi*dx,y1=a.y+hi*dy;
    const steps=Math.max(1,Math.ceil(Math.max(Math.abs(x1-x0),Math.abs(y1-y0))));
    const put=(x,y)=>{x=Math.max(0,Math.min(width-1,x));y=Math.max(0,Math.min(height-1,y));cuts[y*width+x]=1;};
    let px=Math.round(x0),py=Math.round(y0);put(px,py);
    for(let step=1;step<=steps;step++) {
      const x=Math.round(x0+(x1-x0)*step/steps),y=Math.round(y0+(y1-y0)*step/steps);
      if(x!==px&&y!==py){put(px,y);put(x,py);}
      put(x,y);px=x;py=y;
    }
  }
  for(const wall of virtualWalls)for(let i=1;i<(wall.points?.length||0);i++)segment(wall.points[i-1],wall.points[i]);
  if(!cuts.some(Boolean))return {closedVirtualRegions:0,virtualGreyPixels:0};
  // A manually drawn endpoint can miss a thin wall by a couple of cells.
  // Snap the partition to nearby physical support, without painting obstacles.
  for(const wall of virtualWalls)for(const p of wall.points||[]) {
    if(!p||![p.x,p.y].every(Number.isFinite))continue;
    const px=Math.round(p.x),py=Math.round(p.y);let nearest=null,distance=Infinity;
    for(let y=Math.max(0,py-radius);y<=Math.min(height-1,py+radius);y++)
      for(let x=Math.max(0,px-radius);x<=Math.min(width-1,px+radius);x++) {
        const d=(x-px)**2+(y-py)**2;
        if(mask[y*width+x]&&d<=radius**2&&d<distance){nearest={x,y};distance=d;}
      }
    if(nearest)segment(p,nearest);
  }
  const topology=boxMask(boxMask(mask,width,height,radius),width,height,radius,true);
  const regions=[null];
  const open=i=>!mask[i]&&!topology[i]&&!cuts[i]&&rgba[i*4+3]>0;
  const labels=visitMapComponents({width,height,open,
    begin:()=>regions.push({exterior:false,physicalBoundary:0,virtualBoundary:0,grey:false}),
    span:(label,left,right,componentLabels)=>{
      const region=regions[label];
      if(region.exterior)return;
      const inspect=i=>{
        if(componentLabels[i]===label)return;
        if(!rgba[i*4+3])region.exterior=true;
        else if(mask[i]||topology[i])region.physicalBoundary++;
        else if(cuts[i])region.virtualBoundary++;
      };
      if(left%width===0)region.exterior=true;else inspect(left-1);
      if(right%width===width-1)region.exterior=true;else inspect(right+1);
      if(left<width||right>=length-width)region.exterior=true;
      if(region.exterior)return;
      for(let i=left;i<=right;i++) {
        if(i>=width)inspect(i-width);
        if(i+width<length)inspect(i+width);
      }
    },
  });
  // Geometry can fill a truly closed space. Observed-floor connectivity must
  // separately prevent unknown cells from joining rooms around their walls.
  const cutBand=boxMask(cuts,width,height,radius),areas=[null];
  const observedOpen=i=>floor[i]&&!mask[i]&&!topology[i]&&!cutBand[i]&&rgba[i*4+3]>0;
  const observed=visitMapComponents({width,height,open:observedOpen,
    begin:(label,seed)=>areas.push({size:0,geometry:labels[seed],edge:false,boundary:0,wallBoundary:0,score:0}),
    span:(label,left,right,componentLabels)=>{
      const area=areas[label];area.size+=right-left+1;
      const inspect=j=>{
        if(componentLabels[j]===label)return;
        area.boundary++;
        if(!rgba[j*4+3])area.edge=true;
        if(rgba[j*4+3]>0&&(mask[j]||topology[j]||cutBand[j]))area.wallBoundary++;
      };
      if(left%width>0)inspect(left-1);else {area.boundary++;area.edge=true;}
      if(right%width+1<width)inspect(right+1);else {area.boundary++;area.edge=true;}
      for(let i=left;i<=right;i++) {
        if(i>=width)inspect(i-width);else {area.boundary++;area.edge=true;}
        if(i+width<length)inspect(i+width);else {area.boundary++;area.edge=true;}
      }
    },
  });
  for(let i=1;i<areas.length;i++) {
    const area=areas[i];area.score=area.size*(1+area.wallBoundary/Math.max(1,area.boundary));
  }
  // Only unusual starts covered by analysis walls or unknown holes need a
  // per-cell search queue; ordinary starts use their component directly.
  let queue;
  const keep=new Set(),keepGeometry=new Set(),startCells=new Set();
  for(const p of passagePoints) {
    if(!p||!Number.isFinite(p.x)||!Number.isFinite(p.y))continue;
    const x=Math.round(p.x),y=Math.round(p.y);
    if(x<0||x>=width||y<0||y>=height)continue;
    let index=y*width+x,geometry=labels[index];
    if(!geometry&&!mask[index]&&!cuts[index]&&rgba[index*4+3]>0) {
      // Closing a tiny gap may cover a valid start. Recover nearby geometry
      // through original open cells, never across a physical or virtual wall.
      queue ||= new Uint32Array(length);
      const seen=new Set([index]);let head=0,tail=1;queue[0]=index;
      while(head<tail) {
        const i=queue[head++],xx=i%width,yy=Math.floor(i/width);
        if(labels[i]){geometry=labels[i];index=i;break;}
        const visit=j=>{
          if(!seen.has(j)&&!mask[j]&&!cuts[j]&&rgba[j*4+3]>0
            &&Math.abs(j%width-x)+Math.abs(Math.floor(j/width)-y)<=radius*2+1) {
            seen.add(j);queue[tail++]=j;
          }
        };
        if(xx>0)visit(i-1);if(xx+1<width)visit(i+1);
        if(yy>0)visit(i-width);if(yy+1<height)visit(i+width);
      }
      if(geometry&&floor[y*width+x])startCells.add(y*width+x);
    }
    if(geometry&&!regions[geometry].exterior)keepGeometry.add(geometry);
    if(observed[index])keep.add(observed[index]);
    else if(geometry) {
      // A start may land on a local unknown hole. Find the nearest observed
      // floor through this geometry, rather than a larger room via unknown sea.
      queue ||= new Uint32Array(length);
      const seen=new Uint8Array(length);let head=0,tail=1;
      seen[index]=1;queue[0]=index;
      while(head<tail) {
        const i=queue[head++],x=i%width;
        if(observed[i]){keep.add(observed[i]);break;}
        const visit=j=>{if(!seen[j]&&labels[j]===geometry){seen[j]=1;queue[tail++]=j;}};
        if(x>0)visit(i-1);if(x+1<width)visit(i+1);
        if(i>=width)visit(i-width);if(i+width<length)visit(i+width);
      }
    }
  }
  if(!keep.size&&!keepGeometry.size) {
    // Choose actual observed circulation, not a tiny sealed cavity merely
    // because the main corridor has a small leak into exterior unknown.
    let best=0;
    for(let i=1;i<areas.length;i++)if(areas[i].score>(areas[best]?.score||0))best=i;
    if(best&&regions[areas[best].geometry].exterior) {
      // A black-white PGM can contain a huge unbounded white background.
      // Prefer a substantial, manually enclosed circulation space. Do not
      // promote tiny sealed objects over a real open outdoor passage.
      const minimum=4/(resolution*resolution);
      let enclosed=0,score=0;
      for(let i=1;i<areas.length;i++) {
        const area=areas[i],region=regions[area.geometry];
        if(region.exterior||!region.virtualBoundary||area.size<minimum)continue;
        const value=area.score*(1+region.virtualBoundary/Math.max(1,region.physicalBoundary+region.virtualBoundary));
        if(value>score){enclosed=i;score=value;}
      }
      // A deliberate enclosure needs appreciable manual boundary support.
      // Judge the strongest bounded candidate before this check: otherwise a
      // small heavily capped object could displace a larger outdoor passage.
      // This local ratio does not grow with unrelated white image padding.
      if(enclosed) {
        const region=regions[areas[enclosed].geometry];
        const support=area=>area.wallBoundary/Math.max(1,area.boundary);
        // A closure is stronger evidence than unbounded white padding, but
        // not than an outdoor passage already bordered almost entirely by
        // real walls. Require a material gain in observed boundary support.
        if(region.virtualBoundary*4>=region.physicalBoundary
          &&support(areas[enclosed])-support(areas[best])>=.1)best=enclosed;
      }
    }
    if(best)keep.add(best);
  }
  for(const i of keep)if(!regions[areas[i].geometry]?.exterior)keepGeometry.add(areas[i].geometry);
  let closedVirtualRegions=0,virtualGreyPixels=0,virtualWhitePixels=0;
  for(let i=1;i<regions.length;i++)if(!keepGeometry.has(i)&&!regions[i].exterior) {
    regions[i].grey=true;closedVirtualRegions++;
  }
  for(let i=0;i<length;i++) {
    const before=floor[i];
    floor[i]=!mask[i]&&!cuts[i]&&(keepGeometry.has(labels[i])||keep.has(observed[i])||startCells.has(i))?1:0;
    if(before&&!floor[i])virtualGreyPixels++;
    if(!before&&floor[i])virtualWhitePixels++;
  }
  return {closedVirtualRegions,virtualGreyPixels,virtualWhitePixels};
}

// Separable square dilation/erosion: O(pixels), with bounded scratch storage.
// Outside-image cells are empty so edge-touching walls cannot create land.
function boxMask(source,width,height,radius,erode=false) {
  if(!radius)return source.slice();
  const horizontal=new Uint16Array(source.length),output=new Uint8Array(source.length);
  for(let y=0;y<height;y++) {
    const offset=y*width;let sum=0;
    for(let x=0;x<=Math.min(radius,width-1);x++)sum+=source[offset+x];
    for(let x=0;x<width;x++) {
      horizontal[offset+x]=sum;
      if(x>=radius)sum-=source[offset+x-radius];
      if(x+radius+1<width)sum+=source[offset+x+radius+1];
    }
  }
  const full=(radius*2+1)**2;
  // Keep both passes in row order. A column-stride sweep repeatedly misses
  // cache lines on tall maps, despite doing the same number of operations.
  const sums=new Uint16Array(width);
  for(let y=0;y<=Math.min(radius,height-1);y++)
    for(let x=0;x<width;x++)sums[x]+=horizontal[y*width+x];
  for(let y=0;y<height;y++) {
    const row=y*width,remove=(y-radius)*width,add=(y+radius+1)*width;
    for(let x=0;x<width;x++) {
      output[row+x]=(erode?sums[x]===full:sums[x]>0)?1:0;
      if(y>=radius)sums[x]-=horizontal[remove+x];
      if(y+radius+1<height)sums[x]+=horizontal[add+x];
    }
  }
  return output;
}
