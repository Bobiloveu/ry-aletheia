import test from 'node:test';
import assert from 'node:assert/strict';
import { relocalizationProgressState } from '../src/relocalizationProgress.js';

test('idle and ordinary alignment have no progress popup',()=>{
  assert.equal(relocalizationProgressState({phase:'idle'}),null);
  assert.equal(relocalizationProgressState({phase:'calibrating'}),null);
});
test('parallel request names both operations without inventing a completion percentage',()=>{
  const s=relocalizationProgressState({phase:'calibrating',pending:true,switchingMap:true,waitingMap:true});
  assert.equal(s.state,'busy');assert.match(s.title,/地图.*重定位/);
  assert.doesNotMatch(s.detail,/%|已完成|已确认/);
});
test('accepted operation distinguishes waiting for bitmap from waiting for real pose',()=>{
  const map=relocalizationProgressState({phase:'switching_to_navigation',waitingMap:true});
  const pose=relocalizationProgressState({phase:'idle',awaitingPose:true});
  assert.match(map.title,/目标地图/);assert.match(pose.title,/实时位姿/);
  assert.equal(relocalizationProgressState({phase:'idle',waitingMap:false,awaitingPose:false}),null);
});
test('failure and transport uncertainty replace the spinner with actionable status',()=>{
  const failure=relocalizationProgressState({phase:'failed',waitingMap:true});
  assert.equal(failure.state,'failed');assert.match(failure.detail,/停车/);
  const unknown=relocalizationProgressState({phase:'unavailable',waitingMap:true});
  assert.equal(unknown.state,'unknown');assert.doesNotMatch(unknown.detail,/定位已确认/);
});
