// Find search hits in a preview and mark them with the CSS Custom Highlight API.
// The API paints text ranges without changing the DOM, so React views stay intact.

const SKIP = new Set(['SCRIPT', 'STYLE', 'TEXTAREA', 'INPUT', 'NOSCRIPT']);
const MAX_HITS = 2000;

/** Terms to look for: the whole query, or its words when the whole query is not in the text. */
export function searchTerms(query: string): string[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const words = q.split(/\s+/).filter(w => w.length > 1);
  return [q, ...words.filter(w => w !== q)];
}

export function findHits(root: HTMLElement, query: string): Range[] {
  const terms = searchTerms(query);
  if (!terms.length) return [];

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
  const lower = text.toLowerCase();

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

  const spansOf = (list: string[]): [number, number][] => {
    const spans: [number, number][] = [];
    for (const term of list) {
      for (let i = lower.indexOf(term); i >= 0 && spans.length < MAX_HITS; i = lower.indexOf(term, i + term.length)) {
        spans.push([i, i + term.length]);
      }
    }
    return spans.sort((a, b) => a[0] - b[0]);
  };

  // The whole query first; single words only when the whole query has no hit
  let spans = spansOf([terms[0]]);
  if (!spans.length && terms.length > 1) spans = spansOf(terms.slice(1));

  return spans.map(([a, b]) => {
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
