const annotationLabel = (annotation) =>
  String(annotation?.label || "此标记").trim() || "此标记";

/**
 * Delete one map annotation and then reload the authoritative project snapshot.
 *
 * The browser must never retain a locally edited route after an annotation is
 * removed: the backend owns the automatic route recalculation.  Keeping this
 * sequence in one helper makes components and manual waypoints follow the
 * same observable lifecycle.
 */
export async function deleteDeploymentAnnotation({
  projectId,
  annotation,
  collection,
  request,
  refreshProject,
  notify,
}) {
  const label = annotationLabel(annotation);
  const id = String(annotation?.id || "").trim();
  if (!projectId || !id || !["components", "waypoints"].includes(collection)) {
    throw new Error("删除标记所需的信息不完整");
  }

  notify(`正在删除${label}…`);
  try {
    await request(
      `/api/deployments/${encodeURIComponent(projectId)}/${collection}/${encodeURIComponent(id)}`,
      { method: "DELETE" },
    );
    await refreshProject(projectId);
    notify(`${label}已删除；系统已根据剩余标记重新计算路线。`);
    return true;
  } catch (error) {
    const detail = error instanceof Error && error.message ? error.message : "请求失败";
    notify(`删除${label}失败：${detail}。请检查连接后重试。`, true);
    throw error;
  }
}
