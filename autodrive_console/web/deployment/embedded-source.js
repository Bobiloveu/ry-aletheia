/** Presentation-only switch: retain the 2D viewport and unload GPU work on return. */
export function bindEmbeddedSource({container,viewport,zoom,button,frame,help,fullscreen,origin=globalThis.location?.origin}) {
  let url=null, key=null, sourceMode=false;
  const document=container.ownerDocument;
  let expanded=false, fullscreenIntent=0;
  function setExpanded(value) {
    expanded=value;
    container.setAttribute('data-expanded',String(value));
    if(fullscreen) {
      fullscreen.textContent=value?'退出全屏':'全屏查看';
      fullscreen.setAttribute('aria-pressed',String(value));
    }
  }
  function closeExpanded() {
    fullscreenIntent+=1;
    setExpanded(false);
    if(document?.fullscreenElement===container) return document.exitFullscreen().catch(()=>{});
  }
  function escape(event) { if(event.key==='Escape' && expanded) closeExpanded(); }
  document?.addEventListener('keydown',escape);
  document?.addEventListener('fullscreenchange',()=>{
    if(document.fullscreenElement===container) setExpanded(true);
    else if(expanded && !container.hasAttribute?.('data-fullscreen-fallback')) setExpanded(false);
  });
  fullscreen?.addEventListener('click',async()=>{
    if(!sourceMode) return;
    if(expanded) return closeExpanded();
    const intent=++fullscreenIntent;
    container.setAttribute('data-fullscreen-fallback','');
    setExpanded(true);
    if(container.requestFullscreen) {
      try {
        await container.requestFullscreen();
        container.removeAttribute('data-fullscreen-fallback');
        if(intent!==fullscreenIntent && document?.fullscreenElement===container) await document.exitFullscreen();
      } catch { /* Keep the same window enlarged when browser fullscreen is denied. */ }
    }
  });
  function syncBand() {
    if (!sourceMode || !url) return;
    const query=new URL(url,origin).searchParams;
    frame.contentWindow?.postMessage({type:'aletheia-pcd-band',band:[Number(query.get('z_min')),Number(query.get('z_max'))]},origin);
  }
  function show(source) {
    sourceMode=Boolean(source && url);
    if(fullscreen) fullscreen.hidden=!sourceMode;
    if(!sourceMode) closeExpanded();
    container.setAttribute('data-view',sourceMode?'source':'map');
    viewport.hidden=sourceMode;zoom.hidden=sourceMode;frame.hidden=!sourceMode;
    button.textContent=sourceMode?'返回二维地图':'查看源 PCD';
    button.setAttribute('aria-expanded',String(sourceMode));
    help.textContent=sourceMode?'拖动旋转 · 滚轮缩放 · 右键拖动平移':'滚轮缩放 · 拖动平移 · 适配恢复全图';
    if (sourceMode) {
      const target=new URL(url,origin);target.searchParams.set('embed','1');
      frame.setAttribute('src',`${target.pathname}${target.search}`);
    } else frame.removeAttribute('src');
  }
  button.addEventListener('click',()=>{if(url)show(!sourceMode);});
  frame.addEventListener('load',()=>{
    syncBand();
    // Escape inside the same-origin source iframe must also close fallback view.
    frame.contentDocument?.addEventListener('keydown',escape);
  });
  show(false);
  return {render(next){
    const parsed=next?new URL(next,origin):null;
    const nextKey=parsed?`${parsed.searchParams.get('project')}/${parsed.searchParams.get('projection')}`:null;
    if(!next || key!==nextKey)show(false);
    key=nextKey;url=next;
    button.disabled=!url;
    if(sourceMode)syncBand();
  },close(){show(false);}};
}
