/* Bounded renderer: parses Markdown before escaping and never processes generated HTML again. */
(function (global) {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  function safeUrl(value) {
    if (typeof value !== 'string' || /[\s\u0000-\u001f\u007f]/.test(value)) return '';
    try {
      const u = new URL(value);
      return ['https:', 'http:'].includes(u.protocol) && !u.username && !u.password ? u.href : '';
    } catch { return ''; }
  }
  const link = (text, url) => {
    const safe = safeUrl(url);
    return safe ? `<a href="${esc(safe)}" target="_blank" rel="noopener noreferrer">${esc(text)}</a>` : esc(text);
  };
  function inline(text) {
    const pattern = /`([^`\n]+)`|\[([^\]\n]+)\]\(([^\s)]+)\)|https?:\/\/[^\s<>]+|\*\*([^*\n]+)\*\*|\*([^*\n]+)\*/g;
    let html = '', start = 0, m;
    while ((m = pattern.exec(text))) {
      html += esc(text.slice(start, m.index));
      if (m[1] !== undefined) html += `<code>${esc(m[1])}</code>`;
      else if (m[2] !== undefined) html += link(m[2], m[3]);
      else if (m[4] !== undefined) html += `<b>${esc(m[4])}</b>`;
      else if (m[5] !== undefined) html += `<i>${esc(m[5])}</i>`;
      else {
        let url = m[0], tail = '';
        while (/[.,;:!?]$/.test(url) || (url.endsWith(')') && (url.match(/\)/g) || []).length > (url.match(/\(/g) || []).length)) {
          tail = url.slice(-1) + tail; url = url.slice(0, -1);
        }
        html += link(url, url) + esc(tail);
      }
      start = pattern.lastIndex;
    }
    return html + esc(text.slice(start));
  }
  function render(text) {
    const lines = String(text ?? '').split('\n');
    let html = '', list = '', paragraph = [], code = null;
    const closeP = () => { if (paragraph.length) { html += `<p>${inline(paragraph.join(' '))}</p>`; paragraph = []; } };
    const closeL = () => { if (list) { html += `</${list}>`; list = ''; } };
    for (const raw of lines) {
      const l = raw.trimEnd();
      if (/^\s*```/.test(l)) {
        closeP(); closeL();
        if (code === null) code = []; else { html += `<pre><code>${esc(code.join('\n'))}</code></pre>`; code = null; }
        continue;
      }
      if (code !== null) { code.push(raw); continue; }
      if (!l.trim()) { closeP(); closeL(); continue; }
      let m;
      if ((m = l.match(/^(#{1,3})\s+(.*)$/))) { closeP(); closeL(); html += `<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`; continue; }
      if (/^(-{3,}|\*{3,})$/.test(l.trim())) { closeP(); closeL(); html += '<hr>'; continue; }
      if ((m = l.match(/^\s*[-*•]\s+(.*)$/))) { closeP(); if (list !== 'ul') { closeL(); html += '<ul>'; list = 'ul'; } html += `<li>${inline(m[1])}</li>`; continue; }
      if ((m = l.match(/^\s*\d+[.)]\s+(.*)$/))) { closeP(); if (list !== 'ol') { closeL(); html += '<ol>'; list = 'ol'; } html += `<li>${inline(m[1])}</li>`; continue; }
      if ((m = l.match(/^>\s?(.*)$/))) { closeP(); closeL(); html += `<blockquote>${inline(m[1])}</blockquote>`; continue; }
      closeL(); paragraph.push(l.trim());
    }
    closeP(); closeL();
    if (code !== null) html += `<pre><code>${esc(code.join('\n'))}</code></pre>`;
    return html;
  }
  global.SafeMarkdown = Object.freeze({render, safeUrl});
})(globalThis);
