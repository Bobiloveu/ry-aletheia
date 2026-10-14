// Display inference only: none of these colors are navigation evidence.
export function cleanDisplayRegions({rgba,mask,barriers=mask,floor,width,height,resolution}) {
  const length=width*height,queue=new Uint32Array(length),seen=new Uint8Array(length);
  const open=i=>!mask[i]&&rgba[i*4+3]>0;
  const observed=i=>rgba[i*4]>=250&&rgba[i*4+3]>0;
  const radius=Math.max(1,Math.min(24,Math.round(.15/resolution)));
  let head=0,tail=0;
  for(let i=0;i<length;i++) {
    if(!open(i))floor[i]=0;
    // Real white observations are seeds, even when too sparse for the density
    // window. Only the subsequent unknown-region judgement may grey them.
    if(open(i)&&observed(i)){floor[i]=1;seen[i]=1;}
  }
  // A density window may see white on the other side of a wall. Require
  // a short, wall-free path to an actual white observation as well.
  const extend=(j,distance)=>{if(floor[j]&&!seen[j]){seen[j]=distance;queue[tail++]=j;}};
  // Only uncertain cells need distance propagation. Enqueuing every observed
  // pixel made a mostly-white map traverse its entire floor a second time.
  for(let i=0;i<length;i++)if(floor[i]&&!seen[i]) {
    const x=i%width;
    if(x>0&&seen[i-1]===1||x+1<width&&seen[i+1]===1
      ||i>=width&&seen[i-width]===1||i+width<length&&seen[i+width]===1) {
      seen[i]=2;queue[tail++]=i;
    }
  }
  while(head<tail) {
    const i=queue[head++],x=i%width;
    if(seen[i]>radius)continue;
    const distance=seen[i]+1;
    if(x>0)extend(i-1,distance);if(x+1<width)extend(i+1,distance);
    if(i>=width)extend(i-width,distance);if(i+width<length)extend(i+width,distance);
  }
  for(let i=0;i<length;i++)if(!seen[i])floor[i]=0;

  function flood(seed,eligible) {
    let head=0,tail=1;queue[0]=seed;seen[seed]=1;
    const add=i=>{if(!seen[i]&&eligible(i)){seen[i]=1;queue[tail++]=i;}};
    while(head<tail) {
      const i=queue[head++],x=i%width;
      if(x>0)add(i-1);if(x+1<width)add(i+1);
      if(i>=width)add(i-width);if(i+width<length)add(i+width);
    }
    return tail;
  }
  const touchesEdge=i=>i<width||i>=length-width||i%width===0||i%width===width-1
    ||!rgba[(i-1)*4+3]||!rgba[(i+1)*4+3]||!rgba[(i-width)*4+3]||!rgba[(i+width)*4+3];
  const unknown=i=>open(i)&&!floor[i];
  const majorityUnknown=new Uint8Array(length);
  let majorityRegions=0,unifiedUnknown=0;
  seen.fill(0);
  const regionOpen=i=>!barriers[i]&&rgba[i*4+3]>0;
  for(let seed=0;seed<length;seed++) {
    if(seen[seed]||!regionOpen(seed))continue;
    const count=flood(seed,regionOpen);
    let exterior=false,unknownCount=0;
    for(let j=0;j<count;j++) {
      const i=queue[j];
      if(touchesEdge(i)){exterior=true;break;}
      if(!observed(i))unknownCount++;
    }
    if(exterior||unknownCount*2<count)continue;
    majorityRegions++;
    for(let j=0;j<count;j++)majorityUnknown[queue[j]]=1;
  }
  // Preserve independently observed narrow strokes, even inside a larger
  // unknown enclosure. They can be corridors whose end walls were not scanned.
  const corridorFloor=new Uint8Array(length);
  seen.fill(0);
  for(let seed=0;seed<length;seed++) {
    // Corridor exceptions matter only for components that intersect a region
    // actually eligible for greying. Skip the unrelated exterior white ocean.
    if(seen[seed]||!floor[seed]||!majorityUnknown[seed])continue;
    const count=flood(seed,i=>floor[i]);
    let raw=0,sx=0,sy=0,sxx=0,syy=0,sxy=0;
    for(let j=0;j<count;j++) {
      const i=queue[j],x=i%width,y=Math.floor(i/width);
      if(observed(i))raw++;sx+=x;sy+=y;sxx+=x*x;syy+=y*y;sxy+=x*y;
    }
    const xx=sxx/count-(sx/count)**2,yy=syy/count-(sy/count)**2,xy=sxy/count-sx*sy/(count*count);
    const trace=xx+yy,delta=Math.hypot(xx-yy,2*xy);
    if(raw>=count*.8&&trace+delta>=4*Math.max(1,trace-delta)) {
      const angle=.5*Math.atan2(2*xy,xx-yy),nx=-Math.sin(angle),ny=Math.cos(angle),sides=[0,0];
      for(let j=0;j<count;j++) {
        const i=queue[j],x=i%width;
        if(x>0&&mask[i-1]&&Math.abs(nx)>.5)sides[nx>0?0:1]++;
        if(x+1<width&&mask[i+1]&&Math.abs(nx)>.5)sides[nx>0?1:0]++;
        if(i>=width&&mask[i-width]&&Math.abs(ny)>.5)sides[ny>0?0:1]++;
        if(i+width<length&&mask[i+width]&&Math.abs(ny)>.5)sides[ny>0?1:0]++;
      }
      const flankSupport=Math.max(4,Math.sqrt(6*(trace+delta))*.4);
      if(sides.every(n=>n>=flankSupport))for(let j=0;j<count;j++)corridorFloor[queue[j]]=1;
    }
  }
  for(let i=0;i<length;i++)if(majorityUnknown[i]) {
    if(corridorFloor[i])majorityUnknown[i]=0;
    else {if(floor[i])unifiedUnknown++;floor[i]=0;}
  }
  let filledUnknown=0;
  const maximumHoleArea=1/(resolution*resolution);
  seen.fill(0);
  for(let seed=0;seed<length;seed++) {
    if(seen[seed]||!unknown(seed))continue;
    const count=flood(seed,unknown);
    if(count>maximumHoleArea)continue;
    let edge=false,whiteBoundary=0,wallBoundary=0;
    const inspect=i=>{if(floor[i])whiteBoundary++;else if(mask[i])wallBoundary++;};
    for(let j=0;j<count&&!edge;j++) {
      const i=queue[j],x=i%width;edge=touchesEdge(i);
      if(x>0)inspect(i-1);if(x+1<width)inspect(i+1);
      if(i>=width)inspect(i-width);if(i+width<length)inspect(i+width);
    }
    // A room bounded only by walls has no white evidence. Do not fill it.
    if(!edge&&whiteBoundary>=4&&whiteBoundary>=wallBoundary&&!queue.subarray(0,count).some(i=>majorityUnknown[i])) {
      for(let j=0;j<count;j++)floor[queue[j]]=1;
      filledUnknown+=count;
    }
  }
  return {filledUnknown,unifiedUnknown,majorityRegions};
}
