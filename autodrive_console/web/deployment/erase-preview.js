export function eraseEditsForRender({
  savedEdits = [],
  activeMapId,
  activeStroke = null,
  pendingStroke = null,
}) {
  const edits = savedEdits.filter((edit) => edit.map_asset_id === activeMapId);
  if (activeStroke) edits.push(activeStroke);
  if (pendingStroke) edits.push(pendingStroke);
  return edits;
}
