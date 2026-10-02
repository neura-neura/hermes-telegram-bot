/* No network requests, persistence, analytics or arbitrary redirect targets. */
(function (root) {
  'use strict';
  const valuePattern = /^(?:[A-Za-z0-9._~!$'()*;,=:@/?-]|%[0-9A-Fa-f]{2})+$/;
  function validObsidianUri(uri) {
    if (typeof uri !== 'string' || !uri.startsWith('obsidian://open?') ||
        /[^\x21-\x7e]/.test(uri) || uri.includes('...') || uri.includes('#')) return false;
    const values = new Map();
    for (const pair of uri.slice('obsidian://open?'.length).split('&')) {
      const equals = pair.indexOf('=');
      if (equals < 0) return false;
      const key = pair.slice(0, equals), value = pair.slice(equals + 1);
      if (!['vault', 'file'].includes(key) || values.has(key) || !valuePattern.test(value)) return false;
      let decoded;
      try { decoded = decodeURIComponent(value); } catch (_) { return false; }
      if (!decoded.trim() || decoded.includes('...') || decoded.includes('…') ||
          /[\x00-\x1f\x7f<>]/.test(decoded)) return false;
      values.set(key, value);
    }
    return values.size === 2 && values.has('vault') && values.has('file');
  }
  function uriFromFragment(fragment) {
    if (!fragment.startsWith('#')) return null;
    let uri;
    try { uri = decodeURIComponent(fragment.slice(1)); } catch (_) { return null; }
    return validObsidianUri(uri) ? uri : null;
  }
  function boot(win, doc) {
    const status = doc.getElementById('status'), link = doc.getElementById('open');
    const uri = uriFromFragment(win.location.hash);
    if (!uri) {
      status.textContent = 'Este enlace está incompleto o no es un enlace válido de Obsidian.';
      link.hidden = true;
      return;
    }
    // Assign the exact string, not a rebuilt URL or model-controlled HTML.
    link.setAttribute('href', uri);
    link.hidden = false;
    status.textContent = 'Intentando abrir Obsidian. Si no se abre, pulsa el botón y acepta la confirmación del navegador.';
    // Keep the manual link available: mobile browsers may require a user gesture.
    try { win.location.assign(uri); } catch (_) {
      status.textContent = 'Pulsa el botón para abrir Obsidian y acepta la confirmación del navegador.';
    }
  }
  const api = { validObsidianUri, uriFromFragment, boot };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else if (root.document) boot(root, root.document);
})(typeof window === 'undefined' ? globalThis : window);
