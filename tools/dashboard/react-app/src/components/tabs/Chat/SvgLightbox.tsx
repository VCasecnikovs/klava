import { useState, useEffect, useCallback, useRef } from 'react';
import { sketchifySvg } from './sketchify';

const LS_KEY = 'svg-sketch-mode';

function getMainSvg(block: Element): SVGSVGElement | null {
  const all = block.querySelectorAll(':scope > svg');
  for (const el of all) {
    if (el.closest('.svg-toolbar')) continue;
    return el as SVGSVGElement;
  }
  return block.querySelector('svg:not(.svg-toolbar svg)') as SVGSVGElement | null;
}

function applySketchToBlock(block: Element, on: boolean) {
  const svg = getMainSvg(block);
  if (!svg) return;

  if (on) {
    if (block.getAttribute('data-has-sketch')) {
      (block.querySelector('.svg-sketch-layer') as HTMLElement)!.style.display = '';
      svg.style.display = 'none';
    } else {
      const sketchy = sketchifySvg(svg);
      sketchy.classList.add('svg-sketch-layer');
      svg.style.display = 'none';
      svg.after(sketchy);
      block.setAttribute('data-has-sketch', '1');
    }
  } else {
    svg.style.display = '';
    const sketch = block.querySelector('.svg-sketch-layer') as HTMLElement;
    if (sketch) sketch.style.display = 'none';
  }
}

function applySketchAll(on: boolean) {
  document.querySelectorAll('.chat-svg-block[data-svg-lb]').forEach(block => {
    applySketchToBlock(block, on);
  });
}

let _fontCache: string | null = null;
async function getCaveatFontCSS(): Promise<string> {
  if (_fontCache) return _fontCache;
  try {
    const res = await fetch('https://fonts.googleapis.com/css2?family=Caveat:wght@400;600&display=swap');
    const css = await res.text();
    const woff2Urls = [...css.matchAll(/url\((https:\/\/[^)]+\.woff2)\)/g)];
    let inlined = css;
    for (const m of woff2Urls) {
      const fontRes = await fetch(m[1]);
      const buf = await fontRes.arrayBuffer();
      const b64 = btoa(String.fromCharCode(...new Uint8Array(buf)));
      inlined = inlined.replace(m[1], `data:font/woff2;base64,${b64}`);
    }
    _fontCache = inlined;
    return inlined;
  } catch {
    return '';
  }
}

async function copyAsImage(svg: SVGSVGElement, btn: HTMLElement) {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  const vb = svg.viewBox?.baseVal;
  const w = vb?.width || svg.clientWidth || 800;
  const h = vb?.height || svg.clientHeight || 600;
  const scale = 2;
  clone.setAttribute('width', String(w));
  clone.setAttribute('height', String(h));
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');

  const fontCSS = await getCaveatFontCSS();
  if (fontCSS) {
    let defs = clone.querySelector('defs');
    if (!defs) {
      defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
      clone.prepend(defs);
    }
    const style = document.createElementNS('http://www.w3.org/2000/svg', 'style');
    style.textContent = fontCSS;
    defs.appendChild(style);
  }

  const data = new XMLSerializer().serializeToString(clone);
  const blob = new Blob([data], { type: 'image/svg+xml;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const img = new Image();
  img.onload = () => {
    const canvas = document.createElement('canvas');
    canvas.width = w * scale;
    canvas.height = h * scale;
    const ctx = canvas.getContext('2d')!;
    ctx.fillStyle = '#0d0d10';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.scale(scale, scale);
    ctx.drawImage(img, 0, 0, w, h);
    URL.revokeObjectURL(url);
    canvas.toBlob(pngBlob => {
      if (pngBlob) {
        navigator.clipboard.write([new ClipboardItem({ 'image/png': pngBlob })]).then(() => {
          btn.classList.add('copied');
          setTimeout(() => btn.classList.remove('copied'), 1500);
        });
      }
    }, 'image/png');
  };
  img.onerror = () => URL.revokeObjectURL(url);
  img.src = url;
}

export function SvgLightbox() {
  const [svgHtml, setSvgHtml] = useState<string | null>(null);
  const [sketchy, setSketchy] = useState(() => localStorage.getItem(LS_KEY) === '1');
  const [scale, setScale] = useState(1);
  const [translate, setTranslate] = useState({ x: 0, y: 0 });
  const dragging = useRef(false);
  const dragStart = useRef({ x: 0, y: 0 });
  const translateStart = useRef({ x: 0, y: 0 });

  useEffect(() => {
    function attachHandlers() {
      document.querySelectorAll('.chat-svg-block').forEach(block => {
        if (block.getAttribute('data-svg-lb')) return;
        block.setAttribute('data-svg-lb', '1');

        if (localStorage.getItem(LS_KEY) === '1') {
          applySketchToBlock(block, true);
        }

        block.addEventListener('click', (e) => {
          if ((e.target as HTMLElement).closest('.svg-toolbar')) return;
          const html = block.innerHTML;
          if (html && html.length > 10) {
            setSvgHtml(html);
            setScale(1);
            setTranslate({ x: 0, y: 0 });
          }
        });

        const toggle = block.querySelector('.svg-style-toggle');
        if (toggle && !toggle.getAttribute('data-bound')) {
          toggle.setAttribute('data-bound', '1');
          toggle.addEventListener('click', (e) => {
            e.stopPropagation();
            const next = localStorage.getItem(LS_KEY) !== '1';
            localStorage.setItem(LS_KEY, next ? '1' : '0');
            setSketchy(next);
            applySketchAll(next);
          });
        }

        const copyImg = block.querySelector('.svg-copy-img');
        if (copyImg && !copyImg.getAttribute('data-bound')) {
          copyImg.setAttribute('data-bound', '1');
          copyImg.addEventListener('click', (e) => {
            e.stopPropagation();
            const visibleSvg = (block.querySelector('.svg-sketch-layer:not([style*="display: none"])') ||
              getMainSvg(block)) as SVGSVGElement | null;
            if (visibleSvg) copyAsImage(visibleSvg, e.currentTarget as HTMLElement);
          });
        }

        const copySrc = block.querySelector('.svg-copy-src');
        if (copySrc && !copySrc.getAttribute('data-bound')) {
          copySrc.setAttribute('data-bound', '1');
          copySrc.addEventListener('click', (e) => {
            e.stopPropagation();
            const svg = getMainSvg(block);
            if (svg) {
              navigator.clipboard.writeText(svg.outerHTML).then(() => {
                const btn = e.currentTarget as HTMLElement;
                btn.classList.add('copied');
                setTimeout(() => btn.classList.remove('copied'), 1500);
              });
            }
          });
        }
      });
    }

    attachHandlers();
    const observer = new MutationObserver(() => attachHandlers());
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);

  const close = useCallback(() => setSvgHtml(null), []);

  useEffect(() => {
    if (!svgHtml) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
      if (e.key === '+' || e.key === '=') setScale(s => Math.min(s * 1.3, 8));
      if (e.key === '-') setScale(s => Math.max(s / 1.3, 0.2));
      if (e.key === '0') { setScale(1); setTranslate({ x: 0, y: 0 }); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [svgHtml, close]);

  const onWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    setScale(s => Math.min(Math.max(s * factor, 0.2), 8));
  }, []);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest?.('.svg-lb-controls')) return;
    dragging.current = true;
    dragStart.current = { x: e.clientX, y: e.clientY };
    translateStart.current = { ...translate };
  }, [translate]);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragging.current) return;
    setTranslate({
      x: translateStart.current.x + (e.clientX - dragStart.current.x),
      y: translateStart.current.y + (e.clientY - dragStart.current.y),
    });
  }, []);

  const onPointerUp = useCallback(() => { dragging.current = false; }, []);

  if (!svgHtml) return null;

  return (
    <div
      className={`svg-lb-overlay${sketchy ? ' sketchy' : ''}`}
      onWheel={onWheel}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
    >
      <div className="svg-lb-controls">
        <button onClick={() => setScale(s => Math.min(s * 1.3, 8))} title="Zoom in (+)">+</button>
        <span className="svg-lb-scale">{Math.round(scale * 100)}%</span>
        <button onClick={() => setScale(s => Math.max(s / 1.3, 0.2))} title="Zoom out (-)">-</button>
        <button onClick={() => { setScale(1); setTranslate({ x: 0, y: 0 }); }} title="Reset (0)">Fit</button>
        <button onClick={close} title="Close (Esc)">✕</button>
      </div>
      <div
        className="svg-lb-content"
        style={{ transform: `translate(${translate.x}px, ${translate.y}px) scale(${scale})` }}
        dangerouslySetInnerHTML={{ __html: svgHtml }}
      />
      <div className="svg-lb-backdrop" onClick={close} />
    </div>
  );
}
