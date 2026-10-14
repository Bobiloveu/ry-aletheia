// Four-neighbour labelling with horizontal runs, rather than one queued entry
// per pixel. Large open floors need only a small stack of scanline segments.
export function visitMapComponents({width,height,open,begin=()=>{},span=()=>{}}) {
  const length=width*height,labels=new Uint32Array(length);
  let stack=new Uint32Array(4096),top=0,label=0;
  function push(index) {
    const row=index-index%width,end=row+width;
    let left=index,right=index;
    while(left>row&&!labels[left-1]&&open(left-1))left--;
    while(right+1<end&&!labels[right+1]&&open(right+1))right++;
    labels.fill(label,left,right+1);
    if(top+2>stack.length){const next=new Uint32Array(stack.length*2);next.set(stack);stack=next;}
    stack[top++]=left;stack[top++]=right;
    return right;
  }
  for(let seed=0;seed<length;seed++) {
    if(labels[seed]||!open(seed))continue;
    label++;begin(label,seed);push(seed);
    while(top) {
      const right=stack[--top],left=stack[--top];
      if(left>=width)for(let i=left-width;i<=right-width;i++)if(!labels[i]&&open(i))i=push(i);
      if(right+width<length)for(let i=left+width;i<=right+width;i++)if(!labels[i]&&open(i))i=push(i);
      span(label,left,right,labels);
    }
  }
  return labels;
}
