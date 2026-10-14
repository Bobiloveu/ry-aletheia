import test from 'node:test';
import assert from 'node:assert/strict';

test('viewing export draws authoritative grey virtual walls over the finished surface',async()=>{
  const {createMapImageCanvas}=await import('../../../autodrive_console/web/deployment/map-image-export.js');
  for(const outlined of [false,true]) {
    const calls=[],context=new Proxy({},{get:(_,k)=>(...a)=>calls.push([k,...a]),set:(_,k,v)=>{calls.push([k,v]);return true;}});
    const map={id:'a',width:100,height:80,resolution_m:.05,origin:[-2,-1]};
    const edits=[{map_asset_id:'a',kind:'brush_erase',radius_m:.4,points:[{x:-1,y:0},{x:0,y:0}]}];
    createMapImageCanvas({document:{createElement:()=>({getContext:()=>context})},surface:{width:100,height:80},map,edits,
      paintEdits:outlined?()=>{calls.push(['outlinedErase']);return true;}:undefined,
      virtualWalls:[{map_asset_id:'a',points:[{x:-1,y:0},{x:0,y:0}]}]});
    const lastStroke=calls.findLastIndex(c=>c[0]==='stroke');
    assert.ok(lastStroke>calls.findIndex(c=>c[0]==='drawImage'));
    assert.equal(calls.some(c=>c[0]==='outlinedErase'||c[0]==='arc'),false);
    assert.deepEqual(calls.filter(c=>c[0]==='strokeStyle').at(-1),['strokeStyle','#8b99a7']);
    assert.deepEqual(calls.filter(c=>c[0]==='lineTo').at(-1),['lineTo',40,60]);
  }
});

test('viewing export preserves the final boundary without calling an obsolete edit painter',async()=>{
  const {createMapImageCanvas}=await import('../../../autodrive_console/web/deployment/map-image-export.js');
  const context={fillRect(){},drawImage(){},save(){throw Error('plain erase would remove the boundary');}};
  const canvas={getContext:()=>context},surface={width:8,height:8},map={id:'a',width:8,height:8,resolution_m:.05,origin:[0,0]};
  const edits=[{map_asset_id:'a',kind:'polygon_erase',points:[{x:0,y:0},{x:.1,y:0},{x:.1,y:.1}]}];
  let calls=0;
  createMapImageCanvas({document:{createElement:()=>canvas},surface,map,edits,paintEdits(args){
    calls++;assert.equal(args.context,context);assert.equal(args.map,map);assert.equal(args.edits,edits);
    assert.deepEqual(args.view,{x:0,y:0,scale:20});return true;
  }});
  assert.equal(calls,0);
});

test('viewing export uses native prepared pixels without replaying saved erases from any map',async()=>{
  const {createMapImageCanvas}=await import('../../../autodrive_console/web/deployment/map-image-export.js');
  const calls=[];
  const context=new Proxy({},{get:(_,key)=> (...args)=>calls.push([key,...args]),set:(_,key,value)=>{calls.push([key,value]);return true;}});
  const canvas={getContext:()=>context};
  const map={id:'a',width:100,height:80,resolution_m:.05,origin:[-2,-1]};
  const surface={width:100,height:80};
  const edits=[{map_asset_id:'a',kind:'brush_erase',radius_m:.4,points:[{x:-1,y:0}]},
    {map_asset_id:'a',kind:'polygon_erase',points:[{x:-2,y:-1},{x:-1,y:-1},{x:-1,y:0}]},
    {map_asset_id:'b',kind:'brush_erase',radius_m:1,points:[{x:0,y:0}]}];
  assert.equal(createMapImageCanvas({document:{createElement:()=>canvas},surface,map,edits}),canvas);
  assert.equal(canvas.width,100);assert.equal(canvas.height,80);
  assert.deepEqual(calls.find(c=>c[0]==='drawImage'),['drawImage',surface,0,0]);
  assert.deepEqual(calls.filter(c=>c[0]==='arc'),[]);
  assert.equal(calls.filter(c=>c[0]==='closePath').length,0);
  assert.equal(calls.some(c=>c[0]==='fillStyle'&&c[1]==='#fff'),false);
  assert.equal(calls.some(c=>['fillText','strokeText'].includes(c[0])),false);
});

test('viewing export rejects an absent or differently sized prepared map',async()=>{
  const {createMapImageCanvas}=await import('../../../autodrive_console/web/deployment/map-image-export.js');
  const map={width:100,height:80,resolution_m:.05,origin:[0,0]};
  for(const surface of [null,{width:80,height:100}])assert.throws(()=>createMapImageCanvas({surface,map}),/地图/);
});
