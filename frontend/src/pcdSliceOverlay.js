import * as THREE from 'three';
import {LineSegments2} from 'three/addons/lines/LineSegments2.js';
import {LineSegmentsGeometry} from 'three/addons/lines/LineSegmentsGeometry.js';
import {LineMaterial} from 'three/addons/lines/LineMaterial.js';

/** Display-only selection volume: far translucent faces preserve foreground source colors. */
export function createPcdSliceOverlay(data, band) {
  const object = new THREE.Group();
  const [x,y] = data.displayBounds;
  const width = x[1]-x[0], height = y[1]-y[0];
  const [low, high] = band.map(z => z-data.origin[2]);
  const volume = new THREE.Mesh(new THREE.BoxGeometry(width,height,high-low),new THREE.MeshBasicMaterial({
    color:'#c0a6ff',transparent:true,opacity:.28,side:THREE.BackSide,depthTest:true,depthWrite:false,
  }));
  volume.name='selection-volume';
  volume.position.set((x[0]+x[1])/2,(y[0]+y[1])/2,(low+high)/2);
  volume.renderOrder=10;
  object.add(volume);
  const connectorPositions=[];
  for(const px of x) for(const py of y) connectorPositions.push(px,py,low,px,py,high);
  const connectors=new LineSegments2(new LineSegmentsGeometry().setPositions(connectorPositions),new LineMaterial({
    color:'#c0a6ff',linewidth:2.5,worldUnits:false,transparent:true,opacity:1,depthTest:false,depthWrite:false,
  }));
  connectors.name='selection-connectors';
  connectors.renderOrder=19;
  object.add(connectors);
  const dash = Math.max(width,height,.1)/80;
  for (let index=0;index<2;index+=1) {
    const name = index ? 'upper' : 'lower';
    const color = index ? '#ffd166' : '#61e1ff';
    const z = band[index]-data.origin[2];
    const geometry = new LineSegmentsGeometry().setPositions([
      x[0],y[0],z, x[1],y[0],z,
      x[1],y[0],z, x[1],y[1],z,
      x[1],y[1],z, x[0],y[1],z,
      x[0],y[1],z, x[0],y[0],z,
    ]);
    for (const halo of [true,false]) {
      const material = new LineMaterial({
        color:halo?'#080b10':color, linewidth:halo?6:2.5, worldUnits:false,
        transparent:true,opacity:halo?.9:1,depthTest:false,depthWrite:false,
        dashed:Boolean(index),dashSize:dash,gapSize:dash*.65,
      });
      const line = new LineSegments2(geometry,material);
      line.name=`${name}-${halo?'halo':'boundary'}`;
      line.renderOrder=20+index*2+(halo?0:1);
      line.computeLineDistances();
      object.add(line);
    }
  }
  return {object,dispose() {
    const resources = new Set();
    object.traverse(node => {
      if(node.geometry) resources.add(node.geometry);
      if(node.material) resources.add(node.material);
    });
    resources.forEach(resource => resource.dispose());
  }};
}
