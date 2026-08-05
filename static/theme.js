(function () {
  'use strict';
  var KEY = 'sofia_theme';
  var META = 'theme-color';
  var DURATION = 120;
  var fab, aura;

  function systemDark() {
    try { return window.matchMedia('(prefers-color-scheme: dark)').matches; } catch (e) { return false; }
  }

  function saved() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }

  function current() {
    var stored = saved();
    if (stored === 'dark') return 'dark';
    if (stored === 'light') return 'light';
    return systemDark() ? 'dark' : 'light';
  }

  function apply(theme) {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
    var meta = document.querySelector('meta[name="' + META + '"]');
    if (meta) {
      meta.setAttribute('content', theme === 'dark' ? '#100C0A' : '#C41E24');
    }
  }

  function reducedMotion() {
    try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; }
  }

  function createStyles() {
    if (document.getElementById('themeAuraStyles')) return;
    var style = document.createElement('style');
    style.id = 'themeAuraStyles';
    style.textContent =
      'html, body, .top-bar, .hero-card, .glass-card, .stat-card, .flota-mini-card, .liquid-glass, .glass-header, .bg-pattern-dots, .bg-pattern-grid, .brand-name, .live-badge, .kpi-num, .stat-info .value { transition: background 260ms ease, background-color 260ms ease, color 260ms ease, border-color 260ms ease, box-shadow 260ms ease, fill 260ms ease, stroke 260ms ease; }' +
      '#themeFab{position:fixed;right:1.25rem;bottom:1.25rem;width:56px;height:56px;border-radius:50%;border:none;background:var(--primary);color:#fff;display:inline-flex;align-items:center;justify-content:center;box-shadow:0 16px 40px rgba(0,0,0,.18);cursor:pointer;transition:transform .2s ease,background .2s ease,box-shadow .2s ease;z-index:10001;}' +
      '#themeFab:hover{transform:translateY(-2px);box-shadow:0 18px 45px rgba(0,0,0,.22);}' +
      '#themeFab:active{transform:translateY(0);}' +
      '#themeFab svg{width:22px;height:22px;}' +
      '#themeAura{position:fixed;width:260px;height:260px;border-radius:50%;pointer-events:none;opacity:0;visibility:hidden;transform:translate(-50%,-50%) scale(0.01);transition:transform ' + DURATION + 'ms cubic-bezier(0.22,1,0.36,1),opacity 160ms ease;z-index:10000;will-change:transform,opacity;}' +
      '.dark #themeAura{background:rgba(8,5,4,0.85);}' +
      ':not(.dark) #themeAura{background:rgba(255,255,255,0.95);}';
    document.head.appendChild(style);
  }

  function showAura(x, y, targetTheme) {
    if (!aura) return;
    aura.style.left = x + 'px';
    aura.style.top = y + 'px';
    aura.style.transition = 'none';
    aura.style.transform = 'translate(-50%, -50%) scale(0.7)';
    aura.style.opacity = '0';
    aura.style.visibility = 'visible';
    aura.style.background = targetTheme === 'dark' ? 'rgba(8,5,4,0.75)' : 'rgba(255,255,255,0.85)';
    requestAnimationFrame(function () {
      aura.style.transition = 'transform ' + DURATION + 'ms ease,opacity ' + DURATION + 'ms ease';
      aura.style.transform = 'translate(-50%, -50%) scale(1)';
      aura.style.opacity = '0.28';
    });
  }

  function hideAura() {
    if (!aura) return;
    aura.style.transition = 'opacity 120ms ease, transform 120ms ease';
    aura.style.opacity = '0';
    aura.style.transform = 'translate(-50%, -50%) scale(0.7)';
    setTimeout(function () {
      aura.style.visibility = 'hidden';
    }, 140);
  }

  function toggle(e) {
    var x = window.innerWidth / 2;
    var y = window.innerHeight / 2;
    if (e && typeof e.clientX === 'number') {
      x = e.clientX;
      y = e.clientY;
    } else if (e && e.touches && e.touches[0]) {
      x = e.touches[0].clientX;
      y = e.touches[0].clientY;
    }
    var next = document.documentElement.classList.contains('dark') ? 'light' : 'dark';
    try { localStorage.setItem(KEY, next); } catch (err) {}
    if (reducedMotion() || !aura) {
      apply(next);
      return;
    }

    showAura(x, y, next);
    setTimeout(function () {
      apply(next);
    }, 80);
    setTimeout(hideAura, DURATION + 40);
  }

  function mount() {
    if (document.getElementById('themeFab')) return;
    createStyles();
    fab = document.createElement('button');
    fab.id = 'themeFab';
    fab.type = 'button';
    fab.setAttribute('aria-label', 'Cambiar tema claro/oscuro');
    fab.title = 'Cambiar tema claro/oscuro';
    fab.innerHTML =
      '<svg class="fab-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>' +
      '<svg class="fab-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>';
    document.body.appendChild(fab);
    aura = document.createElement('div');
    aura.id = 'themeAura';
    document.body.appendChild(aura);
    fab.addEventListener('click', toggle);
  }

  apply(current());

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
})();
