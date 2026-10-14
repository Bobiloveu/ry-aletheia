// Session-only undo metadata. Every inverse still goes through Backend CRUD.
export function createMapEditHistory({limit=100,onChange=()=>{}}={}) {
  let entries=[];
  const pending=new Map(),key=(projectId,mapId)=>JSON.stringify([projectId,mapId]);
  const owns=(entry,projectId,mapId)=>entry.projectId===projectId&&entry.mapId===mapId;
  return {
    push(projectId,mapId,operation) {
      entries.push({...structuredClone(operation),projectId,mapId});
      entries=entries.slice(-limit);onChange();
    },
    peek(projectId,mapId) {return entries.findLast(entry=>owns(entry,projectId,mapId))||null;},
    remove(entry) {entries=entries.filter(item=>item!==entry);onChange();},
    clear(projectId,mapId) {entries=entries.filter(entry=>!owns(entry,projectId,mapId));onChange();},
    remapWall(projectId,mapId,oldId,newId) {
      for(const entry of entries)if(owns(entry,projectId,mapId)&&entry.wallId===oldId)entry.wallId=newId;
    },
    busy(projectId,mapId) {return Boolean(pending.get(key(projectId,mapId)));},
    begin(projectId,mapId) {
      const scope=key(projectId,mapId);let finished=false;
      pending.set(scope,(pending.get(scope)||0)+1);onChange();
      return ()=>{
        if(finished)return;finished=true;
        const count=pending.get(scope)-1;
        if(count)pending.set(scope,count);else pending.delete(scope);
        onChange();
      };
    },
  };
}
