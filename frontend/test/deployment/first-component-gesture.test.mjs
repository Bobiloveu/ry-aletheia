import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {COMPONENT_SPECS} from '../../../autodrive_console/web/deployment/component-specs.js';
import {createCanvasDrawScheduler} from '../../../autodrive_console/web/deployment/canvas-scheduler.js';
import {rotationYawFromDrag} from '../../../autodrive_console/web/deployment/canvas-geometry.js';
const source=readFileSync(new URL('../../../autodrive_console/web/deployment.js',import.meta.url),'utf8');
function fn(name){const start=source.indexOf(`function ${name}(`);return source.slice(start,source.indexOf('\n}',start)+2);}
const moves={
 rotate:source.slice(source.indexOf('    if (componentRotate) {',source.indexOf('canvas.addEventListener("pointermove"')),source.indexOf('    if (waypointRotate) {',source.indexOf('canvas.addEventListener("pointermove"'))),
 resize:source.slice(source.indexOf('    if (componentResize) {',source.indexOf('canvas.addEventListener("pointermove"')),source.indexOf('    if (componentRotate) {',source.indexOf('canvas.addEventListener("pointermove"'))),
 drag:source.slice(source.indexOf('    if (componentDrag) {',source.indexOf('canvas.addEventListener("pointermove"')),source.indexOf('    if (componentResize) {',source.indexOf('canvas.addEventListener("pointermove"'))),
};
function editor(kind) {
 // A JSON response contains separate component and project.components objects.
 const body=JSON.parse(JSON.stringify({component:{id:'new',map_asset_id:'a',kind,x:1,y:2,yaw:0,attributes:{width_m:.8,height_m:.8}},project:{components:[{id:'new',map_asset_id:'a',kind,x:1,y:2,yaw:0,attributes:{width_m:.8,height_m:.8}}]}}));
 const state={selectedProject:body.project,selectedComponent:null,selectedVirtualWall:null,componentRotate:null,componentResize:null,componentDrag:null,
  pendingComponentYaw:null,pendingComponentSizeReadout:null,mapView:{scale:10},annotationGesture:null,waypointRotate:null,deploymentProjectGeneration:1,rotationYawFromDrag,
  $:()=>({}),renderComponentAttributes(){},componentCanvasPoint:()=>({x:0,y:0}),worldCanvasPoint:()=>({x:0,y:0}),canvasPointFromEvent:event=>event.point??({x:0,y:-10}),componentLocalPoint:()=>({x:10,y:20}),
  drawMap(){state.painted=structuredClone(state.selectedProject.components[0]);}};
 const frames=[];state.scheduleMapDraw=createCanvasDrawScheduler(()=>state.drawMap(),fn=>{frames.push(fn);return frames.length;});
 runInNewContext([fn('selectComponent'),fn('beginAnnotationGesture'),...Object.entries(moves).map(([name,code])=>`function ${name}(){const x=3,y=4,event={};${code}\n}`)].join('\n'),state);
 state.selectComponent(body.component);
 return {state,body,paint:()=>frames.shift()()};
}
for(const kind of Object.keys(COMPONENT_SPECS))test(`${kind}: first rotation paints while the mouse is still held`,()=>{
 const f=editor(kind);f.state.componentRotate=f.state.selectedComponent;f.state.beginAnnotationGesture(f.state.componentRotate,{pointerId:1,point:{x:10,y:0}});f.state.rotate();f.paint();
 assert.equal(f.state.painted.yaw,Math.PI/2,'canvas must see the yaw before pointerup or save');
 assert.equal(f.body.component.yaw,0,'the detached response object is not the editing target');
});
for(const mode of ['resize','drag'])test(`new component first ${mode} updates the object used by canvas`,()=>{
 const f=editor('narrow_passage');f.state[mode==='resize'?'componentResize':'componentDrag']=f.state.selectedComponent;f.state[mode]();f.paint();
 if(mode==='resize'){assert.equal(f.state.painted.attributes.width_m,2);assert.equal(f.state.painted.attributes.height_m,4);}
 else {assert.equal(f.state.painted.x,3);assert.equal(f.state.painted.y,4);}
});

test('a null component still clears the current selection',()=>{
 const f=editor('narrow_passage');f.state.selectComponent(null);assert.equal(f.state.selectedComponent,null);
});
