import * as THREE from 'three';

/** Opaque, depth-tested micro points. Coloring stays on the GPU during slice edits. */
export function createPointMaterial(data) {
  const height = data.displayBounds[2];
  const intensity = data.attributes.intensity_range || [0,1];
  return new THREE.ShaderMaterial({
    uniforms: {
      pointSize: {value: 0.85}, pixelRatio: {value: 1}, colorMode: {value:data.defaultColorMode==='rgb'?0:1},
      heightRange: {value:new THREE.Vector2(...height)}, intensityRange: {value:new THREE.Vector2(...intensity)},
    },
    vertexShader: `
      attribute vec4 sourceColor;
      attribute float intensity;
      uniform float pointSize;
      uniform float pixelRatio;
      uniform float colorMode;
      uniform vec2 heightRange;
      uniform vec2 intensityRange;
      varying vec3 pointColor;
      vec3 ramp(float t) {
        vec3 a=vec3(0.18,0.42,0.92), b=vec3(0.20,0.82,0.84), c=vec3(0.98,0.79,0.38), d=vec3(0.91,0.32,0.24);
        t=clamp(t,0.0,1.0)*3.0;
        return t<1.0?mix(a,b,t):t<2.0?mix(b,c,t-1.0):mix(c,d,t-2.0);
      }
      void main() {
        float h=clamp((position.z-heightRange.x)/max(heightRange.y-heightRange.x,0.00001),0.0,1.0);
        pointColor=ramp(h);
        if(colorMode<0.5 && sourceColor.a>0.5) pointColor=sourceColor.rgb;
        if(colorMode>1.5 && intensity==intensity) {
          float t=clamp((intensity-intensityRange.x)/max(intensityRange.y-intensityRange.x,0.00001),0.0,1.0);
          pointColor=mix(vec3(0.12,0.22,0.34),vec3(0.96,0.94,0.84),t);
        }
        gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);
        gl_PointSize=max(1.0,pointSize*pixelRatio);
      }`,
    fragmentShader: `
      varying vec3 pointColor;
      void main() {
        vec2 p=gl_PointCoord-vec2(0.5);
        if(dot(p,p)>0.25) discard;
        gl_FragColor=vec4(pointColor,1.0);
      }`,
    depthTest:true, depthWrite:true, transparent:false, toneMapped:false,
  });
}

/** Fit all robust-bound corners in projection, instead of wasting space on a sphere. */
export function fitCloudPose(bounds,aspect,top=false) {
  const center=new THREE.Vector3(...bounds.map(([low,high])=>(low+high)/2));
  const direction=(top?new THREE.Vector3(0,-.0001,1):new THREE.Vector3(1,-1,.65)).normalize();
  const right=new THREE.Vector3().crossVectors(new THREE.Vector3(0,0,1),direction).normalize();
  const up=new THREE.Vector3().crossVectors(direction,right).normalize();
  const tangent=Math.tan(THREE.MathUtils.degToRad(45)/2);
  let distance=.1;
  for(const x of bounds[0])for(const y of bounds[1])for(const z of bounds[2]) {
    const offset=new THREE.Vector3(x,y,z).sub(center), depth=offset.dot(direction);
    distance=Math.max(distance,Math.abs(offset.dot(right))/(tangent*aspect*.88)+depth,Math.abs(offset.dot(up))/(tangent*.88)+depth);
  }
  return {center,position:center.clone().addScaledVector(direction,distance),distance};
}
