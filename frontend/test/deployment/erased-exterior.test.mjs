import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {eraseEditsForRender} from '../../../autodrive_console/web/deployment/erase-preview.js';
import {beautifyMap} from '../../../autodrive_console/web/deployment/map-cleanup.js';
import {createMapImageCanvas} from '../../../autodrive_console/web/deployment/map-image-export.js';

const source=readFileSync(new URL('../../../autodrive_console/web/deployment.js',import.meta.url),'utf8');
const draw=source.slice(source.indexOf('function drawMapEdits()'),source.indexOf('\nfunction drawMapRoutes()'));
const map={id:'a',width:64,height:64,resolution_m:.05,origin:[0,0]};
const edits=[{map_asset_id:'a',kind:'brush_erase',radius_m:.3,points:[{x:2.45,y:1.6}]}];

test('styled viewing never replays saved white erases or black wall edits over the final floor decision',()=>{
  for(const mode of ['free','wall'])for(const appearance of ['raw','styled'])for(const ready of [false,true]) {
    const saved={...edits[0],mode},replayed=[];
    const state={selectedProject:{map_edits:[saved]},mapAppearance:appearance,activeMap:map,mapView:{},
      mapDisplay:{getExportSurface:()=>ready?({width:64,height:64}):null,paintEdits(){replayed.push('outline');return true;}},
      context:{},canvas:{getBoundingClientRect:()=>({})},eraseEditsForRender,drawEraseOperation:edit=>replayed.push(edit),
      eraserStroke:null,pendingEraserStroke:null,pendingPolygonErase:null,polygonEraseDraft:[],activeTool:'pan'};
    runInNewContext(`${draw}\ndrawMapEdits()`,state);
    assert.deepEqual(replayed,appearance==='styled'&&ready?[]:[saved]);
  }
});

test('an erased circle across a virtual wall stays grey outside in both prepared and exported pixels',()=>{
  const width=64,height=64,rgba=new Uint8ClampedArray(width*height*4).fill(255);
  const result=beautifyMap({rgba,width,height,resolution:.05,
    virtualWalls:[{points:[{x:16,y:16},{x:48,y:16},{x:48,y:48},{x:16,y:48},{x:16,y:16}]}],passagePoints:[{x:32,y:32}]});
  const outside=(32*width+52)*4,inside=(32*width+40)*4;
  assert.deepEqual([...result.rgba.slice(outside,outside+3)],[231,236,242]);
  assert.deepEqual([...result.rgba.slice(inside,inside+3)],[255,255,255]);
  // Minimal raster context: real erase rendering writes the circle if export
  // wrongly replays its history, exactly as a native canvas would.
  let output,circle;
  const context={fillRect(){},drawImage(surface){output=surface.rgba.slice();},save(){},restore(){},beginPath(){},moveTo(){},stroke(){},
    arc(x,y,r){circle={x,y,r};},fill(){for(let y=0;y<height;y++)for(let x=0;x<width;x++)if((x+.5-circle.x)**2+(y+.5-circle.y)**2<circle.r**2)output.fill(255,(y*width+x)*4,(y*width+x)*4+4);}};
  createMapImageCanvas({document:{createElement:()=>({getContext:()=>context})},surface:{width,height,rgba:result.rgba},map,edits});
  assert.deepEqual([...output.slice(outside,outside+3)],[231,236,242]);
  assert.deepEqual([...output.slice(inside,inside+3)],[255,255,255]);
});
