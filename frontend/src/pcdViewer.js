import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { createPointMaterial, fitCloudPose } from './pcdPointMaterial.js';
import { createPcdSliceOverlay } from './pcdSliceOverlay.js';
import { clipDisplayBand, decodePointPreview, readViewerLocation, readEmbeddedBand } from './pcdViewerData.js';

const $ = (id) => document.getElementById(id);
const stage = $('cloudStage');
const message = $('cloudMessage');
const abort = new AbortController();
const embedded = document.documentElement.classList.contains('viewer-embedded') && window.parent !== window;
let latestBand = null, updateBand = null;
if (embedded) window.addEventListener('message', (event) => {
  const band = readEmbeddedBand(event, window.location.origin, window.parent);
  if (band) { latestBand = band; updateBand?.(band); }
});
let renderer, controls, observer, scene, camera, cloud, bandOverlay;
let disposed = false;
let span = 1;
let displayBounds = [[-1,1],[-1,1],[-1,1]];
const resources = [];
const render = () => { if (!disposed && renderer && scene && camera) renderer.render(scene, camera); };
function showError(error) {
  if (disposed) return;
  globalThis.RYAletheiaDiagnostics?.failure?.('pcd-viewer.open',error);
  message.hidden = false;
  message.classList.add('is-error');
  message.textContent = error.message || '点云视图无法打开，请返回部署向导后重新打开。';
  $('cloudSummary').textContent = '源点云暂时无法显示';
  $('retryCloud').hidden = false;
}
function fit(top = false) {
  if (!camera || !controls) return;
  const pose = fitCloudPose(displayBounds,camera.aspect,top);
  const distance = pose.distance;
  controls.target.copy(pose.center);
  camera.position.copy(pose.position);
  camera.near = Math.max(span / 10000, 0.00001);
  camera.far = Math.max(distance * 5, span * 50);
  camera.updateProjectionMatrix();
  controls.maxDistance = camera.far / 2;
  controls.minDistance = span / 10000;
  controls.update();
  render();
}
function resize() {
  const width = Math.max(stage.clientWidth,1);
  const height = Math.max(stage.clientHeight,1);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1,2,Math.sqrt(8000000 / (width * height))));
  renderer.setSize(width,height,false);
  if(cloud) cloud.material.uniforms.pixelRatio.value=renderer.getPixelRatio();
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  render();
}
function keyboard(event) {
  if (!controls || !camera) return;
  const direction = camera.position.clone().sub(controls.target);
  const right = new THREE.Vector3().crossVectors(direction,new THREE.Vector3(0,0,1)).normalize();
  const up = new THREE.Vector3().crossVectors(right,direction).normalize();
  const signs = { ArrowLeft:1, ArrowRight:-1, ArrowUp:1, ArrowDown:-1 };
  if (event.key in signs) {
    if (event.shiftKey) {
      const offset = (event.key === 'ArrowLeft' || event.key === 'ArrowRight' ? right : up).multiplyScalar(direction.length() * .04 * signs[event.key]);
      controls.target.add(offset); camera.position.add(offset);
    } else {
      direction.applyAxisAngle(event.key === 'ArrowLeft' || event.key === 'ArrowRight' ? new THREE.Vector3(0,0,1) : right, .06 * signs[event.key]);
      camera.position.copy(controls.target).add(direction);
    }
  } else if (['+','=','-','_'].includes(event.key)) {
    direction.multiplyScalar(event.key === '+' || event.key === '=' ? .85 : 1 / .85);
    camera.position.copy(controls.target).add(direction);
  } else if (event.key.toLowerCase() === 'f') fit();
  else return;
  event.preventDefault(); controls.update(); render();
}
async function openCloud() {
  try {
    const location = readViewerLocation(window.location.search);
    let response;
    for(let attempt=0;attempt<120;attempt+=1) {
      response=await fetch(location.url,{cache:'no-store',signal:abort.signal});
      if(response.status!==202) break;
      message.textContent='正在生成精细点云，首次查看需要稍候…';
      await new Promise((resolve,reject)=>{
        const cancel=()=>{clearTimeout(timer);reject(new DOMException('已取消','AbortError'));};
        const timer=setTimeout(()=>{abort.signal.removeEventListener('abort',cancel);resolve();},1000);
        if(abort.signal.aborted) cancel();
        else abort.signal.addEventListener('abort',cancel,{once:true});
      });
    }
    if(response.status===202) throw new Error('精细点云仍在准备，请稍后点击“重新读取”。');
    if (!response.ok) {
      const failure = await response.json().catch(() => ({}));
      throw new Error(failure.error || '点云读取失败，请返回部署向导重新上传后再试。');
    }
    const length = Number(response.headers.get('Content-Length'));
    if (!Number.isSafeInteger(length) || length < 12 || length > 200000000) throw new Error('点云预览大小无效。');
    const data = decodePointPreview(await response.arrayBuffer(),response.headers);
    if (disposed) return;
    if (latestBand) location.band = latestBand;
    scene = new THREE.Scene();
    scene.background = new THREE.Color('#080b10');
    camera = new THREE.PerspectiveCamera(45,1,.001,10000);
    camera.up.set(0,0,1);
    try { renderer = new THREE.WebGLRenderer({antialias:true}); }
    catch { throw new Error('浏览器暂不支持三维显示，请启用硬件加速后重新打开。'); }
    stage.append(renderer.domElement);
    renderer.domElement.addEventListener('webglcontextlost',(event) => { event.preventDefault(); showError(new Error('三维显示已中断，请点击“重新读取”恢复。')); });
    controls = new OrbitControls(camera,renderer.domElement);
    controls.enableDamping = false;
    controls.addEventListener('change',render);
    controls.addEventListener('start',() => stage.focus({preventScroll:true}));
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position',new THREE.BufferAttribute(data.positions,3));
    geometry.setAttribute('sourceColor',new THREE.BufferAttribute(data.colors,4,true));
    geometry.setAttribute('intensity',new THREE.BufferAttribute(data.intensities,1));
    const material = createPointMaterial(data);
    const setBand = () => {
      const visible = Boolean($('showBand').checked && bandOverlay);
      if (bandOverlay) bandOverlay.object.visible = visible;
      $('sliceLegend').hidden = !visible;
      render();
    };
    cloud = new THREE.Points(geometry,material);
    resources.push(geometry,material);
    scene.add(cloud);
    span = Math.max(.1,...data.displayBounds.map(([low,high]) => high - low));
    displayBounds = data.displayBounds;
    resources.push({dispose:()=>bandOverlay?.dispose()});
    const refreshBand = () => {
      const displayBand = clipDisplayBand(location.band,data.bounds[2]);
      if(bandOverlay) {scene.remove(bandOverlay.object);bandOverlay.dispose();bandOverlay=null;}
      if(displayBand) {
        bandOverlay=createPcdSliceOverlay(data,displayBand);
        scene.add(bandOverlay.object);
        $('sliceLower').textContent=`下限 ${displayBand[0].toFixed(2)} m`;
        $('sliceUpper').textContent=`上限 ${displayBand[1].toFixed(2)} m`;
      }
      $('cloudBand').textContent = displayBand ? `选定高度 ${location.band[0].toFixed(2)} 至 ${location.band[1].toFixed(2)} m` : location.band ? '选定范围内没有点云' : '未选定高度范围';
      $('showBand').disabled = !displayBand;
    };
    refreshBand();
    updateBand = (band) => { location.band = band; refreshBand(); setBand(); };
    setBand();
    $('showBand').addEventListener('change',setBand);
    const colorControl=$('cloudColor');
    colorControl.querySelector('[value="rgb"]').disabled=!data.attributes.rgb;
    colorControl.querySelector('[value="intensity"]').disabled=!data.attributes.intensity;
    colorControl.value=data.defaultColorMode;
    colorControl.addEventListener('change',()=>{
      material.uniforms.colorMode.value={rgb:0,height:1,intensity:2}[colorControl.value];render();
    });
    $('cloudPointSize').value='0.85';
    $('cloudPointSize').addEventListener('input',()=>{material.uniforms.pointSize.value=Number($('cloudPointSize').value);render();});
    for(const id of ['cloudColor','cloudPointSize']) $(id).disabled=false;
    $('cloudInteractionHint').textContent=`${data.sampleCount.toLocaleString('zh-CN')} / ${data.finiteCount.toLocaleString('zh-CN')} 点 · 全部显示`;
    $('fitCloud').addEventListener('click',() => fit());
    $('topCloud').addEventListener('click',() => fit(true));
    $('orbitCloud').addEventListener('click',() => fit());
    for (const id of ['fitCloud','topCloud','orbitCloud']) $(id).disabled = false;
    stage.addEventListener('keydown',keyboard);
    observer = new ResizeObserver(resize);
    observer.observe(stage);
    resize(); fit();
    $('cloudSummary').textContent = `${data.finiteCount.toLocaleString('zh-CN')} 个有效点 · Z ${data.bounds[2][0].toFixed(2)} 至 ${data.bounds[2][1].toFixed(2)} m`;
    $('sampleNote').textContent = '显示全部有效点，不再抽稀。只读查看，不修改导入文件或投影参数。';

    message.hidden = true;
  } catch (error) { if (error.name !== 'AbortError') showError(error); }
}
$('retryCloud').addEventListener('click',() => window.location.reload());
window.addEventListener('pagehide',() => {
  disposed = true; updateBand = null; abort.abort(); observer?.disconnect(); controls?.dispose();
  resources.forEach((resource) => resource.dispose()); renderer?.dispose(); renderer?.forceContextLoss();
},{once:true});
window.addEventListener('pageshow',(event) => { if (event.persisted) window.location.reload(); });
openCloud();
