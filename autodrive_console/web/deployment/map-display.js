import {paintMapContours} from './map-architecture.js';
import {readEditedMapPixels} from './erase-preview.js';
// Palette helper; geometric cleanup is derived separately in a worker.
// The two anchors follow the existing PGM preview (205 unknown, 254 free).
const palette = Array.from({length:256}, (_, shade) => {
  const start = shade <= 205 ? [51,68,85] : [231,236,242];
  const end = shade <= 205 ? [231,236,242] : [255,255,255];
  const t = shade <= 205 ? shade / 205 : Math.min(1,(shade-205)/49);
  return start.map((value,i)=>Math.round(value+(end[i]-value)*t));
});

export function mapDisplayPixels(source) {
  let count=0;
  for (let i=0;i<source.length;i+=4) if (source[i]<205 && source[i+3]) count++;
  const features=new Uint32Array(count), shades=new Uint8Array(count);
  const rgba=new Uint8ClampedArray(source.length);
  for (let i=0,j=0;i<source.length;i+=4) {
    const shade=source[i], color=palette[shade];
    rgba[i]=color[0]; rgba[i+1]=color[1]; rgba[i+2]=color[2]; rgba[i+3]=source[i+3];
    if (shade<205 && source[i+3]) { features[j]=i/4; shades[j++]=shade; }
  }
  return {rgba,features,shades};
}

// Match the PCD monochrome preview without changing unknown cells in the PGM.
export function mapMonochromePixels(source) {
  const rgba=new Uint8ClampedArray(source.length);
  for(let i=0;i<source.length;i+=4) {
    const shade=source[i]<205?0:255;
    rgba[i]=rgba[i+1]=rgba[i+2]=shade;rgba[i+3]=source[i+3];
  }
  return rgba;
}

export function mapRawDisplayPixels(source) {
  let count=0;
  for(let i=0;i<source.length;i+=4)if(source[i]<205&&source[i+3])count++;
  const features=new Uint32Array(count);
  for(let i=0,j=0;i<source.length;i+=4)if(source[i]<205&&source[i+3])features[j++]=i/4;
  return {rgba:mapMonochromePixels(source),features,shades:new Uint8Array(count)};
}

// Minimum-tone pooling ensures every source feature votes when several cells
// collapse into one screen pixel. No area/neighbor filter or sample stride.
export function rasterizeMapFeatures(features,shades,imageWidth,view) {
  const width=Math.ceil(view.width),height=Math.ceil(view.height);
  const tones=new Uint8Array(width*height); tones.fill(255);
  let previousRow=-1,cy=0,sy=0;
  for (let i=0;i<features.length;i++) {
    const cell=features[i],row=Math.floor(cell/imageWidth);
    if (row!==previousRow) {
      previousRow=row; cy=view.y+(row+.5)*view.scale;
      sy=Math.max(0,Math.min(height-1,Math.floor(cy)));
    }
    if (cy+view.scale/2<=0 || cy-view.scale/2>=height) continue;
    const cx=view.x+(cell-row*imageWidth+.5)*view.scale;
    if (cx+view.scale/2<=0 || cx-view.scale/2>=width) continue;
    const sx=Math.max(0,Math.min(width-1,Math.floor(cx))),index=sy*width+sx;
    if (shades[i]<tones[index]) tones[index]=shades[i];
  }
  return tones;
}

// Manual selections must survive even when a map has hundreds of annotations.
export function mapProtectionRegions(map,manual,anchors) {
  return [...manual,...anchors].slice(0,256).map(p=>({
    x:(p.x-map.origin[0])/map.resolution_m,
    y:map.height-(p.y-map.origin[1])/map.resolution_m,
    radius:.4/map.resolution_m,
  }));
}

export function mapClosureGeometry(map,walls=[],waypoints=[]) {
  const pixel=p=>({x:(p.x-map.origin[0])/map.resolution_m,y:map.height-(p.y-map.origin[1])/map.resolution_m});
  const virtualWalls=walls.filter(w=>w.map_asset_id===map.id).map(w=>({points:Array.isArray(w.points)?w.points:[w.start,w.end]}))
    .filter(w=>w.points.length>=2&&w.points.every(p=>Number.isFinite(p?.x)&&Number.isFinite(p?.y)))
    .map(w=>({points:w.points.map(pixel)}));
  const passagePoints=waypoints.filter(p=>p.map_asset_id===map.id&&p.kind==='start'&&Number.isFinite(p.x)&&Number.isFinite(p.y)).map(pixel);
  return {virtualWalls,passagePoints};
}

export function createMapDisplay(document,{workerFactory=()=>new Worker(new URL('./map-cleanup-worker.js',import.meta.url),{type:'module'}),
  bitmapFactory=typeof globalThis.OffscreenCanvas==='function'&&typeof globalThis.createImageBitmap==='function'?image=>createImageBitmap(image):null,sourceFactory=null,onChange=()=>{}}={}) {
  let image=null,prepared=null,rawPrepared=null,overlay=null,overlayKey=null;
  let worker=null,generation=0,inputKey='',changeOverlay=null,changeKey=null,showChanges=false,exportReady=false;
  function stopWorker(){worker?.terminate();worker=null;generation++;}
  const closeSurface=surface=>surface?.close?.();
  const closeMessage=data=>{closeSurface(data?.preview?.surface);closeSurface(data?.preview?.rawSurface);closeSurface(data?.result?.bitmap);};
  function setImage(next,{resolution,protectedPoints=[],removeIsolated=false,virtualWalls=[],passagePoints=[],mapEdits=[],rasterMap=null,mode='styled',preview=true}={}) {
    // renderProject can draw the new Image before its load event arrives.
    // An undecoded image is not a cached failure.
    if (next && (!next.naturalWidth || !next.naturalHeight)) return false;
    const rawOnly=mode==='raw';
    const key=rawOnly?'raw':JSON.stringify([resolution,protectedPoints,removeIsolated,virtualWalls,passagePoints,preview,mapEdits,rasterMap]);
    if (image===next && key===inputKey) return Boolean(prepared);
    stopWorker();inputKey=key;exportReady=false;
    closeSurface(prepared?.surface);closeSurface(rawPrepared?.surface);
    image=next; prepared=rawPrepared=overlay=overlayKey=changeOverlay=changeKey=null;
    if (!next) return false;
    if(bitmapFactory&&(rawOnly||Number.isFinite(resolution)&&resolution>0)) {
      const token=generation;
      const fail=(error='地图显示处理失败，已保留原始预览')=>{
        if(token!==generation)return;
        globalThis.RYAletheiaDiagnostics?.failure?.('deployment.map-display',error);
        closeSurface(prepared?.surface);prepared=null;stopWorker();onChange({phase:'fallback'});
      };
      try {
        worker=workerFactory();
        worker.onerror=event=>{event.preventDefault?.();fail();};
        worker.onmessage=({data})=>{
          if(token!==generation){closeMessage(data);return;}
          if(data.error){closeMessage(data);fail(data.error);return;}
          if(data.stage){onChange({phase:'processing',stage:data.stage});return;}
          const preview=data.preview,result=data.result;
          const valid=surface=>surface&&surface.width===next.naturalWidth&&surface.height===next.naturalHeight;
          if(preview) {
            if(!valid(preview.surface)||!valid(preview.rawSurface)){closeMessage(data);fail();return;}
            closeSurface(prepared?.surface);closeSurface(rawPrepared?.surface);
            prepared={surface:preview.surface,features:preview.features,shades:preview.shades};
            rawPrepared={surface:preview.rawSurface,features:preview.features,shades:new Uint8Array(preview.features.length)};
            overlayKey=null;onChange({phase:'processing',stage:'repair',preview:true});return;
          }
          if(!valid(result?.bitmap)){closeMessage(data);fail();return;}
          if(rawOnly) {
            rawPrepared={surface:result.bitmap,features:result.features,shades:result.shades};
            overlayKey=null;stopWorker();onChange({phase:'raw-ready'});return;
          }
          closeSurface(prepared?.surface);
          prepared={surface:result.bitmap,features:result.features,shades:result.shades,removed:result.removed,added:result.added,architecture:result.architecture,floorBits:result.floorBits};
          overlayKey=changeKey=null;exportReady=true;stopWorker();onChange({phase:'ready',stats:result.stats});
        };
        onChange({phase:rawOnly?'raw-processing':'processing',stage:'repair'});
        const sourceUrl=sourceFactory?.(next);
        if(sourceUrl) {
          worker.postMessage({sourceUrl,width:next.naturalWidth,height:next.naturalHeight,resolution,protectedPoints,removeIsolated,virtualWalls,passagePoints,rawOnly,preview,mapEdits:rawOnly?[]:mapEdits,rasterMap});
          return false;
        }
        Promise.resolve(bitmapFactory(next)).then(bitmap=>{
          if(token!==generation){closeSurface(bitmap);return;}
          try {worker.postMessage({bitmap,width:next.naturalWidth,height:next.naturalHeight,resolution,protectedPoints,removeIsolated,virtualWalls,passagePoints,rawOnly,preview,mapEdits:rawOnly?[]:mapEdits,rasterMap},[bitmap]);}
          catch {closeSurface(bitmap);fail();}
        },fail);
      } catch {fail();}
      return false;
    }
    try {
      const surface=document.createElement('canvas');
      surface.width=next.naturalWidth; surface.height=next.naturalHeight;
      if (!surface.width || !surface.height) return false;
      const context=surface.getContext('2d',{willReadFrequently:true});
      context.drawImage(next,0,0);
      const source=readEditedMapPixels(context,{width:surface.width,height:surface.height,map:rasterMap,edits:rawOnly?[]:mapEdits});
      if(rawOnly) {
        const result=mapRawDisplayPixels(source.data);
        source.data.set(result.rgba);context.putImageData(source,0,0);
        rawPrepared={surface,features:result.features,shades:result.shades};
        onChange({phase:'raw-ready'});return true;
      }
      const original=Number.isFinite(resolution)&&resolution>0?source.data.slice():null;
      const styled=mapDisplayPixels(source.data);
      rawPrepared={rgba:mapMonochromePixels(source.data),features:styled.features,shades:new Uint8Array(styled.features.length)};
      source.data.set(styled.rgba); context.putImageData(source,0,0);
      prepared={surface,features:styled.features,shades:styled.shades};
      if(Number.isFinite(resolution)&&resolution>0) {
        // Transfer the decoded source to a worker, leaving interactions on the
        // original/base preview responsive while the derived map is prepared.
        const token=generation;
        try {
          worker=workerFactory();
          const fail=(error='地图显示处理失败，已保留原始预览')=>{
            if(token!==generation)return;
            globalThis.RYAletheiaDiagnostics?.failure?.('deployment.map-display',error);
            prepared=null;stopWorker();onChange({phase:'fallback'});
          };
          worker.onerror=event=>{event.preventDefault?.();fail();};
          worker.onmessage=({data})=>{
            if(token!==generation)return;
            if(data.error){fail(data.error);return;}
            if(data.stage){onChange({phase:'processing',stage:data.stage});return;}
            try {
              const result=data.result;
              if(!(result?.rgba instanceof Uint8ClampedArray)||result.rgba.length!==surface.width*surface.height*4)throw Error('invalid display result');
              const output=typeof ImageData==='function'?new ImageData(result.rgba,surface.width,surface.height):context.createImageData(surface.width,surface.height);
              if(output.data!==result.rgba)output.data.set(result.rgba);
              context.putImageData(output,0,0);
              paintMapContours(context,result.architecture);
              prepared={surface,features:result.features,shades:result.shades,removed:result.removed,added:result.added,architecture:result.architecture,floorBits:result.floorBits};
              overlayKey=changeKey=null;exportReady=true;stopWorker();onChange({phase:'ready',stats:result.stats});
            }catch{fail();}
          };
          onChange({phase:'processing',stage:'repair'});
          worker.postMessage({rgba:original,width:surface.width,height:surface.height,resolution,protectedPoints,removeIsolated,virtualWalls,passagePoints},[original.buffer]);
        }catch(error){globalThis.RYAletheiaDiagnostics?.failure?.('deployment.map-display',error);prepared=null;stopWorker();onChange({phase:'fallback'});}
      }
      return Boolean(prepared);
    } catch (error) {
      // A failed decode/allocation keeps the original preview available.
      globalThis.RYAletheiaDiagnostics?.failure?.('deployment.map-display',error);
      onChange({phase:'fallback'});
      return false;
    }
  }
  function drawPrepared({context,image:next,activeMap,view,canvasBox,protectedPoints=[],removeIsolated=false,virtualWalls=[],passagePoints=[],process=false,raw=false,prepare=true}) {
    if(prepare)setImage(next,process?{resolution:activeMap.resolution_m,protectedPoints,removeIsolated,virtualWalls,passagePoints}:{});
    if(image!==next)return false;
    const base=raw?rawPrepared:prepared;
    if(!base)return false;
    if(raw&&!base.surface) {
      base.surface=document.createElement('canvas');
      base.surface.width=next.naturalWidth;base.surface.height=next.naturalHeight;
      const ctx=base.surface.getContext('2d'),output=ctx.createImageData(next.naturalWidth,next.naturalHeight);
      output.data.set(base.rgba);ctx.putImageData(output,0,0);base.rgba=null;
    }
    const pixels=view.scale*activeMap.resolution_m;
    context.imageSmoothingEnabled=Boolean(base.architecture);
    context.drawImage(base.surface,view.x,view.y,activeMap.width*pixels,activeMap.height*pixels);
    const ratio=context.canvas.width/canvasBox.width;
    const screen={width:context.canvas.width,height:context.canvas.height,
      x:view.x*ratio,y:view.y*ratio,scale:pixels*ratio};
    const key=[raw,screen.width,screen.height,screen.x,screen.y,screen.scale].join(',');
    if (screen.scale<1 && key!==overlayKey) {
      const tones=rasterizeMapFeatures(base.features,base.shades,base.surface.width,screen);
      overlay ||= document.createElement('canvas');
      overlay.width=screen.width; overlay.height=screen.height;
      const ctx=overlay.getContext('2d');
      const output=ctx.createImageData(screen.width,screen.height);
      for (let i=0;i<tones.length;i++) if (tones[i]<205) {
        const color=raw?[0,0,0]:palette[tones[i]];
        output.data[i*4]=color[0]; output.data[i*4+1]=color[1];
        output.data[i*4+2]=color[2]; output.data[i*4+3]=255;
      }
      ctx.putImageData(output,0,0); overlayKey=key;
    }
    context.save();
    try {
      context.beginPath(); context.rect(view.x,view.y,activeMap.width*pixels,activeMap.height*pixels); context.clip();
      if(screen.scale<1)context.drawImage(overlay,0,0,canvasBox.width,canvasBox.height);
      // Native contours are already baked into the worker bitmap. Redrawing
      // thousands of subpixel paths at fit scale adds work without detail.
      if(!raw&&base.architecture&&pixels>1)paintMapContours(context,base.architecture,{x:view.x,y:view.y,scale:pixels,viewport:canvasBox});
      if(!raw&&showChanges&&prepared.removed) {
        if(key!==changeKey) {
          changeOverlay ||= document.createElement('canvas');changeOverlay.width=screen.width;changeOverlay.height=screen.height;
          const ctx=changeOverlay.getContext('2d');
          const size=Math.max(2*ratio,screen.scale);
          for(const [points,color] of [[prepared.removed,'#c46a20'],[prepared.added,'#008c95']]) {
            ctx.fillStyle=color;
            for(const cell of points) {
              const x=screen.x+(cell%prepared.surface.width+.5)*screen.scale;
              const y=screen.y+(Math.floor(cell/prepared.surface.width)+.5)*screen.scale;
              if(x>=-size&&y>=-size&&x<screen.width+size&&y<screen.height+size)ctx.fillRect(x-size/2,y-size/2,size,size);
            }
          }
          changeKey=key;
        }
        context.drawImage(changeOverlay,0,0,canvasBox.width,canvasBox.height);
      }
    } finally { context.restore(); }
    return true;
  }
  function draw(options) {
    try { return drawPrepared(options); }
    catch (error) {
      globalThis.RYAletheiaDiagnostics?.failure?.('deployment.map-draw',error);
      closeSurface(prepared?.surface);closeSurface(rawPrepared?.surface);
      prepared=rawPrepared=overlay=overlayKey=changeOverlay=changeKey=null;exportReady=false;
      stopWorker();onChange({phase:'fallback'});return false;
    }
  }
  return {setImage,draw,drawRaw(options){try{return drawPrepared({...options,raw:true});}catch(error){globalThis.RYAletheiaDiagnostics?.failure?.('deployment.map-draw',error);return false;}},getExportSurface(){return exportReady?prepared?.surface||null:null;},setShowChanges(next){showChanges=Boolean(next);}};
}
