import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const moduleUrl = '../../../autodrive_console/web/deployment/map-display.js';
const pixels = values => Uint8ClampedArray.from(values.flatMap(v => [v,v,v,255]));

test('raw viewing uses black obstacles and white free or unknown cells without changing source pixels', async()=>{
  const {mapMonochromePixels}=await import(moduleUrl);
  const source=pixels([0,100,204,205,254,255]);source[23]=0;
  const before=source.slice(), result=mapMonochromePixels(source);
  assert.deepEqual([...result], [...pixels([0,0,0,255,255,255]).slice(0,23),0]);
  assert.deepEqual(source,before);
});

test('raw drawing shares source decoding and preserves every feature at reduced scale', async()=>{
  const {createMapDisplay}=await import(moduleUrl);
  const document=displayDocument([0,205,254,0]), workers=[];
  const display=createMapDisplay(document,{workerFactory:()=>{const w={postMessage(){},terminate(){}};workers.push(w);return w;}});
  const image={naturalWidth:2,naturalHeight:2};display.setImage(image,{resolution:.05});
  const calls=[],context={canvas:{width:1,height:1},drawImage:(...args)=>calls.push(args),save(){},restore(){},beginPath(){},rect(){},clip(){}};
  assert.equal(display.drawRaw({context,image,activeMap:{width:2,height:2,resolution_m:.05},view:{x:0,y:0,scale:10},canvasBox:{width:1,height:1},process:true}),true);
  assert.equal(workers.length,1);
  assert.deepEqual([...calls[0][0].output], [...pixels([0,255,255,0])]);
  assert.deepEqual([...calls[1][0].output], [0,0,0,255]);
});
function displayDocument(values) {
  const surfaces=[];
  return {surfaces,createElement() {
    const canvas={width:0,height:0,reads:0,output:null};
    const ctx={drawImage(){},getImageData(){canvas.reads++;return {data:pixels(values)};},
      putImageData(data){canvas.output=data.data.slice();},
      createImageData(w,h){return {data:new Uint8ClampedArray(w*h*4)};}};
    canvas.getContext=()=>ctx; surfaces.push(canvas); return canvas;
  }};
}

test('caught map worker failures report diagnostics while keeping the original preview',async()=>{
  const {createMapDisplay}=await import(moduleUrl),previous=globalThis.RYAletheiaDiagnostics,failures=[];
  globalThis.RYAletheiaDiagnostics={failure:(operation,error)=>failures.push({operation,error})};
  let worker;
  const phases=[];
  const display=createMapDisplay(displayDocument([0,254,205,0]),{bitmapFactory:async()=>({width:2,height:2}),
    workerFactory:()=>worker={postMessage(){},terminate(){}},onChange:state=>phases.push(state.phase)});
  try {
    display.setImage({naturalWidth:2,naturalHeight:2},{resolution:.05});await Promise.resolve();
    worker.onmessage({data:{error:'decode failed'}});
    assert.equal(phases.at(-1),'fallback');assert.equal(failures[0]?.operation,'deployment.map-display');
    assert.equal(failures[0]?.error,'decode failed');
  }finally{display.setImage(null);globalThis.RYAletheiaDiagnostics=previous;}
});

test('architectural fit view reuses the native rendered outline; enlarged view redraws vector edges',async()=>{
  const {createMapDisplay}=await import(moduleUrl);let worker;
  const display=createMapDisplay(displayDocument([0,254,205,0]),{bitmapFactory:async()=>({width:2,height:2}),workerFactory:()=>worker={postMessage(){},terminate(){}}});
  const image={naturalWidth:2,naturalHeight:2};display.setImage(image,{resolution:.05});await Promise.resolve();
  worker.onmessage({data:{result:{bitmap:{width:2,height:2},features:new Uint32Array(),shades:new Uint8Array(),architecture:{resolution:.05,vertices:new Uint32Array([0,0,2,0,2,2,0,2]),offsets:new Uint32Array([0,4])}}}});
  let strokes=0;
  const context={canvas:{width:10,height:10},drawImage(){},save(){},restore(){},beginPath(){},rect(){},clip(){},moveTo(){},lineTo(){},closePath(){},stroke(){strokes++;}};
  const options={context,image,activeMap:{width:2,height:2,resolution_m:.05},canvasBox:{width:10,height:10},process:true};
  assert.equal(display.draw({...options,view:{x:0,y:0,scale:10}}),true);assert.equal(strokes,0);
  assert.equal(display.draw({...options,view:{x:0,y:0,scale:40}}),true);assert.equal(strokes,1);
});

test('bitmap preparation keeps whole-map decoding off the UI thread and exports only the finished surface',async()=>{
  const {createMapDisplay}=await import(moduleUrl),document=displayDocument([0,254,205,0]);
  const workers=[],states=[],bitmap={width:2,height:2,close(){this.closed=true;}};
  const display=createMapDisplay(document,{bitmapFactory:async()=>bitmap,
    workerFactory:()=>{const w={postMessage(data,transfer){this.input=data;this.transfer=transfer;},terminate(){}};workers.push(w);return w;},onChange:s=>states.push(s)});
  display.setImage({naturalWidth:2,naturalHeight:2},{resolution:.05});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(document.surfaces.length,0,'no full-size canvas allocation or readback on the UI thread');
  assert.equal(workers[0].input.bitmap,bitmap);
  assert.deepEqual(workers[0].transfer,[bitmap]);
  const preview={width:2,height:2,close(){this.closed=true;}},raw={width:2,height:2,close(){this.closed=true;}};
  workers[0].onmessage({data:{preview:{surface:preview,rawSurface:raw,features:new Uint32Array([0,3]),shades:new Uint8Array([0,0])}}});
  assert.equal(display.getExportSurface(),null);
  const finished={width:2,height:2,close(){this.closed=true;}};
  workers[0].onmessage({data:{result:{bitmap:finished,features:new Uint32Array([0,3]),shades:new Uint8Array([0,0]),stats:{}}}});
  assert.equal(display.getExportSurface(),finished);
  assert.equal(preview.closed,true);assert.equal(states.at(-1).phase,'ready');
  display.setImage(null);assert.equal(finished.closed,true);assert.equal(raw.closed,true);
});

test('switching maps closes a pending bitmap and any obsolete worker surfaces',async()=>{
  const {createMapDisplay}=await import(moduleUrl),requests=[],workers=[];
  const display=createMapDisplay(displayDocument([0,254,205,0]),{
    bitmapFactory:()=>new Promise(resolve=>requests.push(resolve)),
    workerFactory:()=>{const w={postMessage(){this.sent=true;},terminate(){this.stopped=true;}};workers.push(w);return w;},
  });
  display.setImage({naturalWidth:2,naturalHeight:2},{resolution:.05});
  const obsolete=workers[0].onmessage;
  display.setImage({naturalWidth:2,naturalHeight:2},{resolution:.05});
  const stale={close(){this.closed=true;}};requests[0](stale);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(stale.closed,true);assert.equal(workers[0].sent,undefined);assert.equal(workers[0].stopped,true);
  const surface={close(){this.closed=true;}},rawSurface={close(){this.closed=true;}};
  obsolete({data:{preview:{surface,rawSurface}}});assert.equal(surface.closed,true);assert.equal(rawSurface.closed,true);
  const result={close(){this.closed=true;}};obsolete({data:{result:{bitmap:result}}});assert.equal(result.closed,true);
  display.setImage(null);
});

test('closure geometry filters map ownership and converts saved walls and start anchors to native pixels',async()=>{
  const {mapClosureGeometry}=await import(moduleUrl);
  const map={id:'a',width:100,height:80,resolution_m:.05,origin:[-2,-1]};
  const walls=[{map_asset_id:'a',points:[{x:-1,y:0},{x:0,y:0}]},{map_asset_id:'b',points:[{x:-1,y:0},{x:0,y:0}]}];
  const anchors=[{map_asset_id:'a',kind:'start',x:0,y:0},{map_asset_id:'a',kind:'goal',x:1,y:0},{map_asset_id:'b',kind:'start',x:0,y:0}];
  assert.deepEqual(mapClosureGeometry(map,walls,anchors),{virtualWalls:[{points:[{x:20,y:60},{x:40,y:60}]}],passagePoints:[{x:40,y:60}]});
});

test('saved wall and start changes invalidate display work and disable stale exports',async()=>{
  const {createMapDisplay}=await import(moduleUrl);const workers=[];
  const display=createMapDisplay(displayDocument([0,254,205,0]),{workerFactory:()=>{const w={postMessage(data){this.input=data},terminate(){this.stopped=true}};workers.push(w);return w;}});
  const image={naturalWidth:2,naturalHeight:2};const options={resolution:.05,virtualWalls:[{points:[{x:0,y:0},{x:1,y:1}]}],passagePoints:[{x:1,y:0}]};
  display.setImage(image,options);
  assert.deepEqual(workers[0].input.virtualWalls,options.virtualWalls);
  assert.deepEqual(workers[0].input.passagePoints,options.passagePoints);
  display.setImage(image,{...options,virtualWalls:[]});assert.equal(workers.length,2);assert.equal(workers[0].stopped,true);
  display.setImage(image,{...options,virtualWalls:[],passagePoints:[{x:0,y:1}]});assert.equal(workers.length,3);
  assert.equal(display.getExportSurface(),null);
});

test('cleanup runs in a cancellable worker and late results cannot replace another map', async()=>{
  const {createMapDisplay}=await import(moduleUrl);const document=displayDocument([0,254,205,0]);
  const workers=[],states=[];
  const display=createMapDisplay(document,{workerFactory:()=>{const w={postMessage(data){this.input=data;},terminate(){this.stopped=true;}};workers.push(w);return w;},onChange:s=>states.push(s)});
  const a={naturalWidth:2,naturalHeight:2},b={naturalWidth:2,naturalHeight:2};
  display.setImage(a,{resolution:.05});assert.equal(workers.length,1);
  const old=workers[0].onmessage;
  display.setImage(b,{resolution:.05});assert.equal(workers[0].stopped,true);
  old({data:{result:{rgba:pixels([0,0,0,0]),features:new Uint32Array([0]),shades:new Uint8Array([0]),removed:new Uint32Array(),added:new Uint32Array(),stats:{removed:0,added:0}}}});
  assert.notEqual(states.at(-1).phase,'ready');
  workers[1].onmessage({data:{result:{rgba:pixels([0,254,205,0]),features:new Uint32Array([0,3]),shades:new Uint8Array([0,0]),removed:new Uint32Array(),added:new Uint32Array(),stats:{removed:0,added:0}}}});
  assert.equal(states.at(-1).phase,'ready');assert.equal(workers[1].stopped,true);
  display.setImage(b,{resolution:.05});assert.equal(workers.length,2);
  display.setImage(b,{resolution:.05,protectedPoints:[{x:1,y:1,radius:2}]});assert.equal(workers.length,3);
  display.setImage(null);assert.equal(workers[2].stopped,true);
});

test('worker failure falls back with an explicit unavailable state rather than claiming cleanup is ready',async()=>{
  const {createMapDisplay}=await import(moduleUrl);const states=[];let worker;
  const display=createMapDisplay(displayDocument([0,254,205,0]),{onChange:s=>states.push(s),workerFactory:()=>worker={postMessage(){},terminate(){}}});
  display.setImage({naturalWidth:2,naturalHeight:2},{resolution:.05});worker.onerror({preventDefault(){}});
  assert.equal(states.at(-1).phase,'fallback');
});

test('a render before image decoding does not poison the later loaded-image cache', async () => {
  const {createMapDisplay}=await import(moduleUrl);
  const document=displayDocument([0,254,205,0]);
  const display=createMapDisplay(document),image={naturalWidth:0,naturalHeight:0};
  assert.equal(display.setImage(image),false);
  image.naturalWidth=image.naturalHeight=2;
  assert.equal(display.setImage(image),true);
  assert.equal(display.setImage(image),true);
  assert.equal(document.surfaces.reduce((n,c)=>n+c.reads,0),1);
});

test('feature pooling uses device pixels and cached draws do not re-decode or re-pool', async () => {
  const {createMapDisplay}=await import(moduleUrl);
  const values=Array(100).fill(254); for (const i of [11,15,51,55]) values[i]=0;
  const document=displayDocument(values),display=createMapDisplay(document);
  const image={naturalWidth:10,naturalHeight:10};
  const calls=[];
  const context={canvas:{width:10,height:10},drawImage:(...args)=>calls.push(args),
    save(){},restore(){},beginPath(){},rect(){},clip(){}};
  const options={context,image,activeMap:{width:10,height:10,resolution_m:.05},
    canvasBox:{width:5,height:5},view:{x:0,y:0,scale:5}};
  display.draw(options);
  const overlay=document.surfaces[1],firstOutput=overlay.output;
  assert.deepEqual([...overlay.output.entries()].filter(([i,v])=>i%4===3&&v).map(([i])=>(i-3)/4),[0,2,20,22]);
  display.draw(options);
  assert.equal(document.surfaces[0].reads,1);
  assert.equal(overlay.output,firstOutput);
  assert.deepEqual(calls[1].slice(1),[0,0,5,5]);
  display.setImage(null);
  display.setImage(image);
  assert.equal(document.surfaces.length,3);
});

test('a decode failure returns control to the original-image renderer', async () => {
  const {createMapDisplay}=await import(moduleUrl);
  const display=createMapDisplay({createElement(){throw Error('allocation failed');}});
  assert.equal(display.setImage({naturalWidth:10,naturalHeight:10}),false);
});

test('a failed viewport allocation also falls back without aborting annotation drawing', async () => {
  const {createMapDisplay}=await import(moduleUrl);
  const document=displayDocument([0,254,205,0]),create=document.createElement;
  document.createElement=()=>{const surface=create();if(document.surfaces.length>1) surface.getContext=()=>null;return surface;};
  const display=createMapDisplay(document);
  const context={canvas:{width:1,height:1},drawImage(){}};
  assert.equal(display.draw({context,image:{naturalWidth:2,naturalHeight:2},
    activeMap:{width:2,height:2,resolution_m:.05},view:{x:0,y:0,scale:5},canvasBox:{width:1,height:1}}),false);
});

test('styling retains every dark feature, including isolated pixels and faint edges, without changing the source', async () => {
  const { mapDisplayPixels } = await import(moduleUrl);
  const source = pixels([0,254,205,1,204,128,255,0]);
  const before = source.slice();
  const result = mapDisplayPixels(source);
  assert.deepEqual(source,before);
  assert.deepEqual([...result.features],[0,3,4,5,7]);
  assert.deepEqual([...result.shades],[0,1,204,128,0]);
  assert.notDeepEqual([...result.rgba.slice(0,3)],[...result.rgba.slice(8,11)]);
  assert.notDeepEqual([...result.rgba.slice(4,7)],[...result.rgba.slice(8,11)]);
  for (let i=0;i<8;i++) assert.equal(result.rgba[i*4+3],255);
});

test('all 256 source tones remain ordered; recoloring never promotes a dark cell to the floor color', async () => {
  const { mapDisplayPixels } = await import(moduleUrl);
  const result = mapDisplayPixels(pixels(Array.from({length:256},(_,i)=>i)));
  for (let i=1;i<255;i++) {
    for (let channel=0;channel<3;channel++) assert.ok(result.rgba[i*4+channel] >= result.rgba[(i-1)*4+channel]);
  }
  assert.equal(result.features.length,205);
  assert.deepEqual([...result.rgba.slice(254*4,254*4+3)],[255,255,255]);
});

test('fit view keeps all four isolated feature locations that nearest-neighbor image sampling loses', async () => {
  const { rasterizeMapFeatures } = await import(moduleUrl);
  const mask = rasterizeMapFeatures(new Uint32Array([11,15,51,55]),new Uint8Array([0,12,128,204]),10,
    {width:5,height:5,x:0,y:0,scale:.5});
  assert.deepEqual([...mask.entries()].filter(([,v])=>v<205),[[0,0],[2,12],[10,128],[12,204]]);
});

test('overlapping features retain the darkest tone independent of source order', async () => {
  const { rasterizeMapFeatures } = await import(moduleUrl);
  const view={width:2,height:2,x:0,y:0,scale:.1};
  for (const shades of [[204,128,0],[0,128,204]]) {
    const mask=rasterizeMapFeatures(new Uint32Array([0,1,2]),new Uint8Array(shades),10,view);
    assert.equal(mask[0],0);
    assert.equal(mask[1],255);
  }
});

test('pan clipping never wraps scanlines or drops a partially visible edge cell', async () => {
  const { rasterizeMapFeatures } = await import(moduleUrl);
  const features=new Uint32Array([0]), shades=new Uint8Array([0]);
  for (const x of [-20,20]) assert.ok(rasterizeMapFeatures(features,shades,10,
    {width:5,height:5,x,y:0,scale:.5}).every(v=>v===255));
  assert.equal(rasterizeMapFeatures(features,shades,10,{width:5,height:5,x:-.4,y:0,scale:.5})[0],0);
});

test('both map appearances paint their virtual-wall layer after erases', async () => {
  const { drawDeploymentCanvas } = await import('../../../autodrive_console/web/deployment/canvas-renderer.js');
  const events=[];
  const context=new Proxy({drawImage:()=>events.push('raw')},{get:(o,k)=>o[k]||(()=>{})});
  const options={context,canvasBox:{width:10,height:10},activeMap:{id:'map',width:10,height:10,resolution_m:.05},mapImage:{},
    project:{},view:{scale:20,x:0,y:0},drawGrid(){},drawMapEdits:()=>events.push('erase'),
    drawVirtualWalls:()=>events.push('wall'),drawMapRoutes:()=>events.push('route'),
    drawMapBase:({mapAppearance})=>{events.push(mapAppearance);return true;}};
  drawDeploymentCanvas({...options,mapAppearance:'styled'});
  assert.deepEqual(events,['styled','erase','wall','route']);
  events.length=0;
  drawDeploymentCanvas({...options,mapAppearance:'raw'});
  assert.deepEqual(events,['raw','erase','wall','route']);
});

test('display controls expose a viewing-image export without the lower-left legend', () => {
  const html=readFileSync(new URL('../../../autodrive_console/web/deployment.html',import.meta.url),'utf8');
  assert.match(html,/id="styledMapView"[^>]*aria-pressed="false"/);
  assert.match(html,/id="rawMapView"[^>]*aria-pressed="true"/);
  assert.doesNotMatch(html,/id="mapDisplayLegend"/);
  assert.doesNotMatch(html,/id="(?:mapCleanupTools|mapNoiseToggle|mapChangesToggle|protectMapFeature|clearMapProtection)"/);
  assert.match(html,/id="exportMapImage"[^>]*disabled/);
});

test('export surface is available only after current-map cleanup succeeds',async()=>{
  const {createMapDisplay}=await import(moduleUrl);let worker;
  const display=createMapDisplay(displayDocument([0,254,205,0]),{workerFactory:()=>worker={postMessage(){},terminate(){}}});
  const image={naturalWidth:2,naturalHeight:2};
  display.setImage(image,{resolution:.05});assert.equal(display.getExportSurface(),null);
  worker.onmessage({data:{result:{rgba:pixels([0,254,205,0]),features:new Uint32Array([0,3]),shades:new Uint8Array([0,0]),removed:new Uint32Array(),added:new Uint32Array(),stats:{}}}});
  assert.ok(display.getExportSurface());
  display.setImage(image,{resolution:.05,removeIsolated:true});assert.equal(display.getExportSurface(),null);
  worker.onerror({preventDefault(){}});assert.equal(display.getExportSurface(),null);
  display.setImage(null);assert.equal(display.getExportSurface(),null);
});

test('manual protection takes precedence over a full set of existing annotations',async()=>{
  const {mapProtectionRegions}=await import(moduleUrl);
  const map={width:40,height:30,resolution_m:.05,origin:[-1,-2]};
  const manual=[{x:0,y:-1}],anchors=Array.from({length:300},()=>({x:-.5,y:-1.5}));
  const regions=mapProtectionRegions(map,manual,anchors);
  assert.equal(regions.length,256);assert.deepEqual(regions[0],{x:20,y:10,radius:8});
});
test('failed bitmap drawing closes both surfaces and disables export',async()=>{
  const {createMapDisplay}=await import(moduleUrl);let worker;
  const document={createElement:()=>({getContext:()=>null})},image={naturalWidth:2,naturalHeight:2};
  const surface=()=>({width:2,height:2,closed:0,close(){this.closed++;}}),preview=surface(),raw=surface(),finished=surface();
  const display=createMapDisplay(document,{workerFactory:()=>worker={postMessage(){},terminate(){}},bitmapFactory:async()=>surface()});
  display.setImage(image,{resolution:.05});await Promise.resolve();
  worker.onmessage({data:{preview:{surface:preview,rawSurface:raw,features:new Uint32Array([0]),shades:new Uint8Array([0])}}});
  worker.onmessage({data:{result:{bitmap:finished,features:new Uint32Array([0]),shades:new Uint8Array([0]),removed:new Uint32Array(),added:new Uint32Array()}}});
  const context={canvas:{width:1,height:1},drawImage(){}};
  assert.equal(display.draw({context,image,activeMap:{width:2,height:2,resolution_m:.05},view:{scale:5,x:0,y:0},canvasBox:{width:1,height:1},process:true}),false);
  assert.equal(finished.closed,1);assert.equal(raw.closed,1);assert.equal(display.getExportSurface(),null);
  display.setImage(null);assert.equal(finished.closed,1);
});

test('overlay allocation failure restores canvas state before raw fallback',async()=>{
  const {createMapDisplay}=await import(moduleUrl);const document=displayDocument([0,254,205,0]);let worker;
  const display=createMapDisplay(document,{workerFactory:()=>worker={postMessage(){},terminate(){}}});
  const image={naturalWidth:2,naturalHeight:2};display.setImage(image,{resolution:.05});
  worker.onmessage({data:{result:{rgba:pixels([0,254,205,0]),features:new Uint32Array([0,3]),shades:new Uint8Array([0,0]),removed:new Uint32Array([0]),added:new Uint32Array(),stats:{removed:1,added:0}}}});
  document.createElement=()=>({getContext:()=>null});display.setShowChanges(true);let depth=0;
  const context={canvas:{width:20,height:20},drawImage(){},save(){depth++;},restore(){depth--;},beginPath(){},rect(){},clip(){}};
  assert.equal(display.draw({context,image,activeMap:{width:2,height:2,resolution_m:.05},view:{scale:20,x:0,y:0},canvasBox:{width:20,height:20},process:true}),false);
  assert.equal(depth,0);
});

test('raw-only bitmap preparation never requests topology and cached drawing never prepares again',async()=>{
 const {createMapDisplay}=await import(moduleUrl),document=displayDocument([0,254,205,0]),workers=[],states=[];
 const display=createMapDisplay(document,{bitmapFactory:async()=>({width:2,height:2}),workerFactory:()=>{const w={postMessage(data){this.input=data;},terminate(){this.stopped=true;}};workers.push(w);return w;},onChange:s=>states.push(s)});
 const image={naturalWidth:2,naturalHeight:2};display.setImage(image,{mode:'raw',resolution:.05});await Promise.resolve();
 assert.equal(workers[0].input.rawOnly,true);assert.equal(document.surfaces.length,0);
 const bitmap={width:2,height:2};workers[0].onmessage({data:{result:{bitmap,features:new Uint32Array(),shades:new Uint8Array()}}});
 assert.equal(workers[0].stopped,true);assert.equal(states.at(-1).phase,'raw-ready');assert.equal(display.getExportSurface(),null);
 const context={canvas:{width:2,height:2},drawImage(){},save(){},restore(){},beginPath(){},rect(){},clip(){}};
 for(let i=0;i<30;i++)assert.equal(display.drawRaw({context,image,activeMap:{width:2,height:2,resolution_m:.05},view:{x:0,y:0,scale:20},canvasBox:{width:2,height:2},prepare:false}),true);
 assert.equal(workers.length,1);assert.equal(document.surfaces.length,0);
});
test('worker URL decoding avoids copying a large HTML image on the UI thread',async()=>{
 const {createMapDisplay}=await import(moduleUrl);let worker,copies=0;
 const display=createMapDisplay({createElement(){throw Error('UI canvas');}},{sourceFactory:()=>'/snapshot.png',bitmapFactory:()=>{copies++;throw Error('UI bitmap copy');},workerFactory:()=>worker={postMessage(data){this.input=data;},terminate(){}}});
 display.setImage({naturalWidth:3480,naturalHeight:10017},{mode:'raw'});
 assert.equal(copies,0);assert.equal(worker.input.sourceUrl,'/snapshot.png');assert.equal(worker.input.rawOnly,true);
});

test('saved wall paint reaches the worker in world coordinates without a main-thread raster allocation',async()=>{
  const {createMapDisplay}=await import(moduleUrl),document=displayDocument([254,254,254,254]);let sent;
  const display=createMapDisplay(document,{bitmapFactory:async()=>({width:2,height:2}),sourceFactory:()=>'/preview.png',workerFactory:()=>({postMessage(data){sent=data;},terminate(){}})});
  const rasterMap={id:'a',width:2,height:2,resolution_m:.05,origin:[-1,-2,0]};
  const mapEdits=[{map_asset_id:'a',kind:'brush_erase',mode:'wall',radius_m:.05,points:[{x:-.95,y:-1.95}]}];
  display.setImage({naturalWidth:2,naturalHeight:2},{resolution:.05,rasterMap,mapEdits});
  assert.deepEqual(sent.mapEdits,mapEdits);assert.deepEqual(sent.rasterMap,rasterMap);
  assert.equal(document.surfaces.length,0);
});
