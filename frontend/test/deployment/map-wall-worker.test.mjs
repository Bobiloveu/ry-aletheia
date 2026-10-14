import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {readEditedMapPixels} from '../../../autodrive_console/web/deployment/erase-preview.js';
const source=readFileSync(new URL('../../../autodrive_console/web/deployment/map-cleanup-worker.js',import.meta.url),'utf8').replace(/^import .*;\n/gm,'');

for(const alpha of [255,102])test(`the beauty worker thresholds the edit layer before classification (coverage ${alpha})`,async()=>{
  let received;const messages=[];
  class Canvas {
    constructor(w,h){this.width=w;this.height=h;this.pixels=new Uint8ClampedArray(w*h*4).fill(255);}
    getContext(){const canvas=this;return {save(){},restore(){},drawImage(){},clearRect(){canvas.pixels.fill(0);canvas.cleared=true;},fillRect(x,y,w,h){
      for(let row=y;row<y+h;row++)for(let col=x;col<x+w;col++)canvas.pixels.set(canvas.cleared?[0,0,0,alpha]:[255-alpha,255-alpha,255-alpha,255],(row*canvas.width+col)*4);
    },getImageData:()=>({data:canvas.pixels.slice()})};}
  }
  const state={self:{postMessage:m=>messages.push(m)},OffscreenCanvas:Canvas,readEditedMapPixels,
    beautifyMap:data=>{received=data.rgba.slice();throw Error('captured classifier input');}};
  runInNewContext(source,state);
  await state.self.onmessage({data:{bitmap:{width:2,height:2,close(){}},width:2,height:2,preview:false,
    rasterMap:{id:'a',width:2,height:2,origin:[0,0],resolution_m:1},
    mapEdits:[{kind:'brush_erase',mode:'wall',shape:'square',radius_m:.5,points:[{x:.5,y:.5}]}]}});
  assert.ok(received);assert.equal(received[8],alpha>=128?0:255,'classifier and edited outline use the same coverage threshold');
  assert.equal(received[0],255,'unpainted cells retain the source data');
});
