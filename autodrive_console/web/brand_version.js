(() => {
  const normalizeCaseWorkspaceLabel = () => {
    // 旧页面与 Vue 构建产物曾分别内嵌“用例资产库”。统一在共享品牌脚本中
    // 修正，确保跨页面导航始终使用“测试用例管理”，且不改变原链接与图标结构。
    document.querySelectorAll('a[href="/case-library.html"]').forEach((link) => {
      const icon = link.querySelector('span');
      link.textContent = '';
      if (icon) link.appendChild(icon);
      link.append('测试用例管理');
    });
  };
  const showVersion = () => {
    const brand = document.querySelector('.brand > div:last-child');
    if (!brand) return;
    // Vue 页面已渲染 `.brand-version`，静态页面才需要创建它；两者必须复用同一节点。
    let target = document.querySelector('.brand .brand-version') || document.getElementById('consoleVersion');
    if (!target) {
      target = document.createElement('span');
      target.id = 'consoleVersion';
      target.className = 'brand-version';
      brand.appendChild(target);
    }
  fetch('/api/system/upgrade')
    .then(response => response.ok ? response.json() : null)
    .then(data => {
      const version = typeof data?.current_version === 'string' && data.current_version.trim() ? data.current_version.trim() : '开发版';
      target.textContent = version === '开发版' ? version : `v${version}`;
      target.title = `当前工具版本：${target.textContent}`;
    })
    .catch(() => { target.textContent = 'v—'; });
  };
  // 静态页和 Vue 生产页的脚本加载时序不同；DOM 就绪后再挂载可兼容两者。
  const initialize = () => { normalizeCaseWorkspaceLabel(); showVersion(); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, { once: true });
  else setTimeout(initialize, 0);
})();
