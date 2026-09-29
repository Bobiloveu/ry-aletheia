(() => {
  try {
    const light = localStorage.getItem("ry-aletheia-theme") === "light";
    const root = document.documentElement;
    root.dataset.theme = light ? "light" : "dark";
    root.style.colorScheme = light ? "light" : "dark";
  } catch {
    // Storage can be unavailable in restrictive browser contexts. The shell's
    // default palette remains a safe fallback in that case.
  }
})();
