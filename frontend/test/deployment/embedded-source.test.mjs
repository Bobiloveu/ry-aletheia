import assert from 'node:assert/strict';
import test from 'node:test';
import { bindEmbeddedSource } from '../../../autodrive_console/web/deployment/embedded-source.js';
function element() { return {hidden:false,disabled:false,attrs:{},handlers:{},setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];},addEventListener(k,fn){this.handlers[k]=fn;},classList:{toggle(){}},textContent:''}; }
function setup(){
  const container=element(),viewport=element(),zoom=element(),button=element(),frame=element(),help=element(),fullscreen=element();
  const document={handlers:{},fullscreenElement:null,addEventListener(k,fn){this.handlers[k]=fn;}};
  container.ownerDocument=document;
  frame.contentDocument={handlers:{},addEventListener(k,fn){this.handlers[k]=fn;}};
  const messages=[]; frame.contentWindow={postMessage:(...args)=>messages.push(args)};
  const ui=bindEmbeddedSource({container,viewport,zoom,button,frame,help,fullscreen,origin:'http://localhost'});
  return {ui,container,viewport,zoom,button,frame,help,fullscreen,document,messages};
}
const url='/vue/pcd-viewer.html?project=site&projection=projection-a&z_min=0&z_max=1';
test('source toggle embeds PCD in the current preview and restores 2D without navigating',()=>{
  const x=setup();x.ui.render(url);x.button.handlers.click();
  assert.equal(x.viewport.hidden,true); assert.equal(x.frame.hidden,false); assert.equal(x.zoom.hidden,true);
  assert.equal(new URL(x.frame.attrs.src,'http://localhost').searchParams.get('embed'),'1');
  assert.equal(x.button.textContent,'返回二维地图');
  x.button.handlers.click();
  assert.equal(x.viewport.hidden,false);assert.equal(x.frame.hidden,true);assert.equal(x.frame.attrs.src,undefined);
});

test('source full screen preserves iframe and exits with Escape inside the viewer',async()=>{
  const x=setup();x.ui.render(url);
  assert.equal(x.fullscreen.hidden,true);
  x.button.handlers.click();const src=x.frame.attrs.src;
  assert.equal(x.fullscreen.hidden,false);
  await x.fullscreen.handlers.click();
  assert.equal(x.container.attrs['data-expanded'],'true');
  assert.equal(x.fullscreen.textContent,'退出全屏');
  assert.equal(x.frame.attrs.src,src);
  x.frame.handlers.load();
  x.frame.contentDocument.handlers.keydown({key:'Escape'});
  assert.equal(x.container.attrs['data-expanded'],'false');
  assert.equal(x.frame.attrs.src,src);
});

test('native fullscreen exits on browser Escape and returning to map clears expansion',async()=>{
  const x=setup();
  x.container.requestFullscreen=async()=>{x.document.fullscreenElement=x.container;x.document.handlers.fullscreenchange();};
  x.document.exitFullscreen=async()=>{x.document.fullscreenElement=null;x.document.handlers.fullscreenchange();};
  x.ui.render(url);x.button.handlers.click();
  await x.fullscreen.handlers.click();
  assert.equal(x.document.fullscreenElement,x.container);
  await x.document.exitFullscreen();
  assert.equal(x.container.attrs['data-expanded'],'false');
  await x.fullscreen.handlers.click();x.button.handlers.click();
  assert.equal(x.document.fullscreenElement,null);
  assert.equal(x.fullscreen.hidden,true);
  assert.equal(x.frame.hidden,true);
});

test('denied native fullscreen falls back and changing project closes it',async()=>{
  const x=setup();x.container.requestFullscreen=async()=>{throw Error('unavailable');};
  x.ui.render(url);x.button.handlers.click();
  await x.fullscreen.handlers.click();
  assert.equal(x.container.attrs['data-expanded'],'true');
  x.ui.render(url.replace('project=site','project=next'));
  assert.equal(x.container.attrs['data-expanded'],'false');
});
test('height changes update the same source view without reloading its camera',()=>{
  const x=setup();x.ui.render(url);x.button.handlers.click();const src=x.frame.attrs.src;
  x.ui.render(url.replace('z_max=1','z_max=2'));
  assert.equal(x.frame.attrs.src,src);assert.deepEqual(x.messages.at(-1),[{type:'aletheia-pcd-band',band:[0,2]},'http://localhost']);
});
test('switching project or invalidating source closes the embedded view and prevents stale data',()=>{
  const x=setup();x.ui.render(url);x.button.handlers.click();
  x.ui.render(url.replace('project=site','project=next'));
  assert.equal(x.frame.hidden,true);assert.equal(x.viewport.hidden,false);
  x.button.handlers.click();x.ui.render(null);
  assert.equal(x.frame.hidden,true);assert.equal(x.button.disabled,true);
});
