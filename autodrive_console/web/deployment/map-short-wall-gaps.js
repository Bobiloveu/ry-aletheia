// Viewing-only repair for short, nearly axial wall breaks. Sparse original
// samples and small lateral offsets must not be mistaken for a doorway.
export function repairShortWallGaps({rgba,source,mask,width,height,resolution}) {
  const gap=Math.min(24,Math.floor(.65/resolution+1e-8));
  if(!gap)return;
  const support=Math.max(6,Math.min(48,Math.ceil(1.2/resolution)));
  const tolerance=Math.min(2,Math.floor(.10/resolution+1e-8));
  const probe=Math.max(2,Math.min(12,Math.ceil(.25/resolution)));
  for(const vertical of [false,true]) {
    const alongLength=vertical?height:width,acrossLength=vertical?width:height;
    const index=(a,b)=>vertical?a*width+b:b*width+a;
    const inside=(a,b)=>a>=0&&a<alongLength&&b>=0&&b<acrossLength;
    const hit=(a,b)=>inside(a,b)&&source[index(a,b)];
    const band=(a,b,radius)=>{
      for(let shift=-radius;shift<=radius;shift++)if(hit(a,b+shift))return true;
      return false;
    };
    const supported=(a,b,direction)=>{
      let hits=0,far=false;
      for(let k=0;k<support;k++)if(band(a+k*direction,b,tolerance)) {
        hits++;if(k>=Math.ceil(support*.60))far=true;
      }
      return far&&hits>=Math.ceil(support*.40);
    };
    const jamb=(a,b)=>{
      let hits=0;
      for(const side of [-1,1]) {
        for(let k=1;k<=probe;k++)if(hit(a,b+side*k))hits++;
      }
      // A sample in the middle of a short jamb has support on both sides.
      // Count both directions so it cannot borrow the neighbouring main wall.
      return hits>=2;
    };
    const crossing=(a,b,end,endAcross)=>{
      const counts=[0,0],totals=[0,0];
      for(let k=1;k<end-a;k++)for(let offset=1;offset<=probe;offset++)for(let side=0;side<2;side++) {
        const across=Math.round(b+(endAcross-b)*k/(end-a))+(side?1:-1)*offset;
        if(!inside(a+k,across))continue;
        const i=index(a+k,across);
        if(!rgba[i*4+3]||source[i])continue;
        totals[side]++;if(rgba[i*4]>=250)counts[side]++;
      }
      // A coherent white crossing is evidence of an opening. Scattered white
      // cells in a mostly unknown room are insufficient to infer a doorway.
      return counts.every((n,side)=>totals[side]>0&&n>=totals[side]*.65);
    };
    for(let i=0;i<source.length;i++) {
      if(!source[i])continue;
      const x=i%width,y=Math.floor(i/width),a=vertical?y:x,b=vertical?x:y;
      if(band(a+1,b,Math.min(1,tolerance))||!supported(a,b,-1))continue;
      for(let distance=2;distance<=gap+1;distance++) {
        let endAcross=null;
        for(let shift=0;shift<=tolerance&&endAcross===null;shift++)
          for(const side of shift?[-1,1]:[1])if(hit(a+distance,b+side*shift)){endAcross=b+side*shift;break;}
        if(endAcross===null)continue;
        if(!supported(a+distance,endAcross,1)||jamb(a,b)&&jamb(a+distance,endAcross)
          ||crossing(a,b,a+distance,endAcross))break;
        let opaque=true,previous=b;
        for(let step=1;step<=distance;step++) {
          const across=Math.round(b+(endAcross-b)*step/distance);
          if(!rgba[index(a+step,across)*4+3]
            ||across!==previous&&!rgba[index(a+step,previous)*4+3]){opaque=false;break;}
          previous=across;
        }
        if(!opaque)break;
        previous=b;
        for(let step=1;step<=distance;step++) {
          const across=Math.round(b+(endAcross-b)*step/distance);
          mask[index(a+step,across)]=1;
          // Supercover the fitted line: diagonal rounding must not leave a
          // four-neighbour leak at a one-cell lateral change.
          if(across!==previous)mask[index(a+step,previous)]=1;
          previous=across;
        }
        break;
      }
    }
  }
}
