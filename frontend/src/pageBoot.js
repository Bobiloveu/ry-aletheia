// Vue entry styles arrive through the module graph. Keep the static document
// hidden until that graph has mounted, otherwise an inline SVG (notably the
// live-observation brand mark) can briefly render at its browser-default size.
function revealPage() {
  const app = document.getElementById("app");
  if (!app) return;
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      document.documentElement.dataset.pageReady = "true";
      app.dataset.pageReady = "true";
    });
  });
}

revealPage();
