import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

import {
  isActivePreviewRequest,
  hasPersistedPreview,
  projectWithPreviewHash,
  previewMatchesProject,
  previewMatchesTaskMode,
} from "../../autodrive_console/web/deployment/task-compiler-preview.js";

test("successful task compiler preview is retained against its project input hash", () => {
  const project = {
    id: "project-1",
    task_compiler: { identity: { community: "高科一号" } },
  };
  const preview = { status: "ready", input_sha256: "preview-input-sha" };

  const updated = projectWithPreviewHash(project, preview);

  assert.notEqual(updated, project);
  assert.equal(updated.task_compiler.identity.last_preview_input_sha256, "preview-input-sha");
  assert.equal(previewMatchesProject(updated, preview), true);
  assert.equal(project.task_compiler.identity.last_preview_input_sha256, undefined);
});

test("persisted preview is restored only when its current project lacks a matching local preview", () => {
  const project = {
    task_compiler: { identity: { last_preview_input_sha256: "preview-input-sha" } },
  };

  assert.equal(hasPersistedPreview(project), true);
  assert.equal(previewMatchesProject(project, { input_sha256: "preview-input-sha" }), true);
  assert.equal(previewMatchesProject(project, { input_sha256: "stale-input-sha" }), false);
});

test("preview responses apply only to the project that started the request", () => {
  assert.equal(isActivePreviewRequest("project-a", { id: "project-a" }), true);
  assert.equal(isActivePreviewRequest("project-a", { id: "project-b" }), false);
  assert.equal(isActivePreviewRequest("project-a", null), false);
});

test('the selected mode must match both the preview and the real artifact structure',()=>{
  for(const mode of ['single','multi']) {
    const prefix=mode==='multi'?'multi_tasks/':'tasks/';
    const preview={status:'ready',task_mode:mode,manifest:{task_mode:mode},artifacts:[{path:`${prefix}task.json`}]};
    assert.equal(previewMatchesTaskMode({task_mode:mode},preview),true);
    assert.equal(previewMatchesTaskMode({task_mode:mode},{...preview,task_mode:'fixed'}),false);
    assert.equal(previewMatchesTaskMode({task_mode:mode},{...preview,artifacts:[{path:mode==='multi'?'tasks/wrong.json':'multi_tasks/wrong.json'}]}),false);
    assert.equal(previewMatchesTaskMode({task_mode:mode},{...preview,manifest:{task_mode:mode==='multi'?'single':'multi'}}),false);
    assert.equal(previewMatchesTaskMode({task_mode:mode},{...preview,artifacts:{}}),false);
    assert.equal(previewMatchesTaskMode({task_mode:mode},{...preview,artifacts:[{path:42}]}),false);
  }
});

test('a hash-matching cached single preview cannot be reused by a multi project',async()=>{
  const {reusableTaskPreview}=await import('../../autodrive_console/web/deployment/task-compiler-preview.js');
  const project={id:'p',task_mode:'multi',task_compiler:{identity:{last_preview_input_sha256:'sha'}}};
  const stale={status:'ready',input_sha256:'sha',task_mode:'single',artifacts:[{path:'tasks/old.json'}]};
  assert.equal(reusableTaskPreview(project,stale,'p'),false);
});

test('reopening a ready preview reuses it only for the unchanged owning project', async () => {
  const { reusableTaskPreview } = await import('../../autodrive_console/web/deployment/task-compiler-preview.js');
  const project = {id:'a',task_compiler:{identity:{last_preview_input_sha256:'sha'}}};
  const preview = {status:'ready',input_sha256:'sha'};
  assert.equal(reusableTaskPreview(project, preview, 'a'), true);
  assert.equal(reusableTaskPreview(project, preview, 'b'), false);
  assert.equal(reusableTaskPreview({...project,task_compiler:{}}, preview, 'a'), false);
  assert.equal(reusableTaskPreview(project, {...preview,status:'blocked'}, 'a'), false);
});

test('the export download keeps the readable community and line name from the backend',async()=>{
  const source=readFileSync(new URL('../../autodrive_console/web/deployment.js',import.meta.url),'utf8');
  const download=source.match(/async function downloadTaskCompilerBundle\(\) \{[\s\S]*?\n\}/)[0];
  const filename='高科一号_超市取货_experimental.zip',button={disabled:false},links=[];
  const state={selectedProject:{id:'p'},taskCompilerPreview:{status:'ready'},taskLineCompileBlocked:()=>false,$:()=>button,
    taskCompilerMessage(){},compilerRecovery:s=>s,URL:{createObjectURL:()=> 'blob:qa',revokeObjectURL(){}},
    fetch:async()=>({ok:true,blob:async()=>({}),headers:{get:()=>`attachment; filename=task-compiler-experimental.zip; filename*=UTF-8''${encodeURIComponent(filename)}`}}),
    document:{createElement:()=>({click(){links.push(this.download);},remove(){}}),body:{append(){}}}};
  runInNewContext(download,state);
  await state.downloadTaskCompilerBundle();
  assert.deepEqual(links,[filename]);
  assert.equal(button.disabled,false);
});
