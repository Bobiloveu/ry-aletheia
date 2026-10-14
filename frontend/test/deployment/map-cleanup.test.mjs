import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
const url='../../../autodrive_console/web/deployment/map-cleanup.js';
function fixture(width=50,height=40) {
  const rgba=new Uint8ClampedArray(width*height*4);
  for(let i=0;i<width*height;i++)rgba.set([205,205,205,255],i*4);
  const point=(x,y,v=0)=>rgba.set([v,v,v,255],(y*width+x)*4);
  const line=(x,y,n,dx=1,dy=0)=>{for(let i=0;i<n;i++)point(x+i*dx,y+i*dy);};
  return {rgba,width,height,resolution:.05,point,line};
}
function virtualRoomFixture(divider=60) {
  const f=fixture(200,140);
  for(const y of [10,129])f.line(10,y,180);
  for(const x of [10,189])f.line(x,10,120,0,1);
  for(let y=11;y<129;y++)for(let x=11;x<189;x++)f.point(x,y,254);
  f.line(10,divider,70);f.line(110,divider,80);
  f.point(150,110); // A real feature inside the closed room must survive.
  return {...f,virtualWalls:[{points:[{x:79,y:divider},{x:110,y:divider}]}]};
}

test('architectural appearance hides all unknown scan fragments while preserving evidence and pure white floor',async()=>{
  const {beautifyMap}=await import(url),f=virtualRoomFixture(),before=f.rgba.slice();
  const r=beautifyMap({...f,passagePoints:[{x:30,y:30}]});
  assert.equal(r.floorBits.length,Math.ceil(r.floor.length/8));
  for(let i=0;i<r.floor.length;i++)assert.equal((r.floorBits[i>>3]>>(i&7))&1,r.floor[i]);
  for(let i=0;i<r.floor.length;i++)assert.deepEqual([...r.rgba.subarray(i*4,i*4+3)],
    r.floor[i]?[255,255,255]:[231,236,242]);
  assert.equal(r.mask[110*f.width+150],1,'source feature evidence survives behind the appearance');
  assert.equal(r.features.length,0,'source points must not return through reduced-scale pooling');
  assert.ok(r.architecture.vertices.length>0);assert.deepEqual(f.rgba,before);
});

test('saved virtual walls grey a closed observed room while retaining the start component and its features',async()=>{
  const {beautifyMap}=await import(url),f=virtualRoomFixture(),before=f.rgba.slice();
  const r=beautifyMap({...f,passagePoints:[{x:30,y:30}]});
  assert.equal(r.floor[30*f.width+30],1);
  assert.equal(r.floor[90*f.width+30],0);
  assert.equal(r.mask[110*f.width+150],1);
  assert.equal(r.mask[60*f.width+90],0,'virtual walls must not become physical obstacles');
  assert.ok(r.stats.closedVirtualRegions>0);assert.deepEqual(f.rgba,before);
});

test('open virtual strokes and removed walls do not grey a still-connected observed room',async()=>{
  const {beautifyMap}=await import(url),f=virtualRoomFixture();
  for(const virtualWalls of [[],[{points:[{x:79,y:60},{x:94,y:60}]}]]) {
    const r=beautifyMap({...f,virtualWalls,passagePoints:[{x:30,y:30}]});
    assert.equal(r.floor[90*f.width+30],1);
  }
});

test('without a start the largest observed enclosed component remains the main passage',async()=>{
  const {beautifyMap}=await import(url),f=virtualRoomFixture(85),r=beautifyMap(f);
  assert.equal(r.floor[30*f.width+30],1);assert.equal(r.floor[100*f.width+30],0);
});

test('a start in the smaller enclosed component takes priority over a larger observed region',async()=>{
  const {beautifyMap}=await import(url),f=virtualRoomFixture(85),r=beautifyMap({...f,passagePoints:[{x:30,y:100}]});
  assert.equal(r.floor[100*f.width+30],1);assert.equal(r.floor[30*f.width+30],0);
});

test('with virtual walls active all other closed rooms are grey, including those already enclosed by real walls',async()=>{
  const {beautifyMap}=await import(url),f=virtualRoomFixture();
  f.line(130,60,70,0,1);
  const r=beautifyMap({...f,passagePoints:[{x:30,y:30}]});
  assert.equal(r.floor[90*f.width+160],0);assert.equal(r.floor[30*f.width+30],1);
});

test('virtual enclosures reaching any legal map edge close on the outermost pixel row or column',async()=>{
  const {beautifyMap}=await import(url);
  for(const [points,probe,start] of [
    [[[40,20],[120,20],[120,80],[40,80],[40,20]],[80,50],[20,50]],
    [[[20,40],[100,40],[100,100],[20,100],[20,40]],[50,70],[50,20]],
    [[[0,20],[60,20],[60,80],[0,80],[0,20]],[30,50],[90,50]],
    [[[20,0],[100,0],[100,60],[20,60],[20,0]],[60,30],[60,80]],
  ]) {
    const f=fixture(120,100);for(let i=0;i<120*100;i++)f.rgba.set([254,254,254,255],i*4);
    const r=beautifyMap({...f,virtualWalls:[{points:points.map(([x,y])=>({x,y}))}],passagePoints:[{x:start[0],y:start[1]}]});
    assert.equal(r.floor[probe[1]*120+probe[0]],0,JSON.stringify(points));
    assert.equal(r.floor[start[1]*120+start[0]],1);
  }
});

test('diagonal virtual wall corners form closed spaces without four-neighbour leaks',async()=>{
  const {beautifyMap}=await import(url),f=fixture(100,100);
  for(let i=0;i<10000;i++)f.rgba.set([254,254,254,255],i*4);
  const r=beautifyMap({...f,virtualWalls:[{points:[[50,20],[80,50],[50,80],[20,50],[50,20]].map(([x,y])=>({x,y}))}],passagePoints:[{x:5,y:5}]});
  assert.equal(r.floor[50*100+50],0);assert.equal(r.floor[10*100+10],1);
});

test('a start component enclosed by real and virtual walls gets a continuous white viewing floor',async()=>{
  const {beautifyMap}=await import(url),f=virtualRoomFixture();
  for(let y=11;y<60;y++)for(let x=50;x<189;x++)f.point(x,y,205);
  f.point(150,30);const r=beautifyMap({...f,passagePoints:[{x:30,y:30}]});
  for(let y=11;y<60;y++)for(let x=11;x<189;x++)if(!r.mask[y*200+x])assert.equal(r.floor[y*200+x],1);
  assert.equal(r.mask[30*200+150],1);assert.equal(r.floor[90*200+30],0);
});

test('a start region leaking into exterior unknown is not blindly filled white',async()=>{
  const {beautifyMap}=await import(url),f=virtualRoomFixture();
  for(let y=20;y<40;y++)f.point(10,y,254);
  const r=beautifyMap({...f,passagePoints:[{x:30,y:30}]});
  assert.equal(r.floor[5*200+5],0);assert.equal(r.floor[30*200+30],1);
});
test('removes disconnected singleton clutter, retains thin walls, a corner and a compact pillar without changing source',async()=>{
  const {beautifyMap}=await import(url);const f=fixture();
  f.line(3,8,20);f.line(3,8,15,0,1);
  for(const [x,y] of [[35,10],[36,10],[35,11],[36,11]])f.point(x,y);
  f.point(30,30);f.point(45,4);const source=f.rgba.slice();
  const r=beautifyMap({...f,removeIsolated:true});
  assert.deepEqual(f.rgba,source);
  for(let x=3;x<23;x++)assert.equal(r.mask[8*f.width+x],1);
  assert.equal(r.mask[11*f.width+36],1);
  assert.equal(r.mask[30*f.width+30],0);
  assert.equal(r.mask[4*f.width+45],0);
  assert.ok(r.stats.removed>=2);
});
test('repairs supported short gaps horizontally, vertically and diagonally',async()=>{
  const {beautifyMap}=await import(url);
  for(const [dx,dy] of [[1,0],[0,1],[1,1],[1,-1]]) {
    const f=fixture(50,50),x=7,y=dy<0?40:7;
    f.line(x,y,10,dx,dy);f.line(x+14*dx,y+14*dy,12,dx,dy);
    const r=beautifyMap(f);
    for(let i=10;i<14;i++)assert.equal(r.mask[(y+i*dy)*f.width+x+i*dx],1,`${dx},${dy}: gap ${i}`);
    assert.ok(r.stats.added>=4);
  }
});
test('leaves a doorway and gaps lacking aligned wall support open',async()=>{
  const {beautifyMap}=await import(url);const f=fixture(65,50);
  f.line(3,10,12);f.line(30,10,12); // 0.75m doorway
  f.line(3,30,12);f.line(18,33,12); // different walls
  const r=beautifyMap(f);
  for(let x=15;x<30;x++)assert.equal(r.mask[10*f.width+x],0);
  assert.equal(r.mask[30*f.width+16],0);
});
test('repairs a supported slanted wall without forcing it onto horizontal or 45-degree axes',async()=>{
  const {beautifyMap}=await import(url);const f=fixture(60,50);
  for(let x=5;x<45;x++)if(x<20||x>23)f.point(x,10+Math.round((x-5)*.5));
  const r=beautifyMap(f);
  for(let x=20;x<=23;x++)assert.equal(r.mask[(10+Math.round((x-5)*.5))*f.width+x],1);
});
test('does not trim attached jambs, inward corners or outdoor diagonal structures',async()=>{
  const {beautifyMap}=await import(url);const f=fixture(80,60);
  f.line(4,10,30);f.line(15,10,3,0,1);f.line(50,10,30,1,1);
  const r=beautifyMap(f);
  for(const [x,y] of [[15,11],[15,12],[50,10],[79,39]])assert.equal(r.mask[y*f.width+x],1);
});
test('explicit protected features survive even if they look like isolated noise',async()=>{
  const {beautifyMap}=await import(url);const f=fixture();f.point(30,30);f.point(40,30);
  const r=beautifyMap({...f,removeIsolated:true,protectedPoints:[{x:30,y:30,radius:2}]});
  assert.equal(r.mask[30*f.width+30],1);assert.equal(r.mask[30*f.width+40],0);
});
test('a two-cell narrow post is retained without requiring an operator annotation',async()=>{
  const {beautifyMap}=await import(url);const f=fixture();f.point(35,10);f.point(35,11);
  const r=beautifyMap(f);assert.equal(r.mask[10*f.width+35],1);assert.equal(r.mask[11*f.width+35],1);
});
test('continuous display fill removes salt-and-pepper floor texture while keeping distant unknown outside',async()=>{
  const {beautifyMap}=await import(url);const f=fixture();
  for(let y=10;y<30;y++)for(let x=10;x<30;x++)if((x+y)%2===0)f.point(x,y,254);
  const r=beautifyMap(f);
  assert.equal(r.floor[20*f.width+20],1);assert.equal(r.floor[20*f.width+21],1);
  assert.equal(r.floor[2*f.width+2],0);
  assert.equal(r.rgba[0],231);
});
test('gap repair distance is in meters and never grows cumulatively through invented support',async()=>{
  const {beautifyMap}=await import(url);const f=fixture(80,40);f.resolution=.1;
  f.line(2,10,6);f.line(12,10,6); // .4m gap with insufficient structural support
  const r=beautifyMap(f);assert.equal(r.mask[10*f.width+10],0);
});
test('rejects malformed input and reports ordered processing stages',async()=>{
  const {beautifyMap}=await import(url);assert.throws(()=>beautifyMap({rgba:new Uint8Array(4),width:2,height:2,resolution:.05}));
  const stages=[];beautifyMap(fixture(),s=>stages.push(s));
  assert.deepEqual(stages,['repair','features','floor','regions','render']);
});

test('default display retains every source obstacle including ambiguous isolated feature points',async()=>{
  const {beautifyMap}=await import(url);const f=fixture();
  for(const [x,y] of [[3,4],[12,7],[34,32],[35,10],[35,11]])f.point(x,y);
  const r=beautifyMap(f);
  assert.equal(r.stats.removed,0);
  for(let i=0;i<f.width*f.height;i++)if(f.rgba[i*4]<205)assert.equal(r.mask[i],1);
});

test('a continuous shallow raster wall is not thickened by inventing parallel cells',async()=>{
  const {beautifyMap}=await import(url);const f=fixture(70,50);
  for(let x=5;x<55;x++)f.point(x,10+Math.round((x-5)*.5));
  const r=beautifyMap(f);assert.equal(r.stats.added,0);
});

test('an observed corridor has no unknown pinholes or small pockets beside its walls',async()=>{
  const {beautifyMap}=await import(url);const f=fixture(120,70);
  f.line(5,10,105);f.line(5,45,105);
  for(let y=11;y<45;y++)for(let x=5;x<110;x++)f.point(x,y,254);
  for(let y=22;y<32;y++)for(let x=40;x<50;x++)f.point(x,y,205);
  for(let y=11;y<16;y++)for(let x=75;x<90;x++)f.point(x,y,205);
  f.point(60,25); // An ambiguous real feature must survive display cleanup.
  const r=beautifyMap(f);
  for(let y=11;y<45;y++)for(let x=6;x<109;x++)if(!r.mask[y*f.width+x])
    assert.deepEqual([...r.rgba.slice((y*f.width+x)*4,(y*f.width+x)*4+3)],[255,255,255],`${x},${y}`);
  assert.equal(r.mask[25*f.width+60],1);
});

test('small white fragments in a predominantly unknown enclosed room become uniformly unknown',async()=>{
  const {beautifyMap}=await import(url);const f=fixture(100,90);
  f.line(10,10,75);f.line(10,75,75);f.line(10,10,66,0,1);f.line(84,10,66,0,1);
  for(let y=30;y<42;y++)for(let x=35;x<47;x++)f.point(x,y,254);
  for(let y=52;y<55;y++)for(let x=65;x<69;x++)f.point(x,y,254);
  const r=beautifyMap(f);
  for(let y=11;y<75;y++)for(let x=11;x<84;x++)if(!r.mask[y*f.width+x])assert.equal(r.floor[y*f.width+x],0,`${x},${y}`);
});

test('floor smoothing cannot bleed through a wall into an unobserved adjacent room',async()=>{
  const {beautifyMap}=await import(url);const f=fixture(100,80);
  f.line(35,5,70,0,1); // A 0.75m door remains open, away from the checked wall.
  for(let y=35;y<50;y++)f.point(35,y,205);
  for(let y=6;y<75;y++)for(let x=10;x<35;x++)f.point(x,y,254);
  const r=beautifyMap(f);
  for(let y=10;y<25;y++)for(let x=36;x<40;x++)assert.equal(r.floor[y*f.width+x],0,`${x},${y}`);
  assert.equal(r.floor[20*f.width+30],1);
});

test('large unknown rooms and exterior unknown remain unknown while an outdoor observed patch survives',async()=>{
  const {beautifyMap}=await import(url);const f=fixture(120,100);
  for(let y=20;y<35;y++)for(let x=20;x<35;x++)f.point(x,y,254);
  const r=beautifyMap(f);
  assert.equal(r.floor[27*f.width+27],1);
  assert.equal(r.floor[70*f.width+70],0);
  assert.equal(r.floor[1*f.width+1],0);
});

test('a short narrow observed corridor is not mistaken for a white island in a large unknown room',async()=>{
  const {beautifyMap}=await import(url);const f=fixture(160,160);
  for(const y of [5,154])f.line(5,y,150);
  for(const x of [5,154])f.line(x,5,150,0,1);
  f.line(50,40,60,0,1);f.line(71,40,60,0,1);
  for(let y=40;y<100;y++)for(let x=51;x<71;x++)f.point(x,y,254);
  const r=beautifyMap(f);
  for(let y=40;y<100;y++)for(let x=51;x<71;x++)assert.equal(r.floor[y*f.width+x],1);
});

test('transparent crop borders count as open exterior rather than artificial room walls',async()=>{
  const {beautifyMap}=await import(url);const f=fixture(120,100);
  for(let y=20;y<35;y++)for(let x=20;x<35;x++)f.point(x,y,254);
  for(let i=0;i<f.width*f.height;i++)if(i<f.width||i>=f.width*(f.height-1)||i%f.width===0||i%f.width===f.width-1)f.rgba[i*4+3]=0;
  const r=beautifyMap(f);assert.equal(r.floor[27*f.width+27],1);
  for(let i=0;i<f.width*f.height;i++)assert.equal(r.rgba[i*4+3],f.rgba[i*4+3]);
});

test('a bounded room with at least half unknown cells is rendered unknown even with a large observed patch',async()=>{
  const {beautifyMap}=await import(url);
  for(const whiteColumns of [30,40]) {
    const f=fixture(110,110);
    f.line(10,10,82);f.line(10,91,82);f.line(10,10,82,0,1);f.line(91,10,82,0,1);
    for(let y=11;y<91;y++)for(let x=11;x<11+whiteColumns;x++)f.point(x,y,254);
    f.point(20,65);const source=f.rgba.slice(),r=beautifyMap(f);
    for(let y=11;y<91;y++)for(let x=11;x<91;x++)if(!r.mask[y*f.width+x])assert.equal(r.floor[y*f.width+x],0,`${whiteColumns}: ${x},${y}`);
    assert.equal(r.mask[65*f.width+20],1);assert.deepEqual(f.rgba,source);
  }
});

test('a mostly observed enclosed room keeps its floor while a neighbouring majority-unknown room is grey',async()=>{
  const {beautifyMap}=await import(url),f=fixture(180,100);
  for(const y of [10,90])f.line(10,y,160);
  for(const x of [10,90,169])f.line(x,10,81,0,1);
  for(let y=11;y<90;y++)for(let x=11;x<75;x++)f.point(x,y,254);
  for(let y=11;y<90;y++)for(let x=91;x<115;x++)f.point(x,y,254);
  const r=beautifyMap(f);assert.equal(r.floor[40*f.width+40],1);assert.equal(r.floor[40*f.width+100],0);
});

test('long aligned structural wall breaks are repaired but observed door crossings remain open',async()=>{
  const {beautifyMap}=await import(url);
  for(const vertical of [false,true]) {
    const f=fixture(150,150),put=(along,across,v=0)=>f.point(vertical?across:along,vertical?along:across,v);
    for(let i=10;i<130;i++)if(i<55||i>=75)put(i,70);
    const r=beautifyMap(f);for(let i=55;i<75;i++)assert.equal(r.mask[(vertical?i:70)*f.width+(vertical?70:i)],1);
    for(let i=50;i<80;i++)for(let j=55;j<86;j++)if(j!==70||i>=55&&i<75)put(i,j,254);
    const door=beautifyMap(f);for(let i=55;i<75;i++)assert.equal(door.mask[(vertical?i:70)*f.width+(vertical?70:i)],0);
  }
});

test('region judgement separates an unknown room from an observed corridor across an open doorway',async()=>{
  const {beautifyMap}=await import(url),f=fixture(150,120);
  for(const y of [10,90])f.line(10,y,130);
  for(const x of [10,90,139])f.line(x,10,81,0,1);
  for(let y=11;y<90;y++)for(let x=91;x<139;x++)f.point(x,y,254);
  for(let y=40;y<60;y++)for(let x=11;x<90;x++)f.point(x,y,254);
  for(let y=40;y<60;y++)f.point(90,y,254);
  const r=beautifyMap(f);
  assert.equal(r.floor[50*f.width+60],0);assert.equal(r.floor[50*f.width+115],1);
  for(let y=40;y<60;y++)assert.equal(r.mask[y*f.width+90],0);
});

test('an enclosed narrow region with exactly half unknown cells is not exempted as an observed corridor',async()=>{
  const {beautifyMap}=await import(url),f=fixture(80,150);
  for(const y of [10,130])f.line(20,y,22);
  for(const x of [20,41])f.line(x,10,121,0,1);
  for(let y=11;y<130;y++)for(let x=21;x<41;x++)if((x+y)%2===0)f.point(x,y,254);
  const r=beautifyMap(f);assert.equal(r.floor[50*f.width+30],0);
});

test('structural repair preserves paired door jambs and never bridges transparent cropped space',async()=>{
  const {beautifyMap}=await import(url);
  for(const transparent of [false,true]) {
    const f=fixture(150,90);
    f.line(10,40,45);f.line(75,40,55);
    if(transparent)for(let x=55;x<75;x++)f.rgba[(40*f.width+x)*4+3]=0;
    else {f.line(54,40,8,0,1);f.line(75,40,8,0,1);}
    const r=beautifyMap(f);
    for(let x=55;x<75;x++)assert.equal(r.mask[40*f.width+x],0);
  }
});

test('one-sided observed doorways with short jambs are not sealed or given parallel walls',async()=>{
  const {beautifyMap}=await import(url);
  for(const jambLength of [2,3,4]) {
    const f=fixture(150,150);f.line(10,70,45);f.line(75,70,55);
    for(let y=71;y<95;y++)for(let x=45;x<85;x++)f.point(x,y,254);
    for(let x=55;x<75;x++)f.point(x,70,254);
    f.line(54,70,jambLength+1,0,-1);f.line(75,70,jambLength+1,0,-1);
    const r=beautifyMap(f);
    for(let y=66;y<=70;y++)for(let x=55;x<75;x++)assert.equal(r.mask[y*f.width+x],0,`${jambLength}: ${x},${y}`);
  }
});

test('a finite tiny resolution cannot create unbounded wall support loops',()=>{
  const moduleUrl=new URL(url,import.meta.url).href;
  const script=`import {beautifyMap} from ${JSON.stringify(moduleUrl)};
    const width=64,height=16,rgba=new Uint8ClampedArray(width*height*4);
    for(let i=0;i<width*height;i++)rgba.set([205,205,205,255],i*4);
    for(let x=1;x<61;x++)if(x<20||x>=22)rgba.set([0,0,0,255],(8*width+x)*4);
    beautifyMap({rgba,width,height,resolution:Number.MIN_VALUE});`;
  const result=spawnSync(process.execPath,['--input-type=module','-e',script],{timeout:2000,encoding:'utf8'});
  assert.equal(result.error,undefined);assert.equal(result.status,0,result.stderr);
});

test('majority-unknown judgement does not grey a separately observed room beside a larger corridor',async()=>{
  const {beautifyMap}=await import(url),f=fixture(180,130);
  for(const y of [10,45,119])f.line(10,y,160);
  for(const x of [10,90,169])f.line(x,45,75,0,1);
  f.line(10,10,36,0,1);f.line(169,10,36,0,1);
  for(let y=11;y<45;y++)for(let x=11;x<169;x++)f.point(x,y,254);
  for(let y=46;y<119;y++)for(let x=11;x<90;x++)if(x<60)f.point(x,y,254);
  const r=beautifyMap(f);
  assert.equal(r.floor[25*f.width+120],1);
  assert.equal(r.floor[80*f.width+40],1);
  assert.equal(r.mask[45*f.width+40],1);
});

test('white observations outside a bounded corridor are not reclassified without unknown evidence',async()=>{
  const {beautifyMap}=await import(url),f=fixture(180,130);
  for(let y=0;y<f.height;y++)for(let x=0;x<f.width;x++)f.point(x,y,254);
  for(const y of [40,70])f.line(20,y,140);
  for(const x of [20,159])f.line(x,40,31,0,1);
  const r=beautifyMap(f);
  assert.equal(r.floor[55*f.width+90],1);
  assert.equal(r.floor[20*f.width+90],1);
  assert.equal(r.floor[110*f.width+90],1);
});

test('sparse white observations in a binary map are not greyed by a density threshold',async()=>{
  const {beautifyMap}=await import(url),f=fixture(30,30);
  for(let y=0;y<30;y++)for(let x=0;x<30;x++)f.point(x,y,0);
  f.point(12,12,254);f.point(20,20,254);f.point(20,21,254);f.point(21,20,254);f.point(21,21,254);
  const r=beautifyMap(f);assert.equal(r.stats.majorityRegions,0);
  for(const [x,y] of [[12,12],[20,20],[20,21],[21,20],[21,21]])assert.equal(r.floor[y*30+x],1);
});

test('an observed island surrounded by unknown is retained when its wall enclosure has less than half unknown',async()=>{
  const {beautifyMap}=await import(url),f=fixture(180,180);
  for(let y=0;y<180;y++)for(let x=0;x<180;x++)f.point(x,y,254);
  for(const y of [10,169])f.line(10,y,160);
  for(const x of [10,169])f.line(x,10,160,0,1);
  for(let y=50;y<130;y++)for(let x=50;x<130;x++)f.point(x,y,205);
  for(let y=80;y<100;y++)for(let x=80;x<100;x++)f.point(x,y,254);
  const r=beautifyMap(f);assert.equal(r.stats.majorityRegions,0);
  for(let y=80;y<100;y++)for(let x=80;x<100;x++)assert.equal(r.floor[y*180+x],1);
});

test('unknown outside a broken room boundary cannot bypass a saved virtual wall',async()=>{
  const {beautifyMap}=await import(url),f=virtualRoomFixture(85);
  // Both rooms leak into the same unobserved outside space, but that is not
  // an observed passage connecting them around the saved wall.
  for(let y=25;y<40;y++)f.point(10,y,205);
  for(let y=100;y<115;y++)f.point(189,y,205);
  const r=beautifyMap(f);
  assert.equal(r.floor[30*200+30],1,'the main observed passage stays white');
  assert.equal(r.floor[100*200+30],0,'room flecks must not survive through unknown exterior');
  assert.equal(r.floor[5*200+5],0,'outside unknown must not become a passage');
  assert.equal(r.mask[110*200+150],1,'physical features survive the grey fill');
});

test('a small sealed cavity does not outrank the main observed corridor leaking into unknown',async()=>{
  const {beautifyMap}=await import(url),f=virtualRoomFixture(85);
  for(let y=25;y<40;y++)f.point(10,y,205);
  const r=beautifyMap(f);
  assert.equal(r.floor[30*200+30],1);
  assert.equal(r.floor[100*200+30],0);
});

test('saved virtual wall endpoints tolerate a two-cell offset from the physical boundary',async()=>{
  const {beautifyMap}=await import(url),f=virtualRoomFixture(85);
  f.virtualWalls=[{points:[{x:81,y:85},{x:108,y:85}]}];
  const r=beautifyMap({...f,passagePoints:[{x:30,y:30}]});
  assert.equal(r.floor[30*200+30],1);
  assert.equal(r.floor[100*200+30],0,'sub-pixel drawing offsets must not reconnect sealed rooms');
});

test('a start on unknown floor selects its nearby room rather than a larger room through exterior unknown',async()=>{
  const {beautifyMap}=await import(url),f=virtualRoomFixture(85);
  for(let y=25;y<40;y++)f.point(10,y,205);
  for(let y=100;y<115;y++)f.point(189,y,205);
  for(let y=90;y<125;y++)for(let x=15;x<50;x++)f.point(x,y,205);
  const r=beautifyMap({...f,passagePoints:[{x:30,y:107}]});
  assert.equal(r.floor[107*200+80],1);
  assert.equal(r.floor[30*200+30],0);
});

test('ten-centimetre analysis tolerance does not close a one-metre doorway in a coarse map',async()=>{
  const {beautifyMap}=await import(url),f=virtualRoomFixture(85);
  f.resolution=.5;
  for(let x=80;x<110;x++)if(x!==99&&x!==100)f.point(x,85);
  f.virtualWalls=[{points:[{x:20,y:110},{x:30,y:110}]}];
  const r=beautifyMap({...f,passagePoints:[{x:30,y:30}]});
  assert.equal(r.floor[100*200+60],1,'a genuine open doorway must retain connectivity');
});

test('an analysis-only wall closing over a valid start does not discard its room priority',async()=>{
  const {beautifyMap}=await import(url),f=fixture(64,32);
  for(const [left,top,right,bottom]of[[5,5,19,19],[25,5,58,26]]) {
    for(let y=top+1;y<bottom;y++)for(let x=left+1;x<right;x++)f.point(x,y,254);
    f.line(left,top,right-left+1);f.line(left,bottom,right-left+1);
    f.line(left,top,bottom-top+1,0,1);f.line(right,top,bottom-top+1,0,1);
  }
  for(let y=8;y<=15;y++)if(y!==11)f.point(10,y);
  const r=beautifyMap({...f,virtualWalls:[{points:[{x:45,y:10},{x:45,y:15}]}],passagePoints:[{x:10,y:11}]});
  assert.equal(r.mask[11*64+10],0,'analysis tolerance cannot paint a physical obstacle');
  assert.equal(r.floor[11*64+10],1,'a valid observed start stays white');
  assert.equal(r.floor[13*64+15],1,'start room takes priority even when analysis closes a nearby wall gap');
  assert.equal(r.floor[20*64+50],0);
});

test('sparse slightly staggered walls bridge a short break despite scattered white observations on both sides',async()=>{
  const {beautifyMap}=await import(url);
  for(const vertical of[false,true]) {
    const f=fixture(180,180),at=(a,b,v=0)=>f.point(vertical?b:a,vertical?a:b,v);
    for(let y=20;y<150;y++)for(let x=20;x<150;x++)if((x+y)%3===0)f.point(x,y,254);
    for(let a=20;a<150;a++)if(a%2===0&&(a<75||a>85))at(a,80+(a%4===0?1:0));
    const source=f.rgba.slice(),r=beautifyMap(f);
    assert.equal(r.mask[80*180+80],1,'supported half-metre wall gap should be repaired');
    assert.deepEqual(f.rgba,source);
  }
});

test('short-wall fitting preserves coherent observed crossings, paired jambs and transparent gaps',async()=>{
  const {beautifyMap}=await import(url);
  for(const kind of['crossing','jambs','transparent']) {
    const f=fixture(180,100);
    f.line(20,50,55);f.line(86,50,64);
    if(kind==='crossing')for(let y=40;y<=60;y++)for(let x=65;x<=96;x++)if(y!==50||x>=75&&x<=85)f.point(x,y,254);
    if(kind==='jambs'){f.line(74,50,6,0,1);f.line(86,50,6,0,1);}
    if(kind==='transparent')for(let x=75;x<=85;x++)f.rgba[(50*180+x)*4+3]=0;
    const r=beautifyMap(f);
    for(let x=75;x<=85;x++)assert.equal(r.mask[50*180+x],0,kind);
  }
});

test('fitted wall repairs reject a transparent auxiliary cell at a staggered step',async()=>{
  const {beautifyMap}=await import(url),f=fixture(180,100);
  f.line(20,50,55);f.line(86,51,64);
  f.rgba[(50*180+80)*4+3]=0;
  const r=beautifyMap(f);
  assert.equal(r.mask[50*180+80],0,'supercover cannot write into a transparent crop');
  assert.equal(r.mask[51*180+80],0,'reject the complete bridge, not just the transparent cell');
});

test('short one-sided door jambs cannot borrow adjacent wall support to draw a parallel closure',async()=>{
  const {beautifyMap}=await import(url);
  for(const vertical of[false,true])for(const length of[2,3,4]) {
    const f=fixture(180,180),at=(a,b,v=0)=>f.point(vertical?b:a,vertical?a:b,v);
    for(let a=20;a<150;a++)if(a<75||a>85)at(a,50);
    for(let a=65;a<=96;a++)for(let b=51;b<=75;b++)at(a,b,254);
    for(let a=75;a<=85;a++)at(a,50,254);
    for(const a of[74,86])for(let b=50-length;b<=50;b++)at(a,b);
    const r=beautifyMap(f);
    for(let a=75;a<=85;a++)for(let b=46;b<=50;b++)
      assert.equal(r.mask[(vertical?a:b)*180+(vertical?b:a)],0,`${vertical}:${length}:${a},${b}`);
  }
});

test('without a start a wall-supported circulation enclosure outranks a slightly larger unbounded white field',async()=>{
  const {beautifyMap}=await import(url),f=fixture(220,190);
  for(let y=11;y<100;y++)for(let x=16;x<100;x++)f.point(x,y,254);
  for(const y of[10,100])f.line(15,y,86);
  for(const x of[15,100])f.line(x,10,91,0,1);
  for(let x=45;x<=65;x++)f.point(x,100,254);
  for(let y=115;y<185;y++)for(let x=20;x<145;x++)f.point(x,y,254);
  const r=beautifyMap({...f,virtualWalls:[{points:[{x:44,y:100},{x:66,y:100}]}]});
  assert.equal(r.floor[40*220+40],1,'retain the physically bounded circulation space');
  assert.equal(r.floor[145*220+60],0,'outside white field is not the intended main space');
});

test('a small manually enclosed hall is independent of exterior white canvas size or unknown borders',async()=>{
  const {beautifyMap}=await import(url);
  for(const border of [0,15]) {
    const f=fixture(500,400);
    for(let y=border;y<f.height-border;y++)for(let x=border;x<f.width-border;x++)f.point(x,y,254);
    f.line(50,50,151);f.line(50,50,41,0,1);f.line(200,50,41,0,1);
    const r=beautifyMap({...f,virtualWalls:[{points:[{x:50,y:90},{x:200,y:90}]}]});
    assert.equal(r.floor[70*f.width+100],1,`hall with ${border}px unknown border`);
    assert.equal(r.floor[200*f.width+300],0,'exterior white is background');
  }
});

test('a small enclosed object cannot displace an already strongly wall-supported open passage',async()=>{
  const {beautifyMap}=await import(url),f=fixture(500,400);
  for(let i=0;i<f.width*f.height;i++)f.rgba.set([254,254,254,255],i*4);
  for(let y=110;y<390;y+=10)f.line(20,y,461);
  f.line(50,50,151);f.line(50,50,41,0,1);f.line(200,50,41,0,1);
  const r=beautifyMap({...f,virtualWalls:[{points:[{x:50,y:90},{x:200,y:90}]}]});
  assert.equal(r.floor[201*f.width+301],1,'retain the substantial open passage');
  assert.equal(r.floor[70*f.width+100],0,'a small closure alone is not a main passage');
});

test('black-white maps do not let a much larger edge-connected background displace a manually enclosed hall',async()=>{
  const {beautifyMap}=await import(url),f=fixture(500,400);
  for(let i=0;i<f.width*f.height;i++)f.rgba.set([254,254,254,255],i*4);
  f.line(50,50,301);f.line(50,50,51,0,1);f.line(350,50,51,0,1);
  const virtualWalls=[{points:[{x:50,y:100},{x:350,y:100}]}];
  const r=beautifyMap({...f,virtualWalls});
  assert.equal(r.floor[75*500+150],1,'the enclosed hall stays white without a start');
  assert.equal(r.floor[350*500+450],0,'outer white background must not win on area');
  const explicit=beautifyMap({...f,virtualWalls,passagePoints:[{x:450,y:350}]});
  assert.equal(explicit.floor[350*500+450],1,'an explicit outdoor start still takes priority');
});

test('automatic circulation selection uses manual closure support rather than picking a slightly larger side room',async()=>{
  const {beautifyMap}=await import(url),f=fixture(500,400);
  for(let i=0;i<f.width*f.height;i++)f.rgba.set([254,254,254,255],i*4);
  f.line(50,50,301);f.line(50,50,51,0,1);f.line(350,50,51,0,1);
  for(const y of[180,245])f.line(50,y,301);
  for(const x of[50,350])f.line(x,180,66,0,1);
  for(let x=190;x<=210;x++)f.point(x,245,254);
  const r=beautifyMap({...f,virtualWalls:[
    {points:[{x:50,y:100},{x:350,y:100}]},
    {points:[{x:189,y:245},{x:211,y:245}]},
  ]});
  assert.equal(r.floor[75*500+150],1,'retain the manually enclosed circulation');
  assert.equal(r.floor[210*500+150],0,'a larger side room with only a capped door stays grey');
});
