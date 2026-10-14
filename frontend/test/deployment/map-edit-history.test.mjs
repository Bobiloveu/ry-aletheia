import test from 'node:test';
import assert from 'node:assert/strict';

test('undo history follows saved operation order separately for each project and map',async()=>{
  const {createMapEditHistory}=await import('../../../autodrive_console/web/deployment/map-edit-history.js');
  const h=createMapEditHistory();
  h.push('p','a',{kind:'wall-create',wallId:'one'});
  h.push('p','b',{kind:'wall-create',wallId:'other'});
  h.push('p','a',{kind:'erase-add',editId:'erase'});
  h.push('q','a',{kind:'wall-create',wallId:'foreign'});
  const latest=h.peek('p','a');assert.equal(latest.editId,'erase');
  h.remove(latest);assert.equal(h.peek('p','a').wallId,'one');
  h.clear('p','a');assert.equal(h.peek('p','a'),null);
  assert.equal(h.peek('p','b').wallId,'other');assert.equal(h.peek('q','a').wallId,'foreign');
});

test('history bounds memory, snapshots old geometry and remaps recreated wall IDs',async()=>{
  const {createMapEditHistory}=await import('../../../autodrive_console/web/deployment/map-edit-history.js');
  const h=createMapEditHistory({limit:2}),entry={kind:'wall-update',wallId:'old',before:{points:[{x:1,y:2},{x:3,y:4}]}};
  h.push('p','a',{kind:'wall-create',wallId:'discarded'});h.push('p','a',entry);
  entry.before.points[0].x=99;h.push('q','b',{kind:'erase-add'});
  h.remapWall('p','a','old','new');assert.equal(h.peek('p','a').wallId,'new');
  assert.equal(h.peek('p','a').before.points[0].x,1);
  h.remove(h.peek('p','a'));assert.equal(h.peek('p','a'),null);
});

test('pending operations lock only their own map until every save has finished',async()=>{
  const {createMapEditHistory}=await import('../../../autodrive_console/web/deployment/map-edit-history.js');
  const h=createMapEditHistory(),finishA=h.begin('p','a'),finishB=h.begin('p','a');
  assert.equal(h.busy('p','a'),true);assert.equal(h.busy('p','b'),false);
  finishA();finishA();assert.equal(h.busy('p','a'),true);
  finishB();assert.equal(h.busy('p','a'),false);
});
