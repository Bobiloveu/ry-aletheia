import test from 'node:test';
import assert from 'node:assert/strict';
import {createPointMaterial} from '../src/pcdPointMaterial.js';
test('micro point material retains source colors and depth without transparent accumulation',()=>{
  const material=createPointMaterial({defaultColorMode:'rgb',displayBounds:[[0,1],[0,1],[-2,3]],attributes:{intensity_range:[10,30]}});
  assert.equal(material.uniforms.colorMode.value,0);assert.equal(material.uniforms.pointSize.value,.85);
  assert.equal(material.depthWrite,true);assert.equal(material.transparent,false);
  assert.deepEqual(material.uniforms.heightRange.value.toArray(),[-2,3]);material.dispose();
});

test('camera fits the projected building tightly for wide and narrow windows',async()=>{
  const THREE=await import('three');
  const {fitCloudPose}=await import('../src/pcdPointMaterial.js');
  for(const aspect of [.6,1.5,3]) {
    const bounds=[[-30,30],[-10,10],[-2,12]];
    const pose=fitCloudPose(bounds,aspect);
    const camera=new THREE.PerspectiveCamera(45,aspect,.001,10000);
    camera.up.set(0,0,1);camera.position.copy(pose.position);camera.lookAt(pose.center);camera.updateMatrixWorld();
    let extent=0;
    for(const x of bounds[0])for(const y of bounds[1])for(const z of bounds[2]) {
      const p=new THREE.Vector3(x,y,z).project(camera);extent=Math.max(extent,Math.abs(p.x),Math.abs(p.y));
    }
    assert.ok(extent<=.9 && extent>=.7,`projected extent ${extent}`);
  }
});
