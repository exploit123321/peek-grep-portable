// Find search hits in a preview and mark them with the CSS Custom Highlight API.
// The API paints text ranges without changing the DOM, so React views stay intact.
// Terms come from the parsed search (wildcards, "+" parts, literals) or from "find in preview".

import { HighlightTerm, pickRegexes, textTerms } from './query';

const SKIP = new Set(['SCRIPT', 'STYLE', 'TEXTAREA', 'INPUT', 'NOSCRIPT']);
const MAX_HITS = 5000;

/** Hit spans [start, end) of the terms in a text, sorted, without overlaps. */
export function textSpans(text: string, terms: HighlightTerm[], limit = MAX_HITS): [number, number][] {
  const regexes = pickRegexes(textTerms(terms), 'text', re => {
    re.lastIndex = 0;
    return re.test(text);
  });
  const spans: [number, number][] = [];
  for (const re of regexes) {
    re.lastIndex = 0;
    for (let m = re.exec(text); m && spans.length < limit; m = re.exec(text)) {
      if (m[0].length === 0) {
        re.lastIndex++;
        continue;
      }
      spans.push([m.index, m.index + m[0].length]);
    }
  }
  spans.sort((a, b) => a[0] - b[0] || b[1] - a[1]);
  const merged: [number, number][] = [];
  for (const s of spans) {
    const last = merged[merged.length - 1];
    if (last && s[0] < last[1]) last[1] = Math.max(last[1], s[1]);
    else merged.push([s[0], s[1]]);
  }
  return merged;
}

export function findHits(root: HTMLElement, terms: HighlightTerm[]): Range[] {
  if (!textTerms(terms).length) return [];

  const nodes: Text[] = [];
  const starts: number[] = [];
  let text = '';
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: n => (n.parentElement && SKIP.has(n.parentElement.tagName) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    nodes.push(n as Text);
    starts.push(text.length);
    text += (n as Text).data;
  }

  // Map an offset in the joined text back to (node, offset)
  const locate = (pos: number): [Text, number] => {
    let lo = 0, hi = starts.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (starts[mid] <= pos) lo = mid;
      else hi = mid - 1;
    }
    return [nodes[lo], pos - starts[lo]];
  };

  return textSpans(text, terms).map(([a, b]) => {
    const range = document.createRange();
    const [sn, so] = locate(a);
    const [en, eo] = locate(b - 1);
    range.setStart(sn, so);
    range.setEnd(en, eo + 1);
    return range;
  });
}

type HighlightRegistry = { set: (name: string, h: unknown) => void; delete: (name: string) => void };

function registry(): HighlightRegistry | null {
  const css = (window as unknown as { CSS?: { highlights?: HighlightRegistry } }).CSS;
  return css?.highlights ?? null;
}

export function paintHits(ranges: Range[], current: number): void {
  const reg = registry();
  const Highlight = (window as unknown as { Highlight?: new (...r: Range[]) => unknown }).Highlight;
  if (!reg || !Highlight) return;
  reg.set('pg-hit', new Highlight(...ranges));
  if (ranges[current]) reg.set('pg-hit-current', new Highlight(ranges[current]));
  else reg.delete('pg-hit-current');
}

export function clearHits(): void {
  const reg = registry();
  reg?.delete('pg-hit');
  reg?.delete('pg-hit-current');
}

/** Scroll the scrolling ancestors so that the range is in the middle of the view. */
export function revealRange(range: Range): void {
  const el = range.startContainer.parentElement;
  if (!el) return;
  el.scrollIntoView({ block: 'center', inline: 'nearest' });
  // Wide lines (code, tables): also bring the hit itself into view horizontally
  const box = range.getBoundingClientRect();
  let scroller: HTMLElement | null = el;
  while (scroller && scroller.scrollWidth <= scroller.clientWidth) scroller = scroller.parentElement;
  if (scroller) {
    const outer = scroller.getBoundingClientRect();
    if (box.left < outer.left || box.right > outer.right) {
      scroller.scrollLeft += box.left - outer.left - outer.width / 3;
    }
  }
}
