import rough from 'roughjs';
import type { Options } from 'roughjs/bin/core';

const ROUGHNESS = 0.8;
const BOWING = 1;
const SEED = 42;
const VIEWBOX_PAD = 6;

function parseNum(v: string | null): number {
  return v ? parseFloat(v) : 0;
}

function getStroke(el: Element): string {
  return el.getAttribute('stroke') || '#e4e4e7';
}

function getStrokeWidth(el: Element): number {
  return parseNum(el.getAttribute('stroke-width')) || 1.5;
}

function getFill(el: Element): string {
  const f = el.getAttribute('fill');
  return f && f !== 'none' ? f : '';
}

function getOpacity(el: Element): string {
  return el.getAttribute('opacity') || el.getAttribute('stroke-opacity') || '';
}

function baseOpts(el: Element, seed: number): Options {
  const fill = getFill(el);
  const opts: Options = {
    roughness: ROUGHNESS,
    bowing: BOWING,
    seed,
    stroke: getStroke(el),
    strokeWidth: getStrokeWidth(el),
    preserveVertices: true,
    strokeLineDash: [],
  };
  if (fill) {
    opts.fill = fill;
    opts.fillStyle = 'hachure';
    opts.hachureAngle = -41;
    opts.hachureGap = Math.max(getStrokeWidth(el) * 4, 6);
    opts.fillWeight = getStrokeWidth(el) / 2;
  }
  const da = el.getAttribute('stroke-dasharray');
  if (da) {
    opts.strokeLineDash = da.split(/[\s,]+/).map(Number);
    opts.disableMultiStroke = true;
  }
  return opts;
}

function transferMarkers(from: Element, to: SVGElement) {
  for (const attr of ['marker-start', 'marker-mid', 'marker-end']) {
    const v = from.getAttribute(attr);
    if (v) {
      const paths = to.querySelectorAll('path');
      if (paths.length > 0) {
        paths[0].setAttribute(attr, v);
      }
    }
  }
}

function applyAttrs(drawn: SVGElement, el: Element) {
  const opacity = getOpacity(el);
  const transform = el.getAttribute('transform');
  if (opacity) drawn.setAttribute('opacity', opacity);
  if (transform) drawn.setAttribute('transform', transform);
  transferMarkers(el, drawn);
}

export function sketchifySvg(svgEl: SVGSVGElement): SVGSVGElement {
  const clone = svgEl.cloneNode(true) as SVGSVGElement;
  const rc = rough.svg(clone);
  let seedCounter = SEED;

  const vb = clone.viewBox?.baseVal;
  if (vb && vb.width > 0) {
    clone.setAttribute('viewBox',
      `${vb.x - VIEWBOX_PAD} ${vb.y - VIEWBOX_PAD} ${vb.width + VIEWBOX_PAD * 2} ${vb.height + VIEWBOX_PAD * 2}`
    );
  }

  const shapes = clone.querySelectorAll('rect, line, circle, ellipse, polygon, polyline');

  shapes.forEach(el => {
    if (el.closest('defs') || el.closest('.svg-toolbar') || el.closest('marker')) return;
    const tag = el.tagName.toLowerCase();
    const parent = el.parentNode;
    if (!parent) return;

    const seed = seedCounter++;
    const opts = baseOpts(el, seed);
    let drawn: SVGGElement | null = null;

    try {
      if (tag === 'rect') {
        const x = parseNum(el.getAttribute('x'));
        const y = parseNum(el.getAttribute('y'));
        const w = parseNum(el.getAttribute('width'));
        const h = parseNum(el.getAttribute('height'));
        if (w > 0 && h > 0) drawn = rc.rectangle(x, y, w, h, opts);
      } else if (tag === 'line') {
        const x1 = parseNum(el.getAttribute('x1'));
        const y1 = parseNum(el.getAttribute('y1'));
        const x2 = parseNum(el.getAttribute('x2'));
        const y2 = parseNum(el.getAttribute('y2'));
        drawn = rc.line(x1, y1, x2, y2, opts);
      } else if (tag === 'circle') {
        const cx = parseNum(el.getAttribute('cx'));
        const cy = parseNum(el.getAttribute('cy'));
        const r = parseNum(el.getAttribute('r'));
        if (r > 0) drawn = rc.circle(cx, cy, r * 2, opts);
      } else if (tag === 'ellipse') {
        const cx = parseNum(el.getAttribute('cx'));
        const cy = parseNum(el.getAttribute('cy'));
        const rx = parseNum(el.getAttribute('rx'));
        const ry = parseNum(el.getAttribute('ry'));
        if (rx > 0 && ry > 0) drawn = rc.ellipse(cx, cy, rx * 2, ry * 2, opts);
      } else if (tag === 'polygon') {
        const pts = el.getAttribute('points');
        if (pts) {
          const points = pts.trim().split(/[\s,]+/);
          const pairs: [number, number][] = [];
          for (let i = 0; i < points.length - 1; i += 2) {
            pairs.push([parseFloat(points[i]), parseFloat(points[i + 1])]);
          }
          if (pairs.length >= 3) drawn = rc.polygon(pairs, opts);
        }
      } else if (tag === 'polyline') {
        const pts = el.getAttribute('points');
        if (pts) {
          const points = pts.trim().split(/[\s,]+/);
          const pairs: [number, number][] = [];
          for (let i = 0; i < points.length - 1; i += 2) {
            pairs.push([parseFloat(points[i]), parseFloat(points[i + 1])]);
          }
          if (pairs.length >= 2) drawn = rc.linearPath(pairs, opts);
        }
      }
    } catch {
      return;
    }

    if (drawn) {
      applyAttrs(drawn, el);
      parent.replaceChild(drawn, el);
    }
  });

  clone.querySelectorAll('text').forEach(t => {
    t.setAttribute('font-family', "'Caveat', 'Segoe Print', cursive");
    const size = parseNum(t.getAttribute('font-size'));
    if (size) t.setAttribute('font-size', String(Math.round(size * 1.3)));
  });

  clone.style.setProperty('stroke-linecap', 'round');
  clone.style.setProperty('stroke-linejoin', 'round');

  return clone;
}
