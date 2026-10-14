// Display-only planning. No task poses, navigation settings or robot files are modified.
import {passageLocal,passageIntersection} from './route-passages.js';
const SQRT2=Math.SQRT2;
const distance=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);
const mix=(a,b,t)=>({x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t});

// Exact squared Euclidean distance transform, separable in O(width*height).
function clearanceField(blocked,width,height) {
  const values=new Float64Array(width*height),size=Math.max(width,height);
  const f=new Float64Array(size),d=new Float64Array(size),v=new Int32Array(size),z=new Float64Array(size+1);
  const transform=n=>{
    let k=0;v[0]=0;z[0]=-Infinity;z[1]=Infinity;
    for(let q=1;q<n;q++) {
      let s=((f[q]+q*q)-(f[v[k]]+v[k]*v[k]))/(2*q-2*v[k]);
      while(s<=z[k]) {k--;s=((f[q]+q*q)-(f[v[k]]+v[k]*v[k]))/(2*q-2*v[k]);}
      k++;v[k]=q;z[k]=s;z[k+1]=Infinity;
    }
    k=0;for(let q=0;q<n;q++){while(z[k+1]<q)k++;d[q]=(q-v[k])**2+f[v[k]];}
  };
  for(let y=0;y<height;y++) {
    for(let x=0;x<width;x++)f[x]=blocked[y*width+x]?0:1e12;
    transform(width);for(let x=0;x<width;x++)values[y*width+x]=d[x];
  }
  const result=new Float32Array(width*height);
  for(let x=0;x<width;x++) {
    for(let y=0;y<height;y++)f[y]=values[y*width+x];
    transform(height);
    for(let y=0;y<height;y++)result[y*width+x]=Math.max(0,Math.min(Math.sqrt(d[y])-SQRT2/2,x+.5,width-x-.5,y+.5,height-y-.5));
  }
  return result;
}
function clipLine(a,b,width,height) {
  let lo=0,hi=1;
  for(const [start,delta,max] of [[a.x,b.x-a.x,width-.001],[a.y,b.y-a.y,height-.001]]) {
    if(!delta){if(start<0||start>max)return null;continue;}
    const p=-start/delta,q=(max-start)/delta;
    lo=Math.max(lo,Math.min(p,q));hi=Math.min(hi,Math.max(p,q));
  }
  return lo>hi?null:[mix(a,b,lo),mix(a,b,hi)];
}
export function buildRouteGrid({rgba,width,height,map,virtualWalls=[],radiusM=.39,maxCells=900000}) {
  if(!map||!(map.resolution_m>0)||!Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1||width*height>64000000||rgba?.length!==width*height*4||!(maxCells>=1))throw Error('路线预览缺少有效地图数据');
  let factor=Math.max(1,Math.ceil(Math.sqrt(width*height/maxCells)));
  while(Math.ceil(width/factor)*Math.ceil(height/factor)>maxCells)factor++;
  const w=Math.ceil(width/factor),h=Math.ceil(height/factor),resolution=map.resolution_m*factor;
  const blocked=new Uint8Array(w*h),unknown=new Uint8Array(w*h);
  // Scan row blocks without dividing each source pixel into a target column.
  // Once a pooled cell is blocked, further pixels cannot make it traversable.
  for(let y=0;y<height;y++) {
    let i=Math.floor(y/factor)*w;
    const end=(y+1)*width*4,step=factor*4;
    for(let source=y*width*4;source<end;source+=step,i++) {
      if(blocked[i])continue;
      const limit=Math.min(end,source+step);
      for(let p=source;p<limit;p+=4) {
        // Unknown remains a penalized display approximation, matching the
        // existing binary preview; it is not verified physical free space.
        if(rgba[p+3]<128||rgba[p]<205){blocked[i]=1;break;}
        if(rgba[p]===205)unknown[i]=1;
      }
    }
  }
  const origin=map.origin||[0,0,0],c=Math.cos(origin[2]||0),s=Math.sin(origin[2]||0);
  const raster=p=>({x:((p.x-origin[0])*c+(p.y-origin[1])*s)/resolution,
    y:(height*map.resolution_m-(-(p.x-origin[0])*s+(p.y-origin[1])*c))/resolution});
  const world=(x,y)=>{
    const localX=(x+.5)*resolution,localY=height*map.resolution_m-(y+.5)*resolution;
    return {x:origin[0]+c*localX-s*localY,y:origin[1]+s*localX+c*localY};
  };
  for(const wall of virtualWalls) {
    const points=wall.points||[wall.start,wall.end];
    for(let k=1;k<points.length;k++) {
      if(![points[k-1],points[k]].every(p=>Number.isFinite(p?.x)&&Number.isFinite(p?.y)))continue;
      const line=clipLine(raster(points[k-1]),raster(points[k]),w,h);if(!line)continue;
      const [a,b]=line,count=Math.max(1,Math.ceil(Math.hypot(b.x-a.x,b.y-a.y)*3));
      for(let j=0;j<=count;j++) {const p=mix(a,b,j/count);blocked[Math.floor(p.y)*w+Math.floor(p.x)]=1;}
    }
  }
  const clear=clearanceField(blocked,w,h),radius=Math.max(0,Number(radiusM)||0);
  const cost=new Float32Array(w*h);
  for(let i=0;i<cost.length;i++) {
    clear[i]*=resolution;
    cost[i]=blocked[i]||clear[i]+1e-6<radius?Infinity:1+5*Math.exp(-Math.max(0,clear[i]-radius)/.65)+unknown[i]*.25;
  }
  const index=p=>{const r=raster(p),x=Math.floor(r.x),y=Math.floor(r.y);return r.x<0||r.y<0||r.x>=width/factor||r.y>=height/factor?-1:y*w+x;};
  return {width:w,height:h,resolution,raster,world,index,cost,clearance:clear,radius,
    usable:p=>{const i=index(p);return i>=0&&Number.isFinite(cost[i]);}};
}
class Heap {
  values=[];
  push(id,score) {
    const a=this.values;let i=a.length;a.push({id,score});
    while(i){const p=(i-1)>>1;if(a[p].score<=score)break;a[i]=a[p];i=p;}a[i]={id,score};
  }
  pop() {
    const a=this.values,first=a[0],last=a.pop();if(!a.length)return first;
    let i=0;while(i*2+1<a.length){let child=i*2+1;if(child+1<a.length&&a[child+1].score<a[child].score)child++;
      if(a[child].score>=last.score)break;a[i]=a[child];i=child;}a[i]=last;return first;
  }
}
function segmentCost(grid,a,b) {
  if(grid.segmentAllowed&&!grid.segmentAllowed(a,b))return Infinity;
  const n=Math.max(1,Math.ceil(distance(a,b)/(grid.resolution*.25)));let sum=0;
  for(let j=0;j<=n;j++) {const p=mix(a,b,j/n),i=grid.index(p);if(i<0||!Number.isFinite(grid.cost[i]))return Infinity;sum+=grid.cost[i];}
  return distance(a,b)*sum/(n+1);
}
function simplify(grid,points) {
  if(points.length<3)return points;
  const cumulative=[0];for(let i=1;i<points.length;i++)cumulative.push(cumulative.at(-1)+segmentCost(grid,points[i-1],points[i]));
  const result=[points[0]];
  for(let i=0;i<points.length-1;) {
    let chosen=i+1;
    for(let j=i+2;j<points.length&&distance(points[i],points[j])<=5;j++) {
      const direct=segmentCost(grid,points[i],points[j]);
      if(Number.isFinite(direct)&&direct<=(cumulative[j]-cumulative[i])*1.025)chosen=j;
    }
    result.push(points[chosen]);i=chosen;
  }
  return result;
}
function roundCorners(grid,points) {
  if(points.length<3)return points;
  const result=[points[0]];
  for(let i=1;i<points.length-1;i++) {
    const a=points[i-1],b=points[i],c=points[i+1],ab=distance(a,b),bc=distance(b,c);
    const trim=Math.min(.65,ab*.32,bc*.32);
    if(trim<.03){result.push(b);continue;}
    // A straight run needs no arc samples. Keep collision checks even for
    // almost-collinear joins so compression never cuts a narrow wall corner.
    // Bound each chord: repeatedly scanning a growing straight run would make
    // compression quadratic on long corridors, outside the A* work budget.
    const cross=Math.abs((b.x-a.x)*(c.y-b.y)-(b.y-a.y)*(c.x-b.x))/(ab*bc);
    const dot=((b.x-a.x)*(c.x-b.x)+(b.y-a.y)*(c.y-b.y))/(ab*bc);
    if(dot>0&&cross*trim<.0025&&distance(result.at(-1),c)<=10&&Number.isFinite(segmentCost(grid,result.at(-1),c)))continue;
    const entry=mix(b,a,trim/ab),exit=mix(b,c,trim/bc),curve=[entry];
    // Subdivide by curvature rather than arc length. Long gentle bends no
    // longer produce dozens of indistinguishable points at every redraw.
    const tolerance=Math.min(.015,grid.resolution*.2);
    const sample=(a,b,c,depth=0)=>{
      const ab=mix(a,b,.5),bc=mix(b,c,.5),mid=mix(ab,bc,.5);
      if(depth<8&&distance(mid,mix(a,c,.5))>tolerance){sample(a,ab,mid,depth+1);sample(mid,bc,c,depth+1);}
      else curve.push(c);
    };
    sample(entry,b,exit);
    const sequence=[result.at(-1),...curve,c];
    if(sequence.slice(1).every((p,j)=>Number.isFinite(segmentCost(grid,sequence[j],p))))result.push(...curve);
    else result.push(b);
  }
  result.push(points.at(-1));return result;
}
export function findRoutePath(grid,start,end,{maxExpansions=250000}={}) {
  const fail=reason=>({status:'blocked',points:[],reason});
  if(!grid.usable(start)||!grid.usable(end))return fail('标记靠近障碍或位于地图外，请检查位置与通行宽度');
  if(distance(start,end)<1e-8)return {status:'ready',points:[{x:start.x,y:start.y}],length_m:0};
  const from=grid.index(start),goal=grid.index(end),w=grid.width,n=grid.cost.length;
  const scores=new Float64Array(n);scores.fill(Infinity);scores[from]=0;
  const parent=new Int32Array(n);parent.fill(-1);const closed=new Uint8Array(n),heap=new Heap();
  const gx=goal%w,gy=Math.floor(goal/w),heuristic=i=>Math.hypot(i%w-gx,Math.floor(i/w)-gy);
  heap.push(from,heuristic(from));let expanded=0,found=false;
  while(heap.values.length) {
    const i=heap.pop().id;if(closed[i])continue;
    if(i===goal){found=true;break;}closed[i]=1;
    if(++expanded>maxExpansions)return fail('路线计算达到预览上限，请缩小地图范围或增加过渡点');
    const x=i%w,y=Math.floor(i/w);
    for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++) {
      if(!dx&&!dy||x+dx<0||y+dy<0||x+dx>=w||y+dy>=grid.height)continue;
      const next=i+dy*w+dx;if(closed[next]||!Number.isFinite(grid.cost[next]))continue;
      if(dx&&dy&&(!Number.isFinite(grid.cost[i+dx])||!Number.isFinite(grid.cost[i+dy*w])))continue;
      if(grid.segmentAllowed&&!grid.segmentAllowed(i===from?start:grid.world(x,y),next===goal?end:grid.world(x+dx,y+dy)))continue;
      const value=scores[i]+(dx&&dy?SQRT2:1)*(grid.cost[i]+grid.cost[next])/2;
      if(value>=scores[next])continue;scores[next]=value;parent[next]=i;heap.push(next,value+heuristic(next));
    }
  }
  if(!found)return fail('没有找到可通行路线，请检查虚拟墙、门口和标记位置');
  const cells=[];for(let i=goal;i!==-1;i=parent[i])cells.push(grid.world(i%w,Math.floor(i/w)));cells.reverse();
  const exactStart={x:start.x,y:start.y},exactEnd={x:end.x,y:end.y};
  // Portal cells may have their center inside the constrained rectangle.
  // Search edges use the exact endpoint there, as must reconstruction.
  const raw=[exactStart,...(grid.segmentAllowed?cells.slice(1,-1):cells),exactEnd];
  if(raw.slice(1).some((p,j)=>!Number.isFinite(segmentCost(grid,raw[j],p))))return fail('标记与相邻栅格之间被障碍阻断');
  const points=roundCorners(grid,simplify(grid,raw));
  return {status:'ready',points,length_m:points.slice(1).reduce((sum,p,j)=>sum+distance(points[j],p),0)};
}

function passageAxisPath(grid,a,b) {
  return Number.isFinite(segmentCost(grid,a,b))
    ?{status:'ready',points:[{x:a.x,y:a.y},{x:b.x,y:b.y}],length_m:distance(a,b)}
    :{status:'blocked',points:[],reason:'窄通道首尾之间无法沿轴线通行，请检查组件位置、障碍与通行宽度'};
}

// Exterior legs cannot take a shortcut through the region's sides. Only its
// two portal cells remain available; the through leg uses the original grid.
function passageExteriorGrid(grid,passages) {
  if(!passages.length)return grid;
  const cost=grid.cost.slice();
  for(const passage of passages) {
    const c=Math.cos(passage.yaw),s=Math.sin(passage.yaw);
    const corners=[[-1,-1],[-1,1],[1,-1],[1,1]].map(([x,y])=>grid.raster({
      x:passage.x+c*x*passage.width/2-s*y*passage.height/2,
      y:passage.y+s*x*passage.width/2+c*y*passage.height/2}));
    const x0=Math.max(0,Math.floor(Math.min(...corners.map(p=>p.x)))),x1=Math.min(grid.width-1,Math.floor(Math.max(...corners.map(p=>p.x))));
    const y0=Math.max(0,Math.floor(Math.min(...corners.map(p=>p.y)))),y1=Math.min(grid.height-1,Math.floor(Math.max(...corners.map(p=>p.y))));
    const portals=new Set(passage.ends.map(grid.index));
    for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++) {
      const i=y*grid.width+x,local=passageLocal(grid.world(x,y),passage);
      if(!portals.has(i)&&Math.abs(local.x)<passage.width/2&&Math.abs(local.y)<passage.height/2)cost[i]=Infinity;
    }
  }
  return {...grid,cost,usable:p=>{const i=grid.index(p);return i>=0&&Number.isFinite(cost[i]);},
    segmentAllowed:(a,b)=>(!grid.segmentAllowed||grid.segmentAllowed(a,b))&&passages.every(p=>passageIntersection(a,b,p)===null)};
}

function findPassageRoute(grid,start,end,passages) {
  if(!passages.length)return findRoutePath(grid,start,end);
  const touches=(point,passage)=>passage.ends.some(p=>distance(point,p)<1e-6);
  const touched=passages.filter(p=>touches(start,p)||touches(end,p));
  let route=findRoutePath(passageExteriorGrid(grid,touched),start,end),visits=[];
  for(let iteration=0;route.status==='ready'&&iteration<=passages.length;iteration++) {
    const crossings=passages.filter(p=>!touched.includes(p)).map(p=>{
      for(let i=1;i<route.points.length;i++) {
        const t=passageIntersection(route.points[i-1],route.points[i],p);
        if(t!==null) {
          const hit=mix(route.points[i-1],route.points[i],t);
          return {passage:p,order:i-1+t,entry:distance(hit,p.ends[0])<=distance(hit,p.ends[1])?0:1};
        }
      }
      return null;
    }).filter(Boolean).sort((a,b)=>a.order-b.order);
    if(crossings.every(({passage})=>visits.includes(passage)))return route;
    visits=crossings.map(c=>c.passage);
    const exterior=passageExteriorGrid(grid,[...touched,...visits]),points=[start],straightPairs=new Set();
    for(const {passage,entry} of crossings) {
      const ends=passage.ends.slice();
      if(entry===1)ends.reverse();
      straightPairs.add(points.length);points.push(...ends);
    }
    points.push(end);
    const joined=[];
    for(let i=1;i<points.length;i++) {
      const part=straightPairs.has(i-1)?passageAxisPath(grid,points[i-1],points[i]):findRoutePath(exterior,points[i-1],points[i]);
      if(part.status!=='ready')return part;
      joined.push(...part.points.slice(joined.length?1:0));
    }
    route={status:'ready',points:joined,length_m:joined.slice(1).reduce((sum,p,j)=>sum+distance(joined[j],p),0)};
  }
  return route.status==='ready'?{status:'blocked',points:[],reason:'窄通道通行约束无法同时满足，请检查组件布局'}:route;
}
export function planRouteSegments(grid,segments,pairCache=new Map(),{refineGrid}={}) {
  const failures=[];
  const planned=segments.map((segment,segmentIndex)=>{
    const paths=[],straightPairs=new Set(segment.straightPairs || []),passages=segment.passages || [];
    let current=null;
    for(let i=1;i<segment.points.length;i++) {
      const a=segment.points[i-1],b=segment.points[i],straight=straightPairs.has(i-1);
      const pairKey=(a,b)=>JSON.stringify([a.x,a.y,b.x,b.y,straight,passages]);
      const key=pairKey(a,b);
      let path=pairCache.get(key);
      if(!path) {
        const reversed=pairCache.get(pairKey(b,a));
        path=reversed?.status==='ready'?{...reversed,points:reversed.points.slice().reverse()}:
          straight?passageAxisPath(grid,a,b):findPassageRoute(grid,a,b,passages);
        pairCache.set(key,path);if(pairCache.size>512)pairCache.delete(pairCache.keys().next().value);
      }
      if(path.status!=='ready'&&refineGrid&&!path.refinementAttempted) {
        const fine=refineGrid(a,b);
        if(fine)path=straight?passageAxisPath(fine,a,b):findPassageRoute(fine,a,b,passages);
        path={...path,refinementAttempted:true};
        pairCache.set(key,path);
      }
      if(path.status!=='ready') {failures.push({segment:segmentIndex,from:i-1,to:i,reason:path.reason});current=null;continue;}
      if(!current){current=[];paths.push(current);}
      for(let j=current.length?1:0;j<path.points.length;j++)current.push(path.points[j]);
    }
    return {...segment,anchors:segment.points,paths};
  });
  return {segments:planned,failures};
}
