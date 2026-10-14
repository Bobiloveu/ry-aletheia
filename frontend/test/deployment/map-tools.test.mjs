import test from 'node:test';
import assert from 'node:assert/strict';
const moduleUrl='../../../autodrive_console/web/deployment/map-tools.js';

test('placement previews use map coordinates and only represent supported annotation tools',async()=>{
  const {placementPreview}=await import(moduleUrl);
  const map={id:'a',origin:[-5,-3],width:100,height:80,resolution_m:.05};
  const point={x:-3,y:-1};
  for(const kind of ['start','target','building_entrance','transition','elevator','gate','auto_door','narrow_passage','ramp','slow_zone']) {
    const item=placementPreview(kind,point,map);
    assert.equal(item.kind,kind);assert.equal(item.map_asset_id,'a');
    assert.equal(item.x,-3);assert.equal(item.y,-1);assert.equal(item.yaw,0);
  }
  for(const kind of ['pan','virtual_wall','erase_brush','erase_polygon','route_link','other']) assert.equal(placementPreview(kind,point,map),null);
});

test('placement previews reject absent maps, absent pointers, nonfinite and out of map positions',async()=>{
  const {placementPreview}=await import(moduleUrl);
  const map={id:'a',origin:[-5,-3],width:100,height:80,resolution_m:.05};
  for(const point of [null,{x:NaN,y:0},{x:-3,y:Infinity},{x:.01,y:0},{x:-5.01,y:0},{x:-3,y:1.01}]) assert.equal(placementPreview('elevator',point,map),null);
  assert.equal(placementPreview('start',{x:0,y:0},null),null);
  assert.ok(placementPreview('target',{x:0,y:1},map));
});

test('edit shortcuts belong to the map and cannot save from palette buttons or read-only preview',async()=>{
  const {canUseMapEditShortcut}=await import(moduleUrl);
  const canvas={closest:()=>null},button={closest:()=>({})},outside={closest:()=>null};
  const workspace={contains:target=>[canvas,button].includes(target)};
  assert.equal(canUseMapEditShortcut({target:canvas},workspace),true);
  for(const event of [{target:button},{target:outside},{target:canvas,defaultPrevented:true}])assert.equal(canUseMapEditShortcut(event,workspace),false);
  assert.equal(canUseMapEditShortcut({target:canvas},workspace,{previewOpen:true}),false);
});
