import { esc } from '@/lib/utils';

function sanitizeSVG(raw: string): string {
  let s = raw;
  s = s.replace(/<script[\s\S]*?<\/script>/gi, '');
  s = s.replace(/\s+on\w+\s*=\s*"[^"]*"/gi, '');
  s = s.replace(/\s+on\w+\s*=\s*'[^']*'/gi, '');
  s = s.replace(/<foreignObject[\s\S]*?<\/foreignObject>/gi, '');
  s = s.replace(/href\s*=\s*"javascript:[^"]*"/gi, 'href=""');
  s = s.replace(/href\s*=\s*'javascript:[^']*'/gi, "href=''");
  return s;
}

/**
 * Line-by-line markdown renderer for chat messages.
 * Streaming-safe: can be called repeatedly as text grows.
 * Security: validates link URLs to block javascript: scheme.
 */
export function renderChatMD(text: string): string {
  const raw = text.replace(/^\n+/, '').replace(/\n+$/, '');
  const lines = raw.split('\n');
  const out: string[] = [];
  let inCode = false;
  let codeLang = '';
  let codeLines: string[] = [];
  let listBuf: string[] = [];
  let tableBuf: string[] = [];

  function flushList() {
    if (listBuf.length) {
      out.push('<ul>' + listBuf.join('') + '</ul>');
      listBuf = [];
    }
  }

  function flushTable() {
    if (tableBuf.length < 2) {
      // Not enough lines for a table (need header + separator at minimum)
      for (const tl of tableBuf) out.push(inlineFmt(tl));
      tableBuf = [];
      return;
    }
    // Check if second line is a separator (e.g. |---|---|)
    const sepLine = tableBuf[1].trim();
    if (!/^\|[-\s|:]+\|$/.test(sepLine)) {
      for (const tl of tableBuf) out.push(inlineFmt(tl));
      tableBuf = [];
      return;
    }
    const parseRow = (row: string) =>
      row.replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());

    const headers = parseRow(tableBuf[0]);
    const dataRows = tableBuf.slice(2);

    let html = '<div class="chat-table-wrap"><table class="chat-table"><thead><tr>';
    for (const h of headers) html += `<th>${inlineFmt(h)}</th>`;
    html += '</tr></thead><tbody>';
    for (const row of dataRows) {
      const cells = parseRow(row);
      html += '<tr>';
      for (let c = 0; c < headers.length; c++) {
        html += `<td>${inlineFmt(cells[c] ?? '')}</td>`;
      }
      html += '</tr>';
    }
    html += '</tbody></table></div>';
    out.push(html);
    tableBuf = [];
  }

  function inlineFmt(line: string): string {
    let s = esc(line);
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    // Allow safe HTML tags (e.g. Telegram <b>, <i>, <br> formatting)
    // esc() already escaped them, so we convert escaped forms back to real HTML.
    // Inner content is already escaped, so no XSS risk.
    s = s.replace(/&lt;b&gt;(.*?)&lt;\/b&gt;/g, '<strong>$1</strong>');
    s = s.replace(/&lt;i&gt;(.*?)&lt;\/i&gt;/g, '<em>$1</em>');
    s = s.replace(/&lt;br\s*\/?&gt;/g, '<br>');
    // Links with scheme validation - only allow http/https
    s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_match, label: string, url: string) => {
      const trimmed = url.trim().toLowerCase();
      if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) {
        return `<a href="${url}" target="_blank" style="color:var(--blue)">${label}</a>`;
      }
      // Block potentially dangerous URLs
      return `${label} (${esc(url)})`;
    });
    // Auto-linkify bare URLs. Skip URLs that are already inside an href or
    // rendered as the inner text of an <a>. The prefix char must not be one
    // that shows up inside an anchor we just produced (= " ' > ).
    s = s.replace(
      /(^|[^"'>=/])(https?:\/\/[^\s<)"']+[^\s<)"'.,;:!?])/g,
      (_m, pre: string, url: string) =>
        `${pre}<a href="${url}" target="_blank" style="color:var(--blue)">${url}</a>`
    );
    // MyBrain paths in inline code -> Obsidian deeplink.
    // Matches <code>~/Documents/MyBrain/<rest></code> (rest is already escaped).
    s = s.replace(
      /<code>~\/Documents\/MyBrain\/([^<]+)<\/code>/g,
      (_m, rest: string) => {
        const trimmed = rest.replace(/\.md$/, '');
        const encoded = encodeURIComponent(trimmed);
        return `<a href="obsidian://open?vault=MyBrain&file=${encoded}" style="color:var(--blue)" title="Open in Obsidian"><code>~/Documents/MyBrain/${rest}</code></a>`;
      }
    );
    return s;
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Code fence toggle
    if (line.startsWith('```')) {
      if (!inCode) {
        flushList();
        inCode = true;
        codeLang = line.slice(3).trim();
        codeLines = [];
      } else {
        if (codeLang === 'svg') {
          out.push(`<div class="chat-svg-block"><div class="svg-toolbar"><button class="svg-copy-img" title="Copy as image"><svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="1.5" y="2.5" width="13" height="11" rx="1.5"/><circle cx="5.5" cy="6.5" r="1.5"/><path d="M1.5 11l3.5-3.5 2.5 2.5 3-3.5 4 4.5"/></svg></button><button class="svg-copy-src" title="Copy SVG source"><svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M5.5 4L2 8l3.5 4"/><path d="M10.5 4L14 8l-3.5 4"/></svg></button><button class="svg-style-toggle" title="Toggle sketch style"><svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M1 8c1.5-3 3-3 4.5 0s3 3 4.5 0 3-3 4.5 0"/></svg></button></div>${sanitizeSVG(codeLines.join('\n'))}</div>`);
        } else {
          const langLabel = codeLang
            ? `<span class="chat-code-lang">${esc(codeLang)}</span>`
            : '';
          out.push(
            `<div class="chat-code-block">${langLabel}<pre><code>${esc(codeLines.join('\n'))}</code></pre></div>`
          );
        }
        inCode = false;
        codeLang = '';
      }
      continue;
    }

    if (inCode) {
      codeLines.push(line);
      continue;
    }

    // Table rows (lines starting with |)
    if (/^\|.+\|/.test(line.trim())) {
      flushList();
      tableBuf.push(line);
      continue;
    }
    flushTable();

    // Headings
    if (line.startsWith('### ')) {
      flushList();
      out.push(`<h3>${inlineFmt(line.slice(4))}</h3>`);
      continue;
    }
    if (line.startsWith('## ')) {
      flushList();
      out.push(`<h2>${inlineFmt(line.slice(3))}</h2>`);
      continue;
    }
    if (line.startsWith('# ')) {
      flushList();
      out.push(`<h2>${inlineFmt(line.slice(2))}</h2>`);
      continue;
    }

    // List items
    if (/^[-*] /.test(line)) {
      listBuf.push(`<li>${inlineFmt(line.slice(2))}</li>`);
      continue;
    }
    if (/^\d+\. /.test(line)) {
      listBuf.push(`<li>${inlineFmt(line.replace(/^\d+\.\s*/, ''))}</li>`);
      continue;
    }

    // Non-list line
    flushList();

    if (line.trim() === '') {
      out.push('<br>');
    } else {
      out.push(inlineFmt(line));
      // Add <br> unless next line is a block element
      const next = lines[i + 1];
      if (
        next !== undefined &&
        !next.startsWith('#') &&
        !next.startsWith('```') &&
        next.trim() !== ''
      ) {
        out.push('<br>');
      }
    }
  }

  // Flush remaining
  if (inCode && codeLines.length) {
    if (codeLang === 'svg') {
      out.push(`<div class="chat-svg-block"><div class="svg-toolbar"><button class="svg-copy-img" title="Copy as image"><svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="1.5" y="2.5" width="13" height="11" rx="1.5"/><circle cx="5.5" cy="6.5" r="1.5"/><path d="M1.5 11l3.5-3.5 2.5 2.5 3-3.5 4 4.5"/></svg></button><button class="svg-copy-src" title="Copy SVG source"><svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M5.5 4L2 8l3.5 4"/><path d="M10.5 4L14 8l-3.5 4"/></svg></button><button class="svg-style-toggle" title="Toggle sketch style"><svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M1 8c1.5-3 3-3 4.5 0s3 3 4.5 0 3-3 4.5 0"/></svg></button></div>${sanitizeSVG(codeLines.join('\n'))}</div>`);
    } else {
      const langLabel = codeLang
        ? `<span class="chat-code-lang">${esc(codeLang)}</span>`
        : '';
      out.push(
        `<div class="chat-code-block">${langLabel}<pre><code>${esc(codeLines.join('\n'))}</code></pre></div>`
      );
    }
  }
  flushTable();
  flushList();

  return out.join('');
}
