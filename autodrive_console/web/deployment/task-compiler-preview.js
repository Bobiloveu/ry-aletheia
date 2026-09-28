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
