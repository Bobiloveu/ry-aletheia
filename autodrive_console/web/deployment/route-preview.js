// Single-flight worker with one replaceable pending request and bounded result cache.
export function createRoutePreview({workerFactory=()=>new Worker(new URL('./route-preview-worker.js',import.meta.url),{type:'module'}),onChange=()=>{},delay=100,maxEntries=16}={}) {
  let worker=null,activeKey='',state={phase:'idle',result:null},pending=null,inFlight=null,timer=null;
  const cache=new Map();
  const emit=next=>{state=next;onChange(state);};
  function start() {
    timer=null;if(inFlight||!pending)return;
    const request=pending;pending=null;
    try {
      if(!worker) {
        worker=workerFactory();
        worker.onmessage=({data})=>finish(data);
        worker.onerror=event=>{event.preventDefault?.();worker?.terminate();worker=null;finish({key:inFlight?.key,error:'路线规划暂不可用，请刷新页面后重试'});};
      }
      inFlight=request;worker.postMessage(request);
    } catch(error){inFlight=request;finish({key:request.key,error:error.message});}
  }
  function finish(data) {
    if(data.key!==inFlight?.key)return;
    if(data.error)globalThis.RYAletheiaDiagnostics?.failure?.('deployment.route-preview',data.error);
    else if(data.result?.failures?.length)globalThis.RYAletheiaDiagnostics?.report?.({event:'operation_failed',level:'WARNING',operation:'deployment.route-preview',message:`路线预览存在 ${data.result.failures.length} 段无法通行路段`});
    const next=data.error?{phase:'error',result:null,error:data.error}:{phase:'ready',result:data.result};
    cache.delete(data.key);cache.set(data.key,next);while(cache.size>maxEntries)cache.delete(cache.keys().next().value);
    inFlight=null;if(data.key===activeKey)emit(next);
    if(pending)start();
  }
  return {
    get state(){return state;},
    sync(request) {
      if(!request) {
        if(activeKey){activeKey='';pending=null;clearTimeout(timer);timer=null;emit({phase:'idle',result:null});}
        return state;
      }
      if(request.key===activeKey)return state;
      activeKey=request.key;
      if(cache.has(activeKey)) {const next=cache.get(activeKey);cache.delete(activeKey);cache.set(activeKey,next);pending=null;clearTimeout(timer);timer=null;emit(next);return state;}
      pending=inFlight?.key===activeKey?null:request;emit({phase:'processing',result:null});
      clearTimeout(timer);timer=setTimeout(start,delay);return state;
    },
    dispose(){clearTimeout(timer);worker?.terminate();worker=null;pending=inFlight=null;activeKey='';cache.clear();state={phase:'idle',result:null};},
  };
}

export function paintRoutePreview(context,segments,toCanvas) {
  context.save();context.lineCap='round';context.lineJoin='round';
  // Return dashes share the planned centerline: no visual offset into walls.
  for(const segment of [...segments].sort((a,b)=>(a.leg==='return')-(b.leg==='return'))) {
    const returning=segment.leg==='return',color=returning?'#b86b00':'#007aff';
    for(const path of segment.paths||[]) {
      if(path.length<2)continue;
      const points=path.map(toCanvas);
      const stroke=()=>{context.beginPath();context.moveTo(points[0].x,points[0].y);for(const p of points.slice(1))context.lineTo(p.x,p.y);context.stroke();};
      context.setLineDash([]);
      if(!returning){context.strokeStyle='rgba(255,255,255,.82)';context.lineWidth=5;stroke();}
      context.strokeStyle=color;context.lineWidth=returning?2:2.8;context.setLineDash(returning?[7,11]:[]);stroke();
      if(returning)continue;
      context.setLineDash([]);let accumulated=0,next=90;
      for(let i=1;i<points.length;i++) {
        const a=points[i-1],b=points[i],length=Math.hypot(b.x-a.x,b.y-a.y);
        while(accumulated+length>=next) {
          const t=(next-accumulated)/length,p={x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t},angle=Math.atan2(b.y-a.y,b.x-a.x);
          context.save();context.translate(p.x,p.y);context.rotate(angle);context.strokeStyle=color;context.lineWidth=2;
          context.beginPath();context.moveTo(-4,-3);context.lineTo(0,0);context.lineTo(-4,3);context.stroke();context.restore();next+=120;
        }
        accumulated+=length;
      }
    }
  }
  context.restore();
}
