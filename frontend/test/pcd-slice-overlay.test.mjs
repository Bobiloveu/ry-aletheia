import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';

test('slice boundaries stay readable through dense points and keep absolute height alignment', async () => {
  const {createPcdSliceOverlay} = await import('../src/pcdSliceOverlay.js');
  const overlay = createPcdSliceOverlay({displayBounds:[[-10,20],[-5,8],[-2,10]],origin:[100,200,30]}, [31,34]);
  const lower = overlay.object.getObjectByName('lower-boundary');
  const upper = overlay.object.getObjectByName('upper-boundary');
  assert.equal(lower.geometry.attributes.instanceStart.getZ(0), 1);
  assert.equal(upper.geometry.attributes.instanceStart.getZ(0), 4);
  for (const edge of [lower,upper]) {
    assert.ok(edge.material.linewidth >= 2, 'boundary remains visible at ordinary window size');
    assert.equal(edge.material.worldUnits, false, 'zooming does not shrink boundary pixel width');
    assert.equal(edge.material.depthTest, false, 'dense foreground cannot erase the reference');
    assert.equal(edge.material.depthWrite, false);
  }
  assert.notEqual(lower.material.color.getHex(), upper.material.color.getHex());
  assert.equal(lower.material.dashed, false);
  assert.equal(upper.material.dashed, true, 'line pattern distinguishes bounds beyond color');
  assert.ok(overlay.object.getObjectByName('lower-halo').material.linewidth > lower.material.linewidth);

  overlay.dispose();
});

test('replacing a slice releases each GPU resource once, including shared boundary geometry', async () => {
  const {createPcdSliceOverlay} = await import('../src/pcdSliceOverlay.js');
  const overlay = createPcdSliceOverlay({displayBounds:[[0,5],[0,8],[0,3]],origin:[0,0,0]}, [.2,1.8]);
  const resources = new Set();
  overlay.object.traverse(node => {if(node.geometry) resources.add(node.geometry);if(node.material) resources.add(node.material);});
  const disposed = new Map();
  for(const resource of resources) resource.addEventListener('dispose',() => disposed.set(resource,(disposed.get(resource)||0)+1));
  overlay.dispose();
  assert.equal(disposed.size, resources.size);
  assert.ok([...disposed.values()].every(count => count===1));
});


test('selection volume spans both heights with far translucent faces that preserve foreground points', async () => {
  const {createPcdSliceOverlay} = await import('../src/pcdSliceOverlay.js');
  const overlay = createPcdSliceOverlay({displayBounds:[[-10,20],[-5,8],[-2,10]],origin:[100,200,30]}, [31,34]);
  const volume = overlay.object.getObjectByName('selection-volume');
  assert.ok(volume, 'both height limits enclose a visible 3D region');
  const bounds = new THREE.Box3().setFromObject(volume);
  assert.deepEqual(bounds.min.toArray(), [-10,-5,1]);
  assert.deepEqual(bounds.max.toArray(), [20,8,4]);
  assert.ok(volume.material.opacity > 0 && volume.material.opacity < .5);
  assert.equal(volume.material.transparent, true);
  assert.equal(volume.material.depthWrite, false, 'selection never occludes source points');
  assert.equal(volume.material.depthTest, true, 'points in front retain their original color');
  assert.equal(volume.material.side, THREE.BackSide);
  const connectors = overlay.object.getObjectByName('selection-connectors');
  assert.equal(connectors.geometry.attributes.instanceStart.count, 4);
  for(let i=0;i<4;i+=1) {
    assert.equal(connectors.geometry.attributes.instanceStart.getZ(i),1);
    assert.equal(connectors.geometry.attributes.instanceEnd.getZ(i),4);
  }
  overlay.dispose();
});
