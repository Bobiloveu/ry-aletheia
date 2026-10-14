import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const source=readFileSync(new URL('../../../autodrive_console/web/deployment.js',import.meta.url),'utf8');
const draw=source.slice(source.indexOf('function drawMapEdits()'),source.indexOf('\nfunction drawMapRoutes()'));
function cursor(diameter,scale,shape) {
  const outlines=[],labels=[];let path;
  const context={save(){},restore(){},beginPath(){},setLineDash(){},fill(){},
    arc(x,y,radius){path={shape:'circle',x,y,radius};},
    rect(x,y,width,height){path={shape:'square',x,y,width,height};},
    stroke(){outlines.push({...path});},
    fillText(text,x,y){labels.push({text,x,y,align:this.textAlign});}};
  runInNewContext(`${draw}\ndrawMapEdits()`,{context,selectedProject:{map_edits:[]},mapAppearance:'raw',activeMap:{id:'a'},
    eraseEditsForRender:()=>[],eraserStroke:null,pendingEraserStroke:null,pendingPolygonErase:null,polygonEraseDraft:[],
    activeTool:'erase_brush',eraserHoverPoint:{x:0,y:0},eraserDiameterM:diameter,eraserShape:shape,
    mapView:{scale},worldCanvasPoint:()=>({x:100,y:100})});
  return {outlines,labels};
}
for(const shape of ['circle','square'])for(const scale of [25,100])test(`${shape} cursor shrinks to the real 0.1m footprint at scale ${scale}`,()=>{
  const radii=[];
  for(const diameter of [.3,.2,.1]) {
    const {outlines,labels}=cursor(diameter,scale,shape),radius=diameter*scale/2;
    assert.equal(outlines.length,1,'one outline must show the actual affected area');
    const outline=outlines[0];assert.equal(outline.shape,shape);
    if(shape==='circle')assert.equal(outline.radius,radius);
    else {assert.equal(outline.width,radius*2);assert.equal(outline.height,radius*2);assert.equal(outline.x,100-radius);}
    radii.push(shape==='circle'?outline.radius:outline.width/2);
    assert.equal(labels[0].text,`${diameter.toFixed(1)} m`);
    assert.equal(labels[0].align,'left');
    assert.ok(labels[0].x>=100+radius+6,'size label stays outside the brush');
  }
  assert.ok(radii[0]>radii[1]&&radii[1]>radii[2]);
});
