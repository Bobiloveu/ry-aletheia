import {beautifyMap} from './map-cleanup.js';
import {mapDisplayPixels,mapMonochromePixels,mapRawDisplayPixels} from './map-display.js';
import {paintMapContours} from './map-architecture.js';
import {readEditedMapPixels} from './erase-preview.js';
self.onmessage=async({data})=>{
  try {
    let canvas,context;
    if(data.sourceUrl) {
      const response=await fetch(data.sourceUrl);
      if(!response.ok)throw Error('地图显示数据读取失败');
      data.bitmap=await createImageBitmap(await response.blob());
    }
    if(data.bitmap) {
      const {bitmap,width,height}=data;
      if(!Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1||width*height>64000000
        ||bitmap.width!==width||bitmap.height!==height){bitmap.close();throw Error('地图显示数据无效');}
      canvas=new OffscreenCanvas(width,height);context=canvas.getContext('2d',{willReadFrequently:true});
      try {
        context.drawImage(bitmap,0,0);
        if(!data.rawOnly && data.mapEdits?.length) {
          const map=data.rasterMap;
          if(!map || !(map.resolution_m>0))throw Error('地图修正缺少栅格元数据');
        }
        data.rgba=readEditedMapPixels(context,{width,height,map:data.rasterMap,edits:data.rawOnly?[]:data.mapEdits}).data;
      }
      finally {bitmap.close();delete data.bitmap;}
      if(data.rawOnly) {
        const result=mapRawDisplayPixels(data.rgba);
        context.putImageData(new ImageData(result.rgba,width,height),0,0);
        result.bitmap=canvas.transferToImageBitmap();delete result.rgba;
        self.postMessage({result},[result.bitmap,result.features.buffer,result.shades.buffer]);
        return;
      }
      if(data.preview!==false) {
        const styled=mapDisplayPixels(data.rgba);
        context.putImageData(new ImageData(styled.rgba,width,height),0,0);
        const surface=canvas.transferToImageBitmap();
        context.putImageData(new ImageData(mapMonochromePixels(data.rgba),width,height),0,0);
        const rawSurface=canvas.transferToImageBitmap();
        // The source features are also needed after cleanup for raw-view pooling.
        self.postMessage({preview:{surface,rawSurface,features:styled.features,shades:styled.shades}},
          [surface,rawSurface,styled.features.buffer,styled.shades.buffer]);
      }
    }
    const result=beautifyMap(data,stage=>self.postMessage({stage}));
    // Masks are only used in algorithm QA; the browser receives display data.
    delete result.mask;delete result.floor;
    const geometry=[result.architecture.vertices.buffer,result.architecture.offsets.buffer,result.floorBits.buffer];
    if(canvas) {
      context.putImageData(new ImageData(result.rgba,data.width,data.height),0,0);
      paintMapContours(context,result.architecture);
      result.bitmap=canvas.transferToImageBitmap();delete result.rgba;
      self.postMessage({result},[result.bitmap,result.features.buffer,result.shades.buffer,result.removed.buffer,result.added.buffer,...geometry]);
    } else self.postMessage({result},[result.rgba.buffer,result.features.buffer,result.shades.buffer,result.removed.buffer,result.added.buffer,...geometry]);
  } catch(error){self.postMessage({error:error.message});}
};
