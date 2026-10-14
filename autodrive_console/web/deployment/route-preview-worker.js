import {buildRouteGrid,planRouteSegments} from './route-planner.js';
import {readEditedMapPixels} from './erase-preview.js';
import {buildLocalRouteGrid} from './route-refinement.js';
const maps=new Map();
self.onmessage=async({data})=>{
  try {
    let rgba=null;
    async function pixels() {
      if(rgba)return rgba;
      const response=await fetch(data.sourceUrl);
      if(!response.ok)throw Error('路线预览无法读取地图');
      const bitmap=await createImageBitmap(await response.blob()),map=data.map;
      if(bitmap.width!==map.width||bitmap.height!==map.height||map.width*map.height>64000000){bitmap.close();throw Error('路线预览地图尺寸无效');}
      const canvas=new OffscreenCanvas(map.width,map.height),context=canvas.getContext('2d',{willReadFrequently:true});
      context.drawImage(bitmap,0,0);bitmap.close();
      rgba=readEditedMapPixels(context,{width:map.width,height:map.height,map,edits:data.edits}).data;
      return rgba;
    }
    let entry=maps.get(data.scope);
    if(!entry) {
      const map=data.map;
      entry={grid:buildRouteGrid({rgba:await pixels(),width:map.width,height:map.height,map,virtualWalls:data.walls,radiusM:data.radiusM}),pairs:new Map()};
    }
    maps.delete(data.scope);maps.set(data.scope,entry);
    while(maps.size>3)maps.delete(maps.keys().next().value);
    let result=planRouteSegments(entry.grid,data.segments,entry.pairs);
    if(result.failures.length&&entry.grid.resolution>data.map.resolution_m&&
       [...entry.pairs.values()].some(path=>path.status!=='ready'&&!path.refinementAttempted)) {
      const map=data.map;
      const source={rgba:await pixels(),width:map.width,height:map.height,map,virtualWalls:data.walls,radiusM:data.radiusM};
      result=planRouteSegments(entry.grid,data.segments,entry.pairs,{refineGrid:(a,b)=>buildLocalRouteGrid(source,a,b)});
    }
    self.postMessage({key:data.key,result});
  } catch(error){self.postMessage({key:data.key,error:error.message});}
};
