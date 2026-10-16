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
  let now=100,nextTimer=0,frameCallback,initializations=[],appCount=0,destroyCount=0,renderCount=0,updateCount=0;
  const timers=new Map(),intervals=new Map(),peers=[],requests=[],apiRequests=[],diagnostics=[],resolutions=[],players=new Map(),dom=new Map();
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
    constructor(){appCount++;}async init(){if(options.deferInit)await new Promise((resolve,reject)=>initializations.push({resolve,reject}));}
    render(){renderCount++;}destroy(){destroyCount++;}
  }
  class ResizeObserver {observe(){}disconnect(){}}
  const video={videoWidth:0,videoHeight:0,paused:true,ended:false,readyState:0,currentTime:0,
    async play(){this.paused=false;},pause(){this.paused=true;},
    requestVideoFrameCallback(callback){frameCallback=callback;return 1;},cancelVideoFrameCallback(){frameCallback=undefined;}};
  const timerApi={setTimeout(callback,delay){const id=++nextTimer;timers.set(id,{callback,at:now+delay});return id;},clearTimeout(id){timers.delete(id);},
    setInterval(callback){const id=++nextTimer;intervals.set(id,callback);return id;},clearInterval(id){intervals.delete(id);}};
  const context={console,URL,AbortController,DOMException,Application,ResizeObserver,RTCPeerConnection:Peer,
    MediaStream:class{},performance:{now:()=>now},document:{hidden:false},window:{RTCPeerConnection:Peer,devicePixelRatio:1,...timerApi},...timerApi,
    fetch(url,opts){requests.push({url,opts});return fetchImpl(url,opts);},
    request(url,opts={}){apiRequests.push({url,opts});return options.requestImpl?options.requestImpl(url,opts):Promise.resolve({enabled:true,gateway:{online:true},streams:[stream]});},
    Texture:{from:()=>({source:{update(){updateCount++;}},destroy(){}})},Sprite:class {position={set(){}};destroy(){}},
    reportObservation(){},reportObservationOnce:(...args)=>diagnostics.push(args),resolveObservationDiagnostic:(...args)=>resolutions.push(args),
    mobileConsoleEnabled:()=>false,mobileWebRtcPlaybackAllowed:()=>true,setWebRtcVideoToggle(){},
    setText:(id,value)=>{context.$(id).textContent=value;},renderWebRtcStreamControls(){},syncMobilePrimaryWebRtcStream(){},
    webrtcPlayers:players,webrtcSessionCleanups:new Map(),webrtcStreamTogglesInFlight:new Set(),webrtcToggleInFlight:false,
    webrtcStatusRequest:undefined,webrtcStatusTimer:undefined,webrtcStatusStopped:false,webrtcControlRequest:undefined,
    videoWaitingSince:new Map(),activeObservationDiagnostics:new Set(),videoGatewayOfflineSince:0,
    $:id=>{if(!dom.has(id))dom.set(id,{dataset:{},setAttribute(){}});return dom.get(id);}};
  vm.createContext(context);
  const constants=source.match(/^const (?:VIDEO_INPUT_READINESS_TIMEOUT_MS|WEBRTC_[A-Z_]+) = [^;]+;/gm)||[];
  vm.runInContext(constants.join('\n')+'\n'+section('mobileWebRtcPlaybackAllowed','mirrorMobileConnection')+section('setWebRtcGatewayState','webRtcStreamLabel')+
    section('setWebRtcPlayerState','createWebRtcPlayer')+section('waitForIceGathering','setupMapInteraction'),context);
  const stream={name:'front_camera',enabled:true,status:'online',url:'http://mock.invalid:8889/front_camera/whep',resolution:'640x480',source_label:'CamFront',encoding:'rgb8'};
  const state={stream,retryAfter:0,video,label:{},detail:{},card:{dataset:{},remove(){}},toggle:{},
    surface:{getBoundingClientRect:()=>({width:640,height:480}),append(){}}};
  players.set(stream.name,state);
  const poll=runtime=>context.applyWebRtcVideoStatus({enabled:true,gateway:{online:true},streams:[stream],...(runtime?{runtime}:{})});
  const advance=async duration=>{const end=now+duration;while(true){const due=[...timers].filter(([,v])=>v.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];if(!due)break;now=due[1].at;timers.delete(due[0]);due[1].callback();await flush();}now=end;await flush();};
  const frame=()=>{video.videoWidth=640;video.videoHeight=480;video.readyState=4;video.currentTime+=1/15;const callback=frameCallback;frameCallback=undefined;callback?.(now,{presentedFrames:1});};
  return {context,stream,state,peers,requests,apiRequests,diagnostics,resolutions,timers,poll,advance,frame,options,tick:()=>{for(const callback of intervals.values())callback();},finishInit:(index=initializations.length-1)=>initializations[index].resolve(),failInit:(index=0)=>initializations[index].reject(Error("old initialization rejected")),
    get appCount(){return appCount;},get destroyCount(){return destroyCount;},get renderCount(){return renderCount;},get updateCount(){return updateCount;}};
}

test('slow video status requests stay single-flight instead of building a polling backlog',async()=>{
  const e=browser();e.options.requestImpl=()=>new Promise(()=>{});
  e.context.refreshWebRtcVideoStatus();e.context.refreshWebRtcVideoStatus();await flush();
  assert.equal(e.apiRequests.length,1);
});
test('a stalled video status request is aborted and the next refresh can proceed',async()=>{
  const e=browser();e.options.requestImpl=(_url,opts)=>new Promise((_resolve,reject)=>opts.signal?.addEventListener('abort',()=>reject(Error('aborted'))));
  const pending=e.context.refreshWebRtcVideoStatus();await flush();await e.advance(5100);
  assert.equal(e.apiRequests[0].opts.signal?.aborted,true);await pending;
  e.context.refreshWebRtcVideoStatus();await flush();assert.equal(e.apiRequests.length,2);
});
test('a late status response cannot undo a more recent video shutdown',async()=>{
  const e=browser();e.poll();await flush();let resolveOld;
  e.options.requestImpl=url=>url==='/api/video/status'?new Promise(resolve=>{resolveOld ||= resolve;}):Promise.resolve({enabled:false,gateway:{online:false},streams:[{...e.stream,enabled:false}]});
  const old=e.context.refreshWebRtcVideoStatus();await flush();await e.context.toggleWebRtcVideo();
  assert.equal(e.context.webrtcPlayers.size,0);
  resolveOld({enabled:true,gateway:{online:true},streams:[e.stream]});await old;await flush();
  assert.equal(e.context.webrtcVideoEnabled,false);
  assert.equal(e.context.webrtcPlayers.size,0);assert.equal(e.peers.length,1);
});
test('a truncated or invalid status response does not shut down healthy video',async()=>{
  const e=browser();e.poll();await flush();const peer=e.state.pc;peer.connectionState='connected';
  await peer.ontrack({streams:[{}]});e.frame();e.options.requestImpl=async()=>({});
  await e.context.refreshWebRtcVideoStatus();
  assert.equal(e.state.pc,peer);assert.equal(e.state.label.textContent,'播放中');
  assert.equal(e.context.webrtcVideoEnabled,true);
});
test('an invalid control response cannot be interpreted as shutting down every stream',async()=>{
  const e=browser();e.poll();await flush();const peer=e.state.pc;peer.connectionState='connected';
  await peer.ontrack({streams:[{}]});e.frame();e.options.requestImpl=async()=>({});
  await e.context.toggleWebRtcVideo();await flush();
  assert.equal(e.context.webrtcVideoEnabled,true);assert.equal(e.state.pc,peer);
});
test('a paused decoded image is visibly marked before the reconnect deadline and clears on a fresh frame',async()=>{
  const e=browser();e.poll();await flush();const peer=e.state.pc;peer.connectionState='connected';
  await peer.ontrack({streams:[{}]});e.frame();const texture=e.state.texture;
  await e.advance(2000);e.poll();
  assert.equal(e.state.label.textContent,'画面停顿');assert.equal(e.state.pc,peer);assert.equal(e.state.texture,texture);
  e.frame();assert.equal(e.state.label.textContent,'播放中');
});
test('stopping status updates aborts the active request and rejects its late result',async()=>{
  const e=browser();e.poll();await flush();let resolveOld;
  e.options.requestImpl=()=>new Promise(resolve=>resolveOld=resolve);
  e.context.startWebRtcVideoStatus();await flush();e.context.stopWebRtcVideoStatus();
  assert.equal(e.apiRequests[0].opts.signal.aborted,true);
  resolveOld({enabled:false,gateway:{online:false},streams:[]});await flush();
  assert.equal(e.context.webrtcVideoEnabled,true);const count=e.apiRequests.length;
  e.tick();assert.equal(e.apiRequests.length,count);
});
test('a hidden page releases its player even when its status request is stalled',async()=>{
  const e=browser();e.poll();await flush();e.options.requestImpl=()=>new Promise(()=>{});
  e.context.startWebRtcVideoStatus();e.context.document.hidden=true;e.tick();await flush();
  assert.equal(e.state.pc,undefined);e.context.document.hidden=false;e.tick();await flush();
  assert.equal(e.peers.length,2);
});
for(const perStream of [false,true])test(`${perStream?'per-stream':'global'} control timeout releases the switch and reconciles without repeating POST`,async()=>{
  const e=browser();e.poll();await flush();
  e.options.requestImpl=(url,opts)=>url==='/api/video/control'
    ?new Promise((_resolve,reject)=>opts.signal?.addEventListener('abort',()=>reject(Error('aborted'))))
    :Promise.resolve({enabled:false,gateway:{online:false},streams:[]});
  const pending=perStream?e.context.toggleWebRtcStream(e.stream):e.context.toggleWebRtcVideo();
  await e.advance(16000);
  assert.equal(e.apiRequests.find(r=>r.url==='/api/video/control').opts.signal?.aborted,true);
  await pending;await flush();
  assert.equal(e.context.webrtcToggleInFlight,false);assert.equal(e.context.webrtcStreamTogglesInFlight.size,0);
  assert.equal(e.apiRequests.filter(r=>r.url==='/api/video/control').length,1);
  assert.equal(e.context.webrtcVideoEnabled,false);
});
test('video recovery proceeds on its heartbeat even when the status API is stalled',async()=>{
  const e=browser();e.poll();await flush();const peer=e.state.pc;peer.connectionState='connected';
  await peer.ontrack({streams:[{}]});e.frame();e.options.requestImpl=()=>new Promise(()=>{});
  e.context.startWebRtcVideoStatus();await e.advance(9000);e.tick();await flush();
  assert.equal(e.state.pc,undefined);
  await e.advance(3001);e.tick();await flush();assert.equal(e.peers.length,2);
});
test('a failed player retries when its backoff expires without waiting for another status tick',async()=>{
  const e=browser();e.poll();await flush();const peer=e.state.pc;peer.connectionState='connected';
  await peer.ontrack({streams:[{}]});e.frame();peer.connectionState='failed';peer.onconnectionstatechange();
  await e.advance(2999);assert.equal(e.peers.length,1);
  await e.advance(2);assert.equal(e.peers.length,2);
});
test('closing a failed player cancels its scheduled retry',async()=>{
  const e=browser();e.poll();await flush();const peer=e.state.pc;peer.connectionState='failed';peer.onconnectionstatechange();
  e.context.closeWebRtcPlayer(e.state);await e.advance(3100);assert.equal(e.peers.length,1);
});
test('a stalled session DELETE is aborted before the player retry backoff expires',async()=>{
  const e=browser((_url,opts)=>opts.method==='DELETE'
    ?new Promise((_resolve,reject)=>opts.signal?.addEventListener('abort',()=>reject(Error('aborted'))))
    :Promise.resolve(answer('/session/current')));
  e.poll();await flush();e.context.closeWebRtcPlayer(e.state);
  const removal=e.requests.find(r=>r.opts.method==='DELETE');
  await e.advance(1600);assert.equal(removal.opts.signal?.aborted,true);
});
test('successful session cleanup cancels its deadline',async()=>{
  const e=browser();e.context.deleteWebRtcSession('http://mock.invalid/session/finished');await flush();
  const removal=e.requests[0];await e.advance(2000);
  assert.equal(removal.opts.signal?.aborted,false);assert.equal(e.timers.size,0);
});
test('active-page cleanup remains transport-cancellable instead of using keepalive',async()=>{
  const e=browser();e.context.deleteWebRtcSession('http://mock.invalid/session/current');await flush();
  assert.equal(e.requests[0].opts.keepalive,false);
});
test('page-exit cleanup preserves its best-effort keepalive request',async()=>{
  const e=browser();e.context.stopWebRtcVideoStatus();e.context.deleteWebRtcSession('http://mock.invalid/session/exiting');await flush();
  assert.equal(e.requests[0].opts.keepalive,true);
});
test('a temporary DELETE failure retains the old cleanup handle until removal succeeds',async()=>{
  let attempts=0;
  const e=browser(async()=>++attempts===1?{ok:false,status:503}:{ok:true,status:204});
  e.context.deleteWebRtcSession('http://mock.invalid/session/old');await flush();
  await e.advance(2500);
  assert.equal(e.requests.length,2);
  assert.ok(e.requests.every(r=>r.url==='http://mock.invalid/session/old'&&r.opts.method==='DELETE'));
  await e.advance(10000);assert.equal(e.requests.length,2);assert.equal(e.timers.size,0);
});
test('a timed-out cleanup retries without closing the replacement player',async()=>{
  let deletions=0;
  const e=browser((_url,opts)=>opts.method!=='DELETE'?Promise.resolve(answer('/session/new')):
    ++deletions===1?new Promise((_resolve,reject)=>opts.signal.addEventListener('abort',()=>reject(Error('aborted')))):
    Promise.resolve({ok:true,status:204}));
  e.context.deleteWebRtcSession('http://mock.invalid/session/old');e.poll();await flush();
  const replacement=e.state.pc;await e.advance(4500);
  assert.equal(deletions,2);assert.equal(e.state.pc,replacement);assert.notEqual(replacement.connectionState,'closed');
});
test('duplicate cleanup calls for one resource share one bounded retry sequence',async()=>{
  const e=browser(async()=>({ok:false,status:503}));
  for(let n=0;n<6;n++)e.context.deleteWebRtcSession('http://mock.invalid/session/old');
  await e.advance(20000);
  assert.equal(e.requests.length,3);assert.equal(e.timers.size,0);
});
for(const status of [404,410,403])test(`cleanup HTTP ${status} does not repeatedly delete an absent or forbidden session`,async()=>{
  const e=browser(async()=>({ok:false,status}));
  e.context.deleteWebRtcSession('http://mock.invalid/session/old');await e.advance(20000);
  assert.equal(e.requests.length,1);assert.equal(e.timers.size,0);
});
test('page exit cancels pending cleanup retries instead of creating new requests',async()=>{
  const e=browser(async()=>({ok:false,status:503}));
  e.context.deleteWebRtcSession('http://mock.invalid/session/old');await flush();
  e.context.stopWebRtcVideoStatus();await e.advance(20000);
  assert.equal(e.requests.length,1);assert.equal(e.timers.size,0);
});
test('a scheduled retry cannot replace a peer that has already reconnected',async()=>{
  const e=browser();e.poll();await flush();const peer=e.state.pc;peer.connectionState='failed';peer.onconnectionstatechange();
  await e.advance(3001);e.poll();await flush();const replacement=e.state.pc;
  replacement.connectionState='connected';await replacement.ontrack({streams:[{}]});e.frame();
  await e.advance(3100);assert.equal(e.state.pc,replacement);assert.equal(e.peers.length,2);
});

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
test('a brief WebRTC disconnect keeps the decoded frame and recovers the same peer',async()=>{
  const e=browser();e.poll();await flush();const peer=e.state.pc;peer.connectionState='connected';
  await peer.ontrack({streams:[{}]});e.frame();const texture=e.state.texture;
  peer.connectionState='disconnected';peer.onconnectionstatechange();
  assert.equal(e.state.pc,peer);assert.equal(e.state.texture,texture);
  assert.equal(e.state.label.textContent,'连接波动');
  await e.advance(420);
  peer.connectionState='connected';peer.onconnectionstatechange();
  assert.equal(e.state.pc,peer);assert.equal(e.state.texture,texture);
  assert.notEqual(e.state.label.textContent,'播放中');
  e.frame();assert.equal(e.state.label.textContent,'播放中');
  await e.advance(5000);e.poll();assert.equal(e.state.pc,peer);
  assert.equal(e.requests.filter(r=>r.opts.method==='POST').length,1);
  assert.equal(e.requests.filter(r=>r.opts.method==='DELETE').length,0);
});
test('repeated disconnected notifications cannot extend the recovery deadline',async()=>{
  const e=browser();e.poll();await flush();const peer=e.state.pc;peer.connectionState='connected';
  await peer.ontrack({streams:[{}]});e.frame();
  peer.connectionState='disconnected';peer.onconnectionstatechange();
  await e.advance(4000);peer.onconnectionstatechange();assert.equal(e.state.pc,peer);
  await e.advance(1100);assert.equal(e.state.pc,undefined);assert.equal(e.state.texture,undefined);
  assert.equal(e.requests.filter(r=>r.opts.method==='DELETE').length,1);
  await e.advance(3001);e.poll();await flush();assert.equal(e.peers.length,2);
});
test('closing a player cancels its network recovery timer without touching a replacement peer',async()=>{
  const e=browser();e.poll();await flush();const peer=e.state.pc;peer.connectionState='connected';
  await peer.ontrack({streams:[{}]});e.frame();
  peer.connectionState='disconnected';peer.onconnectionstatechange();
  e.context.closeWebRtcPlayer(e.state);e.poll();await flush();const replacement=e.state.pc;
  replacement.connectionState='connected';await replacement.ontrack({streams:[{}]});e.frame();
  await e.advance(5100);assert.equal(e.state.pc,replacement);
});
test('a failed connection still releases immediately during the recovery window',async()=>{
  const e=browser();e.poll();await flush();const peer=e.state.pc;peer.connectionState='connected';
  await peer.ontrack({streams:[{}]});e.frame();
  peer.connectionState='disconnected';peer.onconnectionstatechange();
  assert.equal(e.state.pc,peer);
  peer.connectionState='failed';peer.onconnectionstatechange();assert.equal(e.state.pc,undefined);
});
test('a recovered transport without a new frame still expires as stalled video',async()=>{
  const e=browser();e.poll();await flush();const peer=e.state.pc;peer.connectionState='connected';
  await peer.ontrack({streams:[{}]});e.frame();
  peer.connectionState='disconnected';peer.onconnectionstatechange();await e.advance(420);
  peer.connectionState='connected';peer.onconnectionstatechange();
  assert.equal(e.state.label.textContent,'等待画面恢复');
  await e.advance(8000);e.poll();assert.equal(e.state.pc,undefined);
  assert.match(e.state.detail.textContent,/解码已停滞/);
});
test('the stall watchdog does not shorten the bounded disconnect recovery window',async()=>{
  const e=browser();e.poll();await flush();const peer=e.state.pc;peer.connectionState='connected';
  await peer.ontrack({streams:[{}]});e.frame();await e.advance(7000);
  peer.connectionState='disconnected';peer.onconnectionstatechange();await e.advance(2000);e.poll();
  assert.equal(e.state.pc,peer);assert.equal(e.state.label.textContent,'连接波动');
  await e.advance(3100);assert.equal(e.state.pc,undefined);
});
test('buffered frames during a disconnect cannot falsely resolve network recovery',async()=>{
  const e=browser();e.poll();await flush();const peer=e.state.pc;peer.connectionState='connected';
  await peer.ontrack({streams:[{}]});e.frame();const resolved=e.resolutions.length;
  peer.connectionState='disconnected';peer.onconnectionstatechange();e.frame();
  assert.equal(e.state.label.textContent,'连接波动');assert.equal(e.resolutions.length,resolved);
  peer.connectionState='connected';peer.onconnectionstatechange();
  assert.equal(e.state.label.textContent,'等待画面恢复');e.frame();
  assert.equal(e.state.label.textContent,'播放中');assert.equal(e.resolutions.length,resolved+1);
});
test('a recovering peer stuck in connecting cannot escape its disconnect deadline',async()=>{
  const e=browser();e.poll();await flush();const peer=e.state.pc;peer.connectionState='connected';
  await peer.ontrack({streams:[{}]});e.frame();
  peer.connectionState='disconnected';peer.onconnectionstatechange();await e.advance(3000);
  peer.connectionState='connecting';peer.onconnectionstatechange();await e.advance(2100);
  assert.equal(e.state.pc,undefined);assert.equal(e.state.texture,undefined);
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


test('backgrounding decoded video releases its GPU app and recreates it only on return',async()=>{
  const e=browser();e.poll();await flush();await e.state.pc.ontrack({streams:[{}]});e.frame();
  assert.equal(e.appCount,1);
  e.context.document.hidden=true;e.context.maintainWebRtcPlayers();
  assert.equal(e.state.pc,undefined);assert.equal(e.state.app,undefined);
  assert.equal(e.state.resizeObserver,undefined);assert.equal(e.destroyCount,1);
  e.context.document.hidden=false;e.context.maintainWebRtcPlayers();await flush();
  await e.state.pc.ontrack({streams:[{}]});e.frame();
  assert.equal(e.appCount,2);assert.equal(e.state.label.textContent,'播放中');
});
test('leaving the mobile camera workspace releases its GPU app',async()=>{
  const e=browser();e.poll();await flush();await e.state.pc.ontrack({streams:[{}]});e.frame();
  e.context.mobileWebRtcPlaybackAllowed=()=>false;e.context.maintainWebRtcPlayers();
  assert.equal(e.state.pc,undefined);assert.equal(e.state.app,undefined);assert.equal(e.destroyCount,1);
});
test('GPU initialization finishing after backgrounding cannot attach a renderer',async()=>{
  const e=browser();e.options.deferInit=true;e.poll();await flush();
  const attaching=e.state.pc.ontrack({streams:[{}]});await flush();
  e.context.document.hidden=true;e.context.maintainWebRtcPlayers();e.finishInit();await attaching;
  assert.equal(e.state.app,undefined);assert.equal(e.state.resizeObserver,undefined);assert.equal(e.destroyCount,1);
});
test('a temporary network retry reuses the active video renderer',async()=>{
  const e=browser();e.poll();await flush();const peer=e.state.pc;await peer.ontrack({streams:[{}]});e.frame();
  const app=e.state.app;e.context.failWebRtcPlayer(e.state,peer,'test interruption');await e.advance(3000);
  await e.state.pc.ontrack({streams:[{}]});e.frame();
  assert.equal(e.state.app,app);assert.equal(e.appCount,1);assert.equal(e.destroyCount,0);
});

test('late background initialization cannot replace the returning camera renderer',async()=>{
  const e=browser();e.options.deferInit=true;e.poll();await flush();
  const oldAttaching=e.state.pc.ontrack({streams:[{}]});await flush();
  e.context.document.hidden=true;e.context.maintainWebRtcPlayers();
  e.context.document.hidden=false;e.context.maintainWebRtcPlayers();await flush();
  const newAttaching=e.state.pc.ontrack({streams:[{}]});await flush();
  e.finishInit(1);await newAttaching;const currentApp=e.state.app;
  e.finishInit(0);await oldAttaching;
  assert.equal(e.state.app,currentApp);assert.equal(e.appCount,2);assert.equal(e.destroyCount,1);
  e.frame();assert.equal(e.state.label.textContent,'播放中');
});
test('late rejected background initialization cannot reset the returning camera initialization',async()=>{
  const e=browser();e.options.deferInit=true;e.poll();await flush();
  const oldAttaching=e.state.pc.ontrack({streams:[{}]});await flush();
  e.context.document.hidden=true;e.context.maintainWebRtcPlayers();
  e.context.document.hidden=false;e.context.maintainWebRtcPlayers();await flush();
  const newAttaching=e.state.pc.ontrack({streams:[{}]});await flush();
  e.failInit(0);await oldAttaching;
  const shared=e.context.initializeWebRtcRenderer(e.state);await flush();
  assert.equal(e.appCount,2);
  e.finishInit(1);await newAttaching;await shared;e.frame();
  assert.equal(e.state.label.textContent,'播放中');
});
test('the mobile map button immediately releases video GPU resources without waiting for heartbeat',async()=>{
  const e=browser();e.poll();await flush();await e.state.pc.ontrack({streams:[{}]});e.frame();
  e.context.mobileConsoleEnabled=()=>true;e.context.mapInfo=null;
  e.context.document.documentElement={dataset:{}};e.context.document.querySelectorAll=()=>[];
  vm.runInContext(section('setMobileConsoleView','setupMobileConsole'),e.context);
  e.context.setMobileConsoleView('map',false);
  assert.equal(e.state.pc,undefined);assert.equal(e.state.app,undefined);
  assert.equal(e.state.resizeObserver,undefined);assert.equal(e.destroyCount,1);
});
