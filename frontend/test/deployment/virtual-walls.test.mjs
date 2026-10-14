import assert from "node:assert/strict";
import test from "node:test";

import {
  moveWallEndpoint,
  moveWallVertex,
  polylineSegments,
  wallsForDisplay,
  translateWall,
  wallHitTest,
} from "../../../autodrive_console/web/deployment/virtual-walls.js";

const map = { origin: [0, 0, 0], height: 10, resolution_m: 1 };
const view = { x: 0, y: 0, scale: 10 };
const wall = {
  id: "virtual-wall-a",
  start: { x: 0, y: 0 },
  end: { x: 2, y: 0 },
};

test("wall hit testing distinguishes endpoints from the segment", () => {
  assert.equal(wallHitTest(wall, map, view, { x: 0, y: 100 }, 8), "start");
  assert.equal(wallHitTest(wall, map, view, { x: 20, y: 100 }, 8), "end");
  assert.equal(wallHitTest(wall, map, view, { x: 10, y: 100 }, 8), "segment");
  assert.equal(wallHitTest(wall, map, view, { x: 10, y: 70 }, 8), null);
});

test("endpoint and segment movement preserve the other endpoint", () => {
  assert.deepEqual(moveWallEndpoint(wall, "start", { x: 1, y: 3 }), {
    ...wall,
    start: { x: 1, y: 3 },
  });
  assert.deepEqual(translateWall(wall, { x: -0.5, y: 1 }), {
    ...wall,
    start: { x: -0.5, y: 1 },
    end: { x: 1.5, y: 1 },
  });
});

test("polyline walls hit their internal vertex and split into runtime segments", () => {
  const polyline = {
    id: "virtual-wall-polyline",
    points: [{ x: 0, y: 0 }, { x: 2, y: 0 }, { x: 2, y: 2 }],
  };

  assert.equal(wallHitTest(polyline, map, view, { x: 20, y: 100 }, 8), "vertex:1");
  assert.deepEqual(polylineSegments(polyline), [
    { start: { x: 0, y: 0 }, end: { x: 2, y: 0 } },
    { start: { x: 2, y: 0 }, end: { x: 2, y: 2 } },
  ]);
  assert.deepEqual(moveWallVertex(polyline, 1, { x: 1, y: 1 }).points[1], { x: 1, y: 1 });
});

test("a dragged wall replaces its saved geometry in the current render frame", () => {
  const otherWall = {
    id: "virtual-wall-b",
    start: { x: 5, y: 0 },
    end: { x: 7, y: 0 },
  };
  const draggedWall = {
    ...wall,
    start: { x: 3, y: 1 },
    end: { x: 5, y: 1 },
  };

  assert.deepEqual(wallsForDisplay([wall, otherWall], draggedWall), [
    draggedWall,
    otherWall,
  ]);
});

test('wall drawing snaps to the nearest vertex in screen pixels without changing saved geometry',async()=>{
  const {snapWallPoint}=await import('../../../autodrive_console/web/deployment/virtual-walls.js');
  assert.equal(typeof snapWallPoint,'function');
  const m={id:'m',origin:[0,0],height:10,resolution_m:1},v={x:30,y:20,scale:10};
  const walls=[{map_asset_id:'m',points:[{x:1,y:2},{x:4,y:2},{x:4,y:5}]},
    {map_asset_id:'m',start:{x:7,y:2},end:{x:9,y:2}},
    {map_asset_id:'other',points:[{x:1.2,y:2.1},{x:2,y:2}]}];
  const p={x:1.2,y:2.1},result=snapWallPoint(walls,m,v,p);
  assert.deepEqual(result,{x:1,y:2});assert.notEqual(result,walls[0].points[0]);
  assert.deepEqual(snapWallPoint(walls,m,v,{x:4.1,y:2.2}),{x:4,y:2});
  assert.deepEqual(snapWallPoint(walls,m,v,{x:8.8,y:2.2}),{x:9,y:2});
  assert.deepEqual(snapWallPoint(walls,m,{...v,scale:100},p),p,'zoom must not increase world-space snap distance');
  assert.deepEqual(snapWallPoint(walls,m,v,{x:2.5,y:2}),{x:2.5,y:2},'segments are not endpoint snap targets');
});
