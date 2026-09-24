export function synchronizeMapSourceChoice(root, selectedSource) {
  root.querySelectorAll("[data-map-source]").forEach((input) => {
    input.checked = input.dataset.mapSource === selectedSource;
  });
}
