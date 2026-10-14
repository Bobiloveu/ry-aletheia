import { strict as assert } from "node:assert";
import test from "node:test";

import { eraseEditsForRender, paintEraseOperation } from "../../../autodrive_console/web/deployment/erase-preview.js";

test("releasing a brush stroke keeps its local erase preview visible until the saved map edit arrives", () => {
  const savedEdit = { id: "saved-1", map_asset_id: "map-a", kind: "brush_erase", points: [{ x: 1, y: 1 }] };
  const releasedStroke = { kind: "brush_erase", radius_m: 0.4, points: [{ x: 2, y: 2 }] };

  assert.deepEqual(
    eraseEditsForRender({
      savedEdits: [savedEdit],
      activeMapId: "map-a",
      activeStroke: null,
      pendingStroke: releasedStroke,
    }),
    [savedEdit, releasedStroke],
  );
});

test("a submitted polygon stays white while saving, only on its own map", () => {
  const polygon = { map_asset_id: "map-a", kind: "polygon_erase", points: [{ x: 1, y: 1 }, { x: 3, y: 1 }, { x: 2, y: 3 }] };
  assert.deepEqual(eraseEditsForRender({activeMapId: "map-a", pendingPolygon: polygon}), [polygon]);
  assert.deepEqual(eraseEditsForRender({activeMapId: "map-b", pendingPolygon: polygon}), []);
});

for(const kind of ['brush_erase','polygon_erase']) {
  test(`${kind} paints black for wall mode and keeps historical erasures white`,()=>{
    const paints=[];
    const context={save(){},restore(){},beginPath(){},closePath(){},moveTo(){},lineTo(){},arc(){},stroke(){paints.push(this.strokeStyle);},fill(){paints.push(this.fillStyle);}};
    const points=[{x:1,y:1},{x:3,y:1},{x:3,y:3}];
    const options={map:{width:8,height:8,resolution_m:1,origin:[0,0]},view:{x:0,y:0,scale:1}};
    paintEraseOperation(context,{kind,mode:'wall',points,radius_m:1},options);
    assert.ok(paints.length);assert.ok(paints.every(color=>color==='#000'));
    paints.length=0;paintEraseOperation(context,{kind,points,radius_m:1},options);
    assert.ok(paints.every(color=>color==='#fff'));
  });
}
