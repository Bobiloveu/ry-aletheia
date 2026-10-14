import test from 'node:test';
import assert from 'node:assert/strict';

const moduleUrl='../../../autodrive_console/web/deployment/map-edit-outline.js';
test('erased entrance joins the passage into one outline without a line across its mouth',async()=>{
  const {buildEditedMapTile}=await import(moduleUrl);
  const map={width:8,height:8,resolution_m:.05};
  const bits=new Uint8Array(8);bits[0]=bits[1]=255;
  const before=bits.slice(),erase=new Uint8ClampedArray(8*8*4);
  for(let y=1;y<6;y++)for(let x=3;x<5;x++)erase.set([255,255,255,255],(y*8+x)*4);
  const result=buildEditedMapTile({floorBits:bits,map,x:0,y:0,width:8,height:8,erase});
  const v=[...result.architecture.vertices];
  assert.deepEqual(v,[0,0,8,0,8,2,5,2,5,6,3,6,3,2,0,2]);
  assert.deepEqual([...result.architecture.offsets],[0,8]);
  assert.deepEqual([...result.rgba.slice((4*8+3)*4,(4*8+3)*4+4)],[255,255,255,255]);
  assert.deepEqual([...result.rgba.slice((4*8+2)*4,(4*8+2)*4+4)],[231,236,242,255]);
  assert.deepEqual(bits,before);
});

test('tile halos read adjacent floor cells correctly across byte and tile boundaries',async()=>{
  const {buildEditedMapTile}=await import(moduleUrl);
  const map={width:13,height:4,resolution_m:.05},bits=new Uint8Array(7);
  for(let y=0;y<4;y++)for(let x=5;x<10;x++){const i=y*13+x;bits[i>>3]|=1<<(i&7);}
  const tile=buildEditedMapTile({floorBits:bits,map,x:4,y:1,width:7,height:2,erase:new Uint8ClampedArray(7*2*4)});
  assert.deepEqual([...tile.floor],[0,1,1,1,1,1,0,0,1,1,1,1,1,0]);
  assert.deepEqual([...tile.architecture.vertices],[1,0,6,0,6,2,1,2]);
});

function patchDocument() {
  let allocations=0;
  const document={createElement(){allocations++;const canvas={};const ctx={save(){},restore(){},
    beginPath(){},closePath(){},moveTo(){},lineTo(){},fill(){},stroke(){},arc(){},
    getImageData:()=>({data:new Uint8ClampedArray(canvas.width*canvas.height*4)}),
    createImageData:(w,h)=>({data:new Uint8ClampedArray(w*h*4)}),putImageData(){}};
    canvas.getContext=()=>ctx;return canvas;}};
  return {document,count:()=>allocations};
}
test('saved edit patches reuse native tiles across zoom, reset for new floors and clear on undo',async()=>{
  const {createMapEditOutline}=await import(moduleUrl),f=patchDocument(),painter=createMapEditOutline(f.document);
  const map={id:'a',width:4,height:4,resolution_m:.05,origin:[0,0]},floorBits=new Uint8Array([255,0]);
  const edits=[{map_asset_id:'a',kind:'brush_erase',radius_m:.05,points:[{x:.1,y:.1}]}];
  let draws=0;const context={save(){},restore(){},drawImage(){draws++;}};
  const args={context,floorBits,map,view:{x:0,y:0,scale:10},edits};
  assert.equal(painter.paint(args),true);assert.equal(f.count(),1);
  painter.paint({...args,view:{x:50,y:100,scale:20}});assert.equal(f.count(),1);assert.equal(draws,2);
  painter.paint({...args,floorBits:floorBits.slice()});assert.equal(f.count(),2);
  const before=draws;painter.paint({...args,edits:[]});assert.equal(draws,before);
  painter.clear();painter.paint(args);assert.equal(f.count(),3);
});

test('enlarged patch drawing restores all clipping states if a contour stroke fails',async()=>{
  const {createMapEditOutline}=await import(moduleUrl),f=patchDocument(),painter=createMapEditOutline(f.document);
  let depth=0;const context={save(){depth++;},restore(){depth--;},drawImage(){},beginPath(){},rect(){},clip(){},
    moveTo(){},lineTo(){},closePath(){},stroke(){throw Error('canvas unavailable');}};
  assert.throws(()=>painter.paint({context,floorBits:new Uint8Array([255,0]),
    map:{id:'a',width:4,height:4,resolution_m:.05,origin:[0,0]},view:{x:0,y:0,scale:40},
    edits:[{map_asset_id:'a',kind:'brush_erase',radius_m:.05,points:[{x:.1,y:.1}]}]}),/canvas unavailable/);
  assert.equal(depth,0);
});

test('a narrow diagonal brush updates only crossed tiles and appending a point reuses earlier tiles',async()=>{
  const {createMapEditOutline}=await import(moduleUrl),f=patchDocument(),painter=createMapEditOutline(f.document);
  const map={id:'a',width:4096,height:4096,resolution_m:.05,origin:[0,0]};
  const p=(x,y)=>({x:x*.05,y:(4096-y)*.05});
  const edit={map_asset_id:'a',kind:'brush_erase',radius_m:.4,points:[p(1,1),p(4000,4000)]};
  const context={save(){},restore(){},drawImage(){}};
  const args={context,floorBits:new Uint8Array(4096*4096/8),map,view:{x:0,y:0,scale:1},edits:[edit]};
  painter.paint(args);const first=f.count();
  assert.ok(first<64,`diagonal must not prepare all 256 tiles, got ${first}`);
  painter.paint({...args,edits:[{...edit,points:[...edit.points,p(4010,4010)]}]});
  assert.ok(f.count()-first<=4,`new endpoint must not rebuild ${f.count()-first} earlier tiles`);
});

test('polygon tile inclusion follows Canvas nonzero filling for paths that wind twice',async()=>{
  const {createMapEditOutline}=await import(moduleUrl),f=patchDocument(),painter=createMapEditOutline(f.document);
  const map={id:'a',width:1024,height:1024,resolution_m:.05,origin:[0,0]},p=(x,y)=>({x:x*.05,y:(1024-y)*.05});
  const points=[[10,10],[1010,10],[1010,1010],[10,1010]].map(a=>p(...a));
  painter.paint({context:{save(){},restore(){},drawImage(){}},floorBits:new Uint8Array(1024*1024/8),map,
    view:{x:0,y:0,scale:1},edits:[{map_asset_id:'a',kind:'polygon_erase',points:[...points,...points]}]});
  assert.equal(f.count(),16,'a twice-wound polygon still fills all 16 tiles with nonzero fill');
});

test('black edit pixels remove floor cells and produce a complete styled obstacle outline',async()=>{
  const {buildEditedMapTile}=await import(moduleUrl);
  const map={width:8,height:8,resolution_m:.05},bits=new Uint8Array(8).fill(255),erase=new Uint8ClampedArray(256);
  for(let y=2;y<6;y++)for(let x=2;x<6;x++)erase[(y*8+x)*4+3]=255;
  const tile=buildEditedMapTile({floorBits:bits,map,x:0,y:0,width:8,height:8,erase});
  assert.equal(tile.floor[3*8+3],0);assert.equal(tile.floor[0],1);
  assert.deepEqual([...tile.rgba.slice((3*8+3)*4,(3*8+3)*4+4)],[231,236,242,255]);
  assert.equal(tile.architecture.offsets.length,3,'outer boundary and interior wall hole are both outlined');
});
