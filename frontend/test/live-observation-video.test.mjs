import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
const source=readFileSync(new URL('../src/liveObservation.js',import.meta.url),'utf8');
const start=name=>source.search(new RegExp(`\n(?:async )?function ${name}\\(`))+1;
const section=(first,next)=>source.slice(start(first),start(next));
const flush=async()=>{for(let n=0;n<30;n++)await Promise.resolve();};
const answer=location=>({ok:true,headers:{get:()=>location},text:async()=>'answer'});

// Keep lifecycle code real; replace external browser/GPU/network boundaries.
function browser(fetchImpl=async()=>answer('/session/current')) {
  let now=100,nextTimer=0,frameCallback,resolveInit,appCount=0,destroyCount=0,renderCount=0,updateCount=0;
  const timers=new Map(),peers=[],requests=[],diagnostics=[],resolutions=[],players=new Map(),dom=new Map();
  const options={deferInit:false};
  class Peer {
    constructor(){this.connectionState='new';this.iceGatheringState='complete';peers.push(this);}
    addTransceiver(){} async createOffer(){return {type:'offer',sdp:'offer'};}
    async setLocalDescription(value){this.localDescription=value;}
    async setRemoteDescription(value){if(this.connectionState==='closed')throw Error('closed');this.remote=value;}
    close(){this.connectionState='closed';this.onconnectionstatechange?.();}
  }
  class Application {
    canvas={classList:{add(){}},setAttribute(){}};ticker={stop(){}};
    stage={addChild(){}};renderer={resize(){}};
    constructor(){appCount++;}async init(){if(options.deferInit)await new Promise(r=>resolveInit=r);}
    render(){renderCount++;}destroy(){destroyCount++;}
  }
  class ResizeObserver {observe(){}disconnect(){}}
  const video={videoWidth:0,videoHeight:0,paused:true,ended:false,readyState:0,currentTime:0,
    async play(){this.paused=false;},pause(){this.paused=true;},
    requestVideoFrameCallback(callback){frameCallback=callback;return 1;},cancelVideoFrameCallback(){frameCallback=undefined;}};
  const timerApi={setTimeout(callback,delay){const id=++nextTimer;timers.set(id,{callback,at:now+delay});return id;},clearTimeout(id){timers.delete(id);}};
  const context={console,URL,AbortController,DOMException,Application,ResizeObserver,RTCPeerConnection:Peer,
    MediaStream:class{},performance:{now:()=>now},document:{hidden:false},window:{RTCPeerConnection:Peer,devicePixelRatio:1,...timerApi},...timerApi,
    fetch(url,opts){requests.push({url,opts});return fetchImpl(url,opts);},
    Texture:{from:()=>({source:{update(){updateCount++;}},destroy(){}})},Sprite:class {position={set(){}};destroy(){}},
    reportObservationOnce:(...args)=>diagnostics.push(args),resolveObservationDiagnostic:(...args)=>resolutions.push(args),
    mobileConsoleEnabled:()=>false,mobileWebRtcPlaybackAllowed:()=>true,setWebRtcVideoToggle(){},
    setText:(id,value)=>{context.$(id).textContent=value;},renderWebRtcStreamControls(){},syncMobilePrimaryWebRtcStream(){},
    webrtcPlayers:players,webrtcStreamTogglesInFlight:new Set(),webrtcToggleInFlight:false,
    videoWaitingSince:new Map(),activeObservationDiagnostics:new Set(),videoGatewayOfflineSince:0,
    $:id=>{if(!dom.has(id))dom.set(id,{dataset:{},setAttribute(){}});return dom.get(id);}};
  vm.createContext(context);
  const constants=source.match(/^const (?:VIDEO_INPUT_READINESS_TIMEOUT_MS|WEBRTC_[A-Z_]+) = [^;]+;/gm)||[];
  vm.runInContext(constants.join('\n')+'\n'+section('mobileWebRtcPlaybackAllowed','mirrorMobileConnection')+section('setWebRtcGatewayState','webRtcStreamLabel')+
    section('setWebRtcPlayerState','createWebRtcPlayer')+section('waitForIceGathering','refreshWebRtcVideoStatus'),context);
  const stream={name:'front_camera',enabled:true,status:'online',url:'http://mock.invalid:8889/front_camera/whep',resolution:'640x480',source_label:'CamFront',encoding:'rgb8'};
  const state={stream,retryAfter:0,video,label:{},detail:{},card:{dataset:{},remove(){}},toggle:{},
    surface:{getBoundingClientRect:()=>({width:640,height:480}),append(){}}};
  players.set(stream.name,state);
  const poll=runtime=>context.applyWebRtcVideoStatus({enabled:true,gateway:{online:true},streams:[stream],...(runtime?{runtime}:{})});
  const advance=async duration=>{const end=now+duration;while(true){const due=[...timers].filter(([,v])=>v.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];if(!due)break;now=due[1].at;timers.delete(due[0]);due[1].callback();await flush();}now=end;await flush();};
  const frame=()=>{video.videoWidth=640;video.videoHeight=480;video.readyState=4;video.currentTime+=1/15;const callback=frameCallback;frameCallback=undefined;callback?.(now,{presentedFrames:1});};
  return {context,stream,state,peers,requests,diagnostics,resolutions,timers,poll,advance,frame,options,finishInit:()=>resolveInit(),
    get appCount(){return appCount;},get destroyCount(){return destroyCount;},get renderCount(){return renderCount;},get updateCount(){return updateCount;}};
}

test('hung WHEP POST aborts within a deadline and reconnects only that stream',async()=>{
  const e=browser((_url,opts)=>new Promise((_resolve,reject)=>opts.signal?.addEventListener('abort',()=>reject(Error('aborted')))));
  e.poll();await flush();await e.advance(6000);
  assert.equal(e.requests[0].opts.signal?.aborted,true);assert.equal(e.state.pc,undefined);
  await e.advance(3001);e.poll();await flush();assert.equal(e.peers.length,2);
});
test('connected transport without a decoded first frame expires instead of reporting playback',async()=>{
  const e=browser();e.poll();await flush();e.state.pc.connectionState='connected';e.state.pc.onconnectionstatechange();
  assert.doesNotMatch(e.state.detail.textContent,/H\.264/);
  await e.advance(9000);e.poll();assert.equal(e.state.pc,undefined);
  assert.equal(e.resolutions.filter(([key])=>key==='webrtc-front_camera').length,0);
});
test('decoded frames mark recovery once and update the texture only once per frame',async()=>{
  const e=browser();e.poll();await flush();e.state.pc.connectionState='connected';await e.state.pc.ontrack({streams:[{}]});
  assert.equal(e.resolutions.filter(([key])=>key==='webrtc-front_camera').length,0);
  assert.equal(e.state.texture.source.autoUpdate,false);
  e.frame();assert.equal(e.state.hasDecodedFrame,true);for(let n=0;n<15;n++)e.frame();
  assert.equal(e.renderCount,16);assert.equal(e.updateCount,16);
  assert.equal(e.resolutions.filter(([key])=>key==='webrtc-front_camera').length,1);
  await e.advance(3000);e.poll();assert.ok(e.state.pc);
});
test('decoded video that stalls closes and retries without polling WebRTC stats',async()=>{
  const e=browser();e.poll();await flush();const peer=e.state.pc;peer.connectionState='connected';peer.getStats=()=>{throw Error('unexpected stats polling');};
  await peer.ontrack({streams:[{}]});e.frame();await e.advance(9000);e.poll();assert.equal(e.state.pc,undefined);
  await e.advance(3001);e.poll();await flush();assert.equal(e.peers.length,2);
});
test('play rejection releases the broken peer and permits retry',async()=>{
  const e=browser();e.state.video.play=async()=>{throw Error('decoder failed');};e.poll();await flush();const peer=e.state.pc;peer.connectionState='connected';
  await peer.ontrack({streams:[{}]});assert.equal(e.state.pc,undefined);await e.advance(3001);e.poll();await flush();assert.equal(e.peers.length,2);
});
test('late WHEP response is deleted without replacing the current cleanup handle',async()=>{
  let resolveOld,posts=0;
  const e=browser((_url,opts)=>opts.method==='DELETE'?Promise.resolve({ok:true}):++posts===1?new Promise(r=>resolveOld=r):Promise.resolve(answer('/session/new')));
  const oldConnection=e.context.connectWebRtcPlayer(e.state,e.stream);await flush();e.context.closeWebRtcPlayer(e.state);await e.advance(3001);
  await e.context.connectWebRtcPlayer(e.state,e.stream);resolveOld(answer('/session/old'));await oldConnection;
  assert.equal(e.state.sessionUrl,'http://mock.invalid:8889/session/new');
  assert.deepEqual(e.requests.filter(r=>r.opts.method==='DELETE').map(r=>r.url),['http://mock.invalid:8889/session/old']);
});
test('destroy during Pixi initialization disposes the app before attaching to a removed card',async()=>{
  const e=browser();e.options.deferInit=true;const initializing=e.context.initializeWebRtcRenderer(e.state);await flush();
  e.context.destroyWebRtcPlayer(e.stream.name);e.finishInit();await initializing;
  assert.equal(e.context.webrtcPlayers.size,0);assert.equal(e.destroyCount,1);assert.equal(e.state.app,undefined);assert.equal(e.state.resizeObserver,undefined);
});
test('hardware encoder failure appears in the visible gateway diagnosis',()=>{
  const e=browser();e.stream.status='waiting';e.poll({state:'error',encoder:null,detail:'No compatible hardware H.264 encoder'});
  assert.match(e.context.$('webrtcGatewayState').textContent,/No compatible hardware H\.264 encoder/);assert.match(e.state.detail.textContent,/No compatible hardware H\.264 encoder/);
});
test('ShmSDK waiting identifies the configured camera instead of claiming a ROS source',()=>{
  const e=browser();e.stream.status='waiting';e.poll();assert.match(e.state.detail.textContent,/CamFront/);assert.doesNotMatch(e.state.detail.textContent,/ROS/);
});
test('WHEP headers followed by a stalled SDP body still release the peer within the deadline',async()=>{
  const e=browser(async()=>({ok:true,headers:{get:()=>'/session/body-stall'},text:()=>new Promise(()=>{})}));
  e.poll();await flush();await e.advance(6000);assert.equal(e.state.pc,undefined);
  assert.equal(e.requests[0].opts.signal.aborted,true);
  assert.ok(e.requests.some(r=>r.opts.method==='DELETE'&&r.url.endsWith('/session/body-stall')));
});
test('play completion after closing a player cannot initialize or attach a renderer',async()=>{
  let finishPlay;const e=browser();e.state.video.play=()=>new Promise(resolve=>finishPlay=resolve);
  e.poll();await flush();const attach=e.state.pc.ontrack({streams:[{}]});await flush();
  e.context.closeWebRtcPlayer(e.state);finishPlay();await attach;
  assert.equal(e.appCount,0);assert.equal(e.state.video.srcObject,null);assert.equal(e.state.pc,undefined);
});
test('hidden document releases video and does not start another decoder until visible',async()=>{
  const e=browser();e.poll();await flush();e.context.document.hidden=true;e.poll();
  assert.equal(e.state.pc,undefined);await e.advance(10000);e.poll();await flush();assert.equal(e.peers.length,1);
  e.context.document.hidden=false;e.poll();await flush();assert.equal(e.peers.length,2);
});
test('a per-stream input error is diagnosed using the backend reason',()=>{
  const e=browser();e.stream.status='waiting';e.stream.error_code='ingest_failed';e.stream.detail='CamFront JPEG input rejected';e.poll();
  assert.ok(e.diagnostics.some(([key,,message])=>key==='video-input-front_camera'&&message.includes('JPEG input rejected')));
});
test('closing a decoded stream blanks its canvas instead of leaving the last image visible',async()=>{
  const e=browser();e.poll();await flush();await e.state.pc.ontrack({streams:[{}]});e.frame();
  const framesBeforeClose=e.renderCount;e.context.closeWebRtcPlayer(e.state);
  assert.equal(e.state.texture,undefined);assert.equal(e.renderCount,framesBeforeClose+1);
  e.context.closeWebRtcPlayer(e.state);assert.equal(e.renderCount,framesBeforeClose+1);
});
test('old setRemoteDescription completion cannot cancel the replacement handshake deadline',async()=>{
  let finishRemote,posts=0;
  const e=browser((_url,opts)=>opts.method==='DELETE'?Promise.resolve({ok:true}):++posts===1?Promise.resolve(answer('/session/old')):new Promise(()=>{}));
  const oldConnection=e.context.connectWebRtcPlayer(e.state,e.stream);
  e.state.pc.setRemoteDescription=()=>new Promise(resolve=>finishRemote=resolve);await flush();
  e.context.closeWebRtcPlayer(e.state);await e.advance(3001);e.poll();await flush();const replacement=e.state.pc;
  finishRemote();await oldConnection;assert.equal(e.state.pc,replacement);
  await e.advance(6000);assert.equal(e.state.pc,undefined);
  assert.equal(e.requests.filter(r=>r.opts.method==='POST')[1].opts.signal.aborted,true);
});
test('encoder failure does not falsely label an online MediaMTX gateway as disconnected',()=>{
  const e=browser();e.stream.status='waiting';e.poll({state:'error',encoder:null,detail:'No hardware H.264 encoder'});
  assert.doesNotMatch(e.context.$('webrtcGatewayBadge').textContent,/网关离线/);
  assert.match(e.context.$('webrtcGatewayState').textContent,/No hardware H\.264 encoder/);
});
