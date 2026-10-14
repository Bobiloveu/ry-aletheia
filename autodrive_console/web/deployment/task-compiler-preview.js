function previewHash(preview) {
  const value = preview?.input_sha256;
  return typeof value === "string" && value.trim() ? value : null;
}

function projectPreviewHash(project) {
  const value = project?.task_compiler?.identity?.last_preview_input_sha256;
  return typeof value === "string" && value.trim() ? value : null;
}

export function hasPersistedPreview(project) {
  return Boolean(projectPreviewHash(project));
}

export function isActivePreviewRequest(projectId, project) {
  return typeof projectId === "string" && projectId === project?.id;
}

export function previewMatchesProject(project, preview) {
  const expected = projectPreviewHash(project);
  const actual = previewHash(preview);
  return Boolean(expected && actual && expected === actual);
}

export function previewMatchesTaskMode(project, preview) {
  // Pre-mode historical callers can still compare their input hashes. All
  // current project snapshots carry a mode and require a matching structure.
  if (project?.task_mode === undefined) return true;
  const mode = project.task_mode;
  if (!['single','multi'].includes(mode)) return false;
  const actual = preview?.task_mode ?? preview?.manifest?.task_mode;
  if (actual !== mode || (preview?.manifest?.task_mode && preview.manifest.task_mode !== mode)) return false;
  const artifacts = preview?.artifacts ?? preview?.manifest?.artifacts ?? [];
  if (!Array.isArray(artifacts)) return false;
  const paths = artifacts.map(item => typeof item?.path === 'string' ? item.path : '');
  const [expected,forbidden] = mode === 'multi' ? ['multi_tasks/','tasks/'] : ['tasks/','multi_tasks/'];
  return paths.some(path=>path.startsWith(expected)) && !paths.some(path=>path.startsWith(forbidden));
}

export function reusableTaskPreview(project, preview, ownerId) {
  return project?.id === ownerId && preview?.status === "ready" && previewMatchesProject(project, preview) && previewMatchesTaskMode(project, preview);
}

export function previewIncludesTaskLine(preview,lineId) {
  return preview?.manifest?.active_task_line?.id===lineId ||
    Boolean(preview?.manifest?.compiled_task_lines?.some(line=>line.id===lineId));
}

/** View a server-owned route span; never concatenate or infer runtime routes. */
export function selectTaskLinePreview(preview,lineId='all') {
  const line=preview?.manifest?.compiled_task_lines?.find(line=>line.id===lineId);
  if(!line || lineId==='all')return preview;
  const start=line.subtask_start,end=start+line.subtask_count;
  return {...preview,task_json:{...preview.task_json,subtasks:preview.task_json.subtasks.slice(start,end)},
    manifest:{...preview.manifest,active_task_line:line,compiled_task_lines:[line],
      subtask_map_asset_ids:preview.manifest.subtask_map_asset_ids.slice(start,end),
      subtask_task_line_ids:preview.manifest.subtask_task_line_ids.slice(start,end),
      waypoint_trace:preview.manifest.waypoint_trace.filter(node=>node.task_line_id===line.id)}};
}

/** One controlled compile at a time; only the latest saved editor may display it. */
export function createTaskLineMapPreview({request,onChange=()=>{}}) {
  let active=null,inFlight=null,state={phase:'idle',preview:null};
  const same=(a,b)=>a===b || Boolean(a&&b&&a.project===b.project&&
    a.projectGeneration===b.projectGeneration&&a.editGeneration===b.editGeneration&&
    a.lineGeneration===b.lineGeneration&&a.lineId===b.lineId);
  const emit=next=>{state=next;onChange(state);};
  async function start(context) {
    inFlight=context;
    try {
      const data=await request(`/api/deployments/${encodeURIComponent(context.project.id)}/task-compiler/preview`,{
        method:'POST',headers:{'Content-Type':'application/json'},body:'{}',
      });
      if(!same(active,context))return;
      const preview=data.preview;
      if(preview?.status!=='ready')throw Error(preview?.errors?.join('；') || '完整路线校验未通过');
      if(!previewMatchesTaskMode(context.project,preview)||!previewIncludesTaskLine(preview,context.lineId))
        throw Error('完整路线与当前项目模式或线路不一致，请重新校验');
      emit({phase:'ready',preview});
    } catch(error) {
      if(same(active,context))emit({phase:'error',preview:null,error:error.message});
    } finally {
      inFlight=null;
      if(active&&!same(active,context))start(active);
    }
  }
  return {
    stateFor(context){return context&&same(active,context)?state:{phase:'idle',preview:null};},
    sync(context) {
      if(same(active,context))return;
      active=context;
      emit({phase:context?'processing':'idle',preview:null});
      if(context&&!inFlight)start(context);
    },
  };
}

export function projectWithPreviewHash(project, preview) {
  const hash = previewHash(preview);
  if (!project || !hash) return project;
  return {
    ...project,
    task_compiler: {
      ...(project.task_compiler || {}),
      identity: {
        ...(project.task_compiler?.identity || {}),
        last_preview_input_sha256: hash,
      },
    },
  };
}
