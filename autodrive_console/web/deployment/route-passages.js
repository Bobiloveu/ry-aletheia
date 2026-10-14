// Display geometry mirrors execution_chain._narrow_passage_traversal_points.
// Compiled task poses remain owned by Backend.
export function narrowPassageEnds(component) {
  if(component?.kind!=='narrow_passage')return null;
  const {x,y}=component,yaw=Number(component.yaw || 0);
  const width=Number(component.attributes?.width_m),height=Number(component.attributes?.height_m);
  if(![x,y,yaw,width,height].every(Number.isFinite)||width<.1||height<.1||width>20||height>20)return null;
  const vertical=height>=width,half=(vertical?height:width)/2;
  const dx=(vertical?-Math.sin(yaw):Math.cos(yaw))*half;
  const dy=(vertical?Math.cos(yaw):Math.sin(yaw))*half;
  return [{x:x-dx,y:y-dy},{x:x+dx,y:y+dy}];
}

// A pair constraint is local to one segment, so repeated and return visits
// retain their original order. Never insert or move server-produced poses.
export function constrainPassageAxes(segments,components) {
  const passages=components.map(component=>{
    const ends=narrowPassageEnds(component);
    return ends?{x:component.x,y:component.y,yaw:Number(component.yaw || 0),
      width:Number(component.attributes.width_m),height:Number(component.attributes.height_m),ends}:null;
  }).filter(Boolean);
  if(!passages.length)return segments;
  const same=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y)<1e-6;
  return segments.map(segment=>{
    const straightPairs=new Set(segment.straightPairs || []);
    for(let i=0;i<segment.points.length-1;i++) {
      const a=segment.points[i],b=segment.points[i+1];
      if(passages.some(({ends:[p,q]})=>same(a,p)&&same(b,q)||same(a,q)&&same(b,p)))straightPairs.add(i);
    }
    return {...segment,passages,...(straightPairs.size?{straightPairs:[...straightPairs]}:{})};
  });
}

export function passageLocal(point,passage) {
  const c=Math.cos(passage.yaw),s=Math.sin(passage.yaw),dx=point.x-passage.x,dy=point.y-passage.y;
  return {x:c*dx+s*dy,y:-s*dx+c*dy};
}

// Open rectangle: touching an entrance or skimming a boundary is not a visit.
export function passageIntersection(a,b,passage) {
  a=passageLocal(a,passage);b=passageLocal(b,passage);
  let lo=0,hi=1;
  for(const [start,delta,half] of [[a.x,b.x-a.x,passage.width/2-1e-6],[a.y,b.y-a.y,passage.height/2-1e-6]]) {
    if(Math.abs(delta)<1e-12){if(Math.abs(start)>=half)return null;continue;}
    const p=(-half-start)/delta,q=(half-start)/delta;
    lo=Math.max(lo,Math.min(p,q));hi=Math.min(hi,Math.max(p,q));
  }
  return hi>lo?lo:null;
}
