import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const source=readFileSync(new URL('../../../autodrive_console/web/deployment.js',import.meta.url),'utf8');

test('polygon submission freezes wall mode for its visible pending preview and saved edit',async()=>{
  const body=source.match(/\$\("completeErasePolygon"\)\.addEventListener\("click", async \(\) => \{([\s\S]*?)\n\}\);/)[1];
  let payload,pendingMode;
  const state={eraserMode:'wall',pendingPolygonErase:null,polygonEraseDraft:[{x:1,y:1},{x:3,y:1},{x:3,y:3}],polygonVertexHover:-1,
    selectedProject:{id:'p'},activeMap:{id:'a'},finishPolygonVertexDrag(){},$:()=>({}),drawMap(){},note(){},
    commitMapEdit:async p=>{payload=p;pendingMode=state.pendingPolygonErase.mode;return true;}};
  runInNewContext(`async function submit(){${body}\n}`,state);await state.submit();
  assert.equal(pendingMode,'wall');assert.equal(payload.mode,'wall');assert.equal(state.pendingPolygonErase,null);
});

test('a released brush preserves its captured mode even if the current toolbar mode changes',async()=>{
  const start=source.indexOf('  if (eraserStroke) {',source.indexOf('canvas.addEventListener("pointerup"'));
  const end=source.indexOf('  if (virtualWallDrag && selectedProject)',start);
  let payload;
  const state={eraserMode:'erase',eraserStroke:{mode:'wall',shape:'square',radius_m:.5,points:[{x:1,y:1}]},eraserHoverPoint:null,pendingEraserStroke:null,eraserCommitPending:false,
    trackEraserStroke(){},drawMap(){},scheduleMapDraw(){},eraseFrameMask:{cover(){},revealAfterPaint(){}},commitMapEdit:async p=>{payload=p;}};
  runInNewContext(`async function submit(event){${source.slice(start,end)}\n}`,state);await state.submit({});
  assert.equal(payload.mode,'wall');assert.equal(state.eraserCommitPending,false);
});
