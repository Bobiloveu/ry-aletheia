import test from 'node:test';
import assert from 'node:assert/strict';
import {visitMapComponents} from '../../../autodrive_console/web/deployment/map-components.js';

test('scanline components match four-neighbour reachability on thin, cropped and fragmented grids',()=>{
  let random=37;
  for(let sample=0;sample<120;sample++) {
    const width=sample%19+1,height=sample%23+1,length=width*height;
    const cells=Uint8Array.from({length},()=>{random=(Math.imul(random,1664525)+1013904223)>>>0;return random%5>1?1:0;});
    const expected=new Uint32Array(length);let label=0;
    for(let seed=0;seed<length;seed++)if(cells[seed]&&!expected[seed]) {
      label++;const queue=[seed];expected[seed]=label;
      for(let head=0;head<queue.length;head++) {
        const i=queue[head],x=i%width;
        for(const j of[x>0?i-1:-1,x+1<width?i+1:-1,i>=width?i-width:-1,i+width<length?i+width:-1])
          if(j>=0&&cells[j]&&!expected[j]){expected[j]=label;queue.push(j);}
      }
    }
    let visited=0;
    const actual=visitMapComponents({width,height,open:i=>cells[i],span:(id,left,right)=>{
      assert.ok(left<=right&&Math.floor(left/width)===Math.floor(right/width));visited+=right-left+1;
    }});
    assert.deepEqual(actual,expected,`${width}x${height}`);
    assert.equal(visited,cells.reduce((a,b)=>a+b,0));
  }
});
