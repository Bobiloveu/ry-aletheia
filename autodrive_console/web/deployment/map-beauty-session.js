import {createMapDisplay} from './map-display.js';

export function mapBeautyIdentity(projectId,map) {
  const imageFile=map.files?.image;
  return {
    id:JSON.stringify([projectId,map.id]),
    source:JSON.stringify([map.width,map.height,map.resolution_m,map.origin,imageFile,
      map.sha256?.[imageFile?.split('/').at(-1)]||map.sha256?.['map.pgm']||null]),
  };
}

function inputKey(options,edits,identity) {
  // Protection points only affect the optional isolated-feature filter. Normal
  // components are overlays and must not invalidate the default floor result.
  // Start markers are annotations too. Passage seeds are sampled when a new
  // generation is requested, not when reusing a completed/in-flight result.
  return JSON.stringify([identity?.source,options.resolution,Boolean(options.removeIsolated),
    options.removeIsolated ? options.protectedPoints||[] : [],
    options.virtualWalls||[],edits]);
}

// Keep completed maps across switches. Geometry changes only invalidate their
// own entry; computation still requires an explicit user action.
export function createMapBeautySession({document,displayOptions={},onChange=()=>{},maxEntries=8,maxBytes=384*1024*1024}) {
  const entries=new Map();let active=null,showChanges=false;
  const touch=entry=>{entries.delete(entry.id);entries.set(entry.id,entry);};
  const release=entry=>{entry.display.setImage(null);entry.image=null;};
  function suspend(entry) {
    if(!entry||entry.phase==='ready')return;
    if(entry.phase==='processing')entry.phase='dirty';
    release(entry);
  }
  function prune() {
    // Include the retained source image, derived raster, floor bits and a
    // margin for contours/features. The active map is never evicted.
    const weight=()=>[...entries.values()].reduce((sum,e)=>sum+(e.phase==='ready'?e.image.naturalWidth*e.image.naturalHeight*9:0),0);
    while(entries.size>maxEntries||weight()>maxBytes) {
      const oldest=[...entries.values()].find(e=>e!==active);
      if(!oldest)break;
      entries.delete(oldest.id);release(oldest);
    }
  }
  function createEntry(id) {
    const entry={id,image:null,options:{},key:null,phase:'idle',requested:false,stats:null};
    entry.display=createMapDisplay(document,{...displayOptions,onChange(state) {
      entry.phase=state.phase;
      if(state.phase==='ready')entry.stats=state.stats;
      prune();
      if(entry===active)onChange(state);
    }});
    entry.display.setShowChanges(showChanges);
    entries.set(id,entry);return entry;
  }
  const display={
    draw(options){return active?.phase==='ready' ? active.display.draw({...options,image:active.image}) : false;},
    getExportSurface(){return active?.phase==='ready' ? active.display.getExportSurface() : null;},
    setShowChanges(next){showChanges=Boolean(next);for(const e of entries.values())e.display.setShowChanges(showChanges);},
  };
  return {
    display,
    get phase(){return active?.phase||'idle';},
    sync(next,options={},edits=[],identity) {
      if(!next) {
        if(!active)return;
        suspend(active);active=null;onChange({phase:'idle'});return;
      }
      const id=identity?.id??identity??next;
      const entry=entries.get(id)||createEntry(id),switched=entry!==active;
      if(switched){suspend(active);active=entry;}
      touch(entry);
      const key=inputKey(options,edits,identity),changed=key!==entry.key;
      entry.options={...options,mapEdits:edits};
      if(changed) {
        release(entry);entry.key=key;entry.phase=entry.requested?'dirty':'idle';entry.stats=null;
      }
      if(entry.phase!=='ready'&&entry.phase!=='processing')entry.image=next;
      prune();
      if(changed||switched)onChange({phase:entry.phase,stats:entry.stats,restored:!changed&&entry.phase==='ready'});
    },
    generate({blocked=false}={}) {
      const entry=active;
      if(blocked||!entry?.image?.naturalWidth||!entry.image.naturalHeight||entry.phase==='processing')return false;
      if(entry.phase==='ready')return true;
      entry.requested=true;
      if(entry.phase==='fallback')entry.display.setImage(null);
      entry.display.setImage(entry.image,{...entry.options,preview:false});
      return true;
    },
    cancel() {
      if(active?.phase!=='processing')return;
      active.display.setImage(null);active.phase='dirty';onChange({phase:'dirty'});
    },
    dispose() {
      active=null;for(const entry of entries.values())release(entry);entries.clear();onChange({phase:'idle'});
    },
  };
}
