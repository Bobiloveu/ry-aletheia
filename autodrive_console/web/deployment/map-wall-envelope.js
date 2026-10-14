// Separate inferred region boundaries from the walls actually displayed.
// Door crossings may partition rooms for classification without being painted.
export function buildWallEnvelope({rgba,source,mask,width,height,resolution}) {
  const barriers=mask.slice();
  const maximumGap=Math.ceil(2/resolution);
  const support=Math.max(4,Math.ceil(1.2/resolution));
  const shortSupport=Math.max(4,Math.ceil(.35/resolution));
  const probe=Math.max(2,Math.ceil(.25/resolution));
  for(const vertical of [false,true]) {
    const length=vertical?height:width,lines=vertical?width:height;
    const index=(along,across)=>vertical?along*width+across:across*width+along;
    const hit=(along,across)=>along>=0&&along<length&&across>=0&&across<lines&&source[index(along,across)];
    const bandHit=(along,across)=>hit(along,across)||hit(along,across-1)||hit(along,across+1);
    const supported=(along,across,direction,steps)=>{
      const available=direction>0?length-along:along+1;
      if(!Number.isFinite(steps)||Math.ceil(steps*.7)>available)return false;
      let hits=0,exact=0;for(let k=0;k<Math.min(steps,available);k++) {
        if(bandHit(along+k*direction,across))hits++;
        if(hit(along+k*direction,across))exact++;
      }
      return hits>=Math.ceil(steps*.7)&&exact>=Math.ceil(steps*.4);
    };
    const observedCrossing=(start,end,across)=>{
      const counts=[0,0],totals=[0,0];
      for(let along=start+1;along<end;along++)for(let k=1;k<=probe;k++)for(let side=0;side<2;side++) {
        const a=across+(side?1:-1)*k;if(a<0||a>=lines)continue;
        const i=index(along,a);if(!rgba[i*4+3]||source[i])continue;
        totals[side]++;if(rgba[i*4]>=250)counts[side]++;
      }
      return counts.every((count,side)=>count>0&&count>=totals[side]*.12);
    };
    const jamb=(along,across)=>{
      for(const sign of [-1,1]) {
        let hits=0;for(let k=1;k<=probe+1;k++)if(hit(along,across+sign*k))hits++;
        if(hits>=2)return true;
      }
      return false;
    };
    for(let across=0;across<lines;across++) {
      let previous=-1;
      for(let along=0;along<length;along++) {
        if(!hit(along,across))continue;
        const gap=along-previous-1;
        if(previous>=0&&gap>0&&gap<=maximumGap
          &&supported(previous,across,-1,shortSupport)&&supported(along,across,1,shortSupport)) {
          let opaque=true;
          for(let k=previous+1;k<along;k++)if(!rgba[index(k,across)*4+3]){opaque=false;break;}
          if(!opaque){previous=along;continue;}
          const paint=supported(previous,across,-1,support)&&supported(along,across,1,support)
            &&!observedCrossing(previous,along,across)&&!(jamb(previous,across)&&jamb(along,across));
          for(let k=previous+1;k<along;k++) {
            const i=index(k,across);barriers[i]=1;if(paint)mask[i]=1;
          }
        }
        previous=along;
      }
    }
  }
  return barriers;
}
