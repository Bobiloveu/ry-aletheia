import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../src/liveObservation.js", import.meta.url), "utf8");
const MAP_A = "aaaaaaaaaaaaaaaa", MAP_B = "bbbbbbbbbbbbbbbb";
const route = (map_id = MAP_A) => ({ map_id, frame_id: "map", points: [{x: 0, y: 1}, {x: 2, y: 3}] });
function harness() {
  const context = vm.createContext({
    loadedMapId: MAP_A, observedNavigationRoute: undefined,
    relocalizationMapUnconfirmed: false, mapMarkerNavigationStatus: {phase: "idle"},
    navigationRouteVisible: true, mobileConsoleEnabled: () => false,
    renders: 0, draws: 0, pixiApp: { render() {} },
  });
  const start = source.indexOf("function applyObservedNavigationRoute(");
  assert.ok(start >= 0, "generic observation route handler is required");
  vm.runInContext(source.slice(start, source.indexOf("function renderNavigationRoute()", start)), context);
  context.renderNavigationRoute = () => context.renders++;
  context.scheduleMapDraw = () => context.draws++;
  return context;
}

test("delivery and tests display plans even when marker navigation is idle or absent", () => {
  const c = harness();
  for (const status of [undefined, {phase: "idle"}, {phase: "succeeded"}]) {
    c.mapMarkerNavigationStatus = status;
    c.applyObservedNavigationRoute({active_map_id: MAP_A, navigation_route: route()});
    assert.equal(c.navigationRoutePoints().length, 2);
  }
});

test("terminal, empty and failed observations clear the previous line", () => {
  const c = harness();
  c.applyObservedNavigationRoute({active_map_id: MAP_A, navigation_route: route()});
  assert.equal(c.navigationRoutePoints().length, 2);
  c.applyObservedNavigationRoute({active_map_id: MAP_A, navigation_route: null});
  assert.equal(c.navigationRoutePoints().length, 0);
  c.applyObservedNavigationRoute(undefined);
  assert.equal(c.navigationRoutePoints().length, 0);
  assert.equal(c.renders, 3);
});

test("routes cannot cross displayed map identity or an unconfirmed relocalization map", () => {
  const c = harness();
  c.applyObservedNavigationRoute({active_map_id: MAP_B, navigation_route: route(MAP_B)});
  assert.equal(c.navigationRoutePoints().length, 0);
  c.applyObservedNavigationRoute({active_map_id: MAP_A, navigation_route: route(MAP_B)});
  assert.equal(c.navigationRoutePoints().length, 0);
  c.relocalizationMapUnconfirmed = true;
  c.applyObservedNavigationRoute({active_map_id: MAP_A, navigation_route: route()});
  assert.equal(c.navigationRoutePoints().length, 0);
});

test("malformed or unbounded route payloads never draw", () => {
  const c = harness();
  for (const bad of [{...route(), frame_id: "odom"}, {...route(), points: [{x: NaN,y:1},{x:0,y:2}]},
    {...route(), points: Array(513).fill({x:1,y:2})}, {...route(), points:[{x:0,y:0},{x:100001,y:2}]}]) {
    c.applyObservedNavigationRoute({active_map_id: MAP_A, navigation_route: bad});
    assert.equal(c.navigationRoutePoints().length, 0);
  }
});

test("a stale asynchronous poll cannot restore a line after a map or manual action change", async () => {
  const c = harness();
  let resolve;
  const pending = new Promise(r => resolve = r);
  Object.assign(c, {
    activeMapPollPending: false, relocalizationActionEpoch: 0, mapGeneration: 1,
    AbortController, window: {setTimeout: () => 1, clearTimeout() {}},
    request: () => pending, refreshActiveMap: async () => {},
  });
  const start = source.indexOf("async function refreshActiveMapFromServer()");
  vm.runInContext(source.slice(start, source.indexOf("async function refreshActiveMap(", start)), c);
  const polling = c.refreshActiveMapFromServer();
  c.mapGeneration++;
  resolve({active_map_id: MAP_A, navigation_route: route()});
  await polling;
  assert.equal(c.navigationRoutePoints().length, 0);
  c.request = async () => {throw new Error("offline");};
  c.applyObservedNavigationRoute({active_map_id: MAP_A, navigation_route: route()});
  await c.refreshActiveMapFromServer();
  assert.equal(c.navigationRoutePoints().length, 0);
  assert.equal(c.activeMapPollPending, false);
});

test("stalled map layers never hold the route polling gate", async () => {
  const c = harness();
  Object.assign(c, {
    activeMapPollPending: false, relocalizationActionEpoch: 0, mapGeneration: 1,
    AbortController, window: {setTimeout: () => 1, clearTimeout() {}},
    request: async () => ({active_map_id: MAP_B, navigation_route: route(MAP_B)}),
    refreshActiveMap: () => new Promise(() => {}),
  });
  const start = source.indexOf("async function refreshActiveMapFromServer()");
  vm.runInContext(source.slice(start, source.indexOf("async function refreshActiveMap(", start)), c);
  await c.refreshActiveMapFromServer();
  assert.equal(c.activeMapPollPending, false);
  c.request = async () => ({active_map_id: MAP_A, navigation_route: null});
  await c.refreshActiveMapFromServer();
  assert.equal(c.navigationRoutePoints().length, 0);
});
