import React, { useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { PDFDocumentProxy, TextItem } from 'pdfjs-dist/types/src/display/api';
// The legacy build: it brings what an older WebView2 lacks (e.g. Math.sumPrecise)
import workerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url';
import { HighlightTerm, pickRegexes, textTerms } from '../../utils/query';
import { clearHits, paintHits, regexSpans } from '../../utils/searchHits';
import { HitsContext, JumpContext } from '../VirtualGrid';

// PDF pages drawn by pdf.js inside the app (not the WebView2 PDF viewer, which keeps the keyboard
// and cannot be searched from here). Hits come from the text of every page, so a hit on any page
// can be counted and scrolled to; only the pages near the view are drawn.

type Pdfjs = typeof import('pdfjs-dist');
let loader: Promise<Pdfjs> | null = null;
const loadPdfjs = () =>
  (loader ??= (import('pdfjs-dist/legacy/build/pdf.mjs') as Promise<Pdfjs>).then(m => {
    m.GlobalWorkerOptions.workerSrc = workerUrl;
    return m;
  }));

const PAD = 16;
const GAP = 12;
const MAX_HITS = 20000;

interface Size { w: number; h: number }

/** The text of a page as one string, with where each text item starts and its height on the page. */
interface PageText {
  text: string;
  starts: number[];
  tops: number[];
}

interface Hit { page: number; a: number; b: number }

/** The item that holds a position of the page text. */
function itemAt(starts: number[], pos: number): number {
  let lo = 0, hi = starts.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (starts[mid] <= pos) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

const asset = (dir: string) => new URL(`pdfjs/${dir}/`, document.baseURI).href;

export const PdfPreview: React.FC<{ rawUrl: string; filename: string; terms?: HighlightTerm[]; zoom?: number }> = ({
  rawUrl, filename, terms, zoom = 1,
}) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [sizes, setSizes] = useState<Size[]>([]);
  const [texts, setTexts] = useState<(PageText | undefined)[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState({ top: 0, height: 600, width: 800 });
  const report = useContext(HitsContext);
  const jump = useContext(JumpContext);

  // Open the file, read the page sizes, then the text of every page (in the background)
  useEffect(() => {
    let cancelled = false;
    let loaded: PDFDocumentProxy | null = null;
    let loadingTask: { destroy: () => Promise<void> } | null = null;
    setDoc(null);
    setSizes([]);
    setTexts([]);
    setError(null);
    (async () => {
      const pdfjs = await loadPdfjs();
      const task = pdfjs.getDocument({
        url: rawUrl,
        cMapUrl: asset('cmaps'),
        cMapPacked: true,
        standardFontDataUrl: asset('standard_fonts'),
        iccUrl: asset('iccs'),
        wasmUrl: asset('wasm'),
      });
      loadingTask = task;
      loaded = await task.promise;
      if (cancelled) return;
      const pdf = loaded;
      const found: Size[] = [];
      for (let i = 1; i <= pdf.numPages; i++) {
        const vp = (await pdf.getPage(i)).getViewport({ scale: 1 });
        found.push({ w: vp.width, h: vp.height });
        if (cancelled) return;
      }
      setDoc(pdf);
      setSizes(found);
      const all: (PageText | undefined)[] = new Array(pdf.numPages);
      let shown = 0;
      for (let i = 0; i < pdf.numPages && !cancelled; i++) {
        const page = await pdf.getPage(i + 1);
        const vp = page.getViewport({ scale: 1 });
        const content = await page.getTextContent();
        let text = '';
        const starts: number[] = [];
        const tops: number[] = [];
        for (const item of content.items) {
          if (!('str' in item)) continue;
          const t = item as TextItem;
          starts.push(text.length);
          const [, y] = vp.convertToViewportPoint(t.transform[4], t.transform[5]);
          tops.push(y - Math.hypot(t.transform[2], t.transform[3]));
          text += t.str + (t.hasEOL ? '\n' : '');
        }
        all[i] = { text, starts, tops };
        page.cleanup();
        // Show hits while the rest is read: after the first page, then every 25 pages
        if (i === 0 || i - shown >= 25 || i === pdf.numPages - 1) {
          shown = i;
          if (!cancelled) setTexts([...all]);
        }
      }
    })().catch(e => {
      if (cancelled) return;
      const name = (e as Error)?.name;
      setError(name === 'PasswordException' ? 'This PDF has a password.' : `This PDF could not be shown (${(e as Error)?.message || e}).`);
    });
    return () => {
      cancelled = true;
      loadingTask?.destroy();
    };
  }, [rawUrl]);

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const measure = () => setView(v => ({ ...v, height: el.clientHeight, width: el.clientWidth }));
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    measure();
    return () => ro.disconnect();
  }, []);

  // Fit the widest page to the window, times the zoom of Quick Look (pages are drawn again, sharp)
  const scale = useMemo(() => {
    const widest = Math.max(1, ...sizes.map(s => s.w));
    return Math.max(0.25, Math.min(2, (view.width - PAD * 2) / widest)) * zoom;
  }, [sizes, view.width, zoom]);
  // A new scale (zoom, window size): the same place of the document stays in view
  const lastScale = useRef(scale);
  useLayoutEffect(() => {
    const el = scrollRef.current;
    const old = lastScale.current;
    lastScale.current = scale;
    if (el && old && old !== scale) {
      el.scrollTop = el.scrollTop * (scale / old);
      el.scrollLeft = el.scrollLeft * (scale / old);
    }
  }, [scale]);
  const tops = useMemo(() => {
    const out: number[] = [];
    let y = PAD;
    for (const s of sizes) {
      out.push(y);
      y += s.h * scale + GAP;
    }
    out.push(y - GAP + PAD);
    return out;
  }, [sizes, scale]);

  const first = Math.max(0, itemAt(tops, view.top) - 1);
  const last = Math.min(sizes.length - 1, itemAt(tops, view.top + view.height) + 1);

  // Hits: the same words on every page (a whole phrase, or its words if the phrase is nowhere)
  const termsKey = JSON.stringify(terms ?? []);
  const hits = useMemo(() => {
    const list = textTerms(terms ?? []);
    if (!list.length) return [] as Hit[];
    const has = (re: RegExp) => texts.some(t => {
      if (!t) return false;
      re.lastIndex = 0;
      return re.test(t.text);
    });
    const regexes = pickRegexes(list, 'text', has);
    const out: Hit[] = [];
    texts.forEach((t, page) => {
      if (!t || out.length >= MAX_HITS) return;
      for (const [a, b] of regexSpans(t.text, regexes, MAX_HITS - out.length)) out.push({ page, a, b });
    });
    return out;
  }, [texts, termsKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const [current, setCurrent] = useState(0);
  const currentRef = useRef(0);
  currentRef.current = current;

  const scrollToHit = (hit: Hit) => {
    const el = scrollRef.current;
    const t = texts[hit.page];
    if (!el || !t) return;
    const y = tops[hit.page] + (t.tops[itemAt(t.starts, hit.a)] ?? 0) * scale;
    el.scrollTop = Math.max(0, y - el.clientHeight / 3);
  };

  // New search: go to the first hit once it is found
  const jumped = useRef('');
  useEffect(() => {
    setCurrent(0);
    jumped.current = '';
  }, [termsKey, rawUrl]);
  useEffect(() => {
    if (hits.length && jump && jumped.current !== termsKey) {
      jumped.current = termsKey;
      requestAnimationFrame(() => scrollToHit(hits[0]));
    }
  }, [hits, jump, termsKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!hits.length) {
      report(null);
      return;
    }
    report({
      count: hits.length,
      index: Math.min(current, hits.length - 1),
      go: step => {
        const next = (currentRef.current + step + hits.length) % hits.length;
        currentRef.current = next;
        setCurrent(next);
        scrollToHit(hits[next]);
      },
    });
  }, [hits, current, tops]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => report(null), [report]);

  // Highlights on the drawn pages: ranges over the text layer (one span per text item)
  const layers = useRef(new Map<number, HTMLElement[]>());
  const [drawn, setDrawn] = useState(0);
  useEffect(() => {
    const ranges: Range[] = [];
    let currentRange = -1;
    hits.forEach((hit, i) => {
      const divs = layers.current.get(hit.page);
      const t = texts[hit.page];
      if (!divs || !t) return;
      const point = (pos: number, end: boolean): [Node, number] | null => {
        const k = itemAt(t.starts, pos);
        const node = divs[k]?.firstChild;
        if (!node) return null;
        const len = node.textContent?.length ?? 0;
        return [node, Math.min(len, pos - t.starts[k] + (end ? 1 : 0))];
      };
      const s = point(hit.a, false);
      const e = point(hit.b - 1, true);
      if (!s || !e) return;
      const range = document.createRange();
      try {
        range.setStart(s[0], s[1]);
        range.setEnd(e[0], e[1]);
      } catch {
        return;
      }
      if (i === current) currentRange = ranges.length;
      ranges.push(range);
    });
    if (ranges.length) paintHits(ranges, currentRange);
    else clearHits();
  }, [hits, current, drawn, texts]);
  useEffect(() => () => clearHits(), []);

  const onLayer = (page: number, divs: HTMLElement[] | null) => {
    if (divs) layers.current.set(page, divs);
    else layers.current.delete(page);
    setDrawn(n => n + 1);
  };

  const pageNumber = Math.min(sizes.length, itemAt(tops, view.top + view.height / 3) + 1);

  return (
    <div className="relative w-full h-full" style={{ background: '#1b1b22' }}>
      <div
        ref={scrollRef}
        className="absolute inset-0 overflow-auto select-text"
        onScroll={e => {
          const top = (e.target as HTMLDivElement).scrollTop;
          requestAnimationFrame(() => setView(v => (v.top === top ? v : { ...v, top })));
        }}
        aria-label={filename}
      >
        <div className="relative" style={{ height: tops[tops.length - 1] ?? 0 }}>
          {doc && sizes.slice(first, last + 1).map((s, k) => {
            const i = first + k;
            return (
              <PdfPage
                key={`${i}-${scale}`}
                doc={doc}
                index={i}
                scale={scale}
                top={tops[i]}
                left={Math.max(PAD, (view.width - s.w * scale) / 2)}
                width={s.w * scale}
                height={s.h * scale}
                onLayer={onLayer}
              />
            );
          })}
        </div>
      </div>
      {!doc && !error && (
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="w-5 h-5 rounded-full spin" style={{ border: '2px solid var(--line-strong)', borderTopColor: 'var(--accent)' }} />
        </div>
      )}
      {error && <div className="absolute inset-0 flex items-center justify-center text-[13px] text-fg-3">{error}</div>}
      {sizes.length > 0 && (
        <span className="absolute bottom-3 right-5 px-2 h-6 flex items-center rounded-md num text-[11.5px] text-fg-3 pointer-events-none" style={{ background: 'rgba(15,15,19,0.85)' }}>
          {pageNumber} / {sizes.length}
          {texts.filter(Boolean).length < sizes.length && ` · reading text ${texts.filter(Boolean).length}/${sizes.length}`}
        </span>
      )}
    </div>
  );
};

interface PdfPageProps {
  doc: PDFDocumentProxy;
  index: number;
  scale: number;
  top: number;
  left: number;
  width: number;
  height: number;
  onLayer: (page: number, divs: HTMLElement[] | null) => void;
}

/** One page: the picture on a canvas, and the text above it (invisible, but it can be selected and found). */
const PdfPage: React.FC<PdfPageProps> = ({ doc, index, scale, top, left, width, height, onLayer }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    const cleanup: (() => void)[] = [];
    (async () => {
      const pdfjs = await loadPdfjs();
      const page = await doc.getPage(index + 1);
      if (cancelled) return;
      const viewport = page.getViewport({ scale });
      const canvas = canvasRef.current!;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      const render = page.render({
        canvas,
        viewport,
        transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined,
      });
      cleanup.push(() => render.cancel());
      const layer = new pdfjs.TextLayer({ textContentSource: page.streamTextContent(), container: textRef.current!, viewport });
      cleanup.push(() => layer.cancel());
      await layer.render();
      if (cancelled) return;
      onLayer(index, layer.textDivs);
      await render.promise.catch(() => {});
    })().catch(() => {});
    return () => {
      cancelled = true;
      cleanup.forEach(f => f());
      if (textRef.current) textRef.current.textContent = '';
      onLayer(index, null);
    };
  }, [doc, index, scale]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div
      className="absolute bg-white"
      style={{
        top,
        left,
        width,
        height,
        boxShadow: '0 10px 30px -12px rgba(0,0,0,0.8)',
        ['--total-scale-factor' as string]: scale,
        ['--scale-round-x' as string]: '1px',
        ['--scale-round-y' as string]: '1px',
      }}
    >
      <canvas ref={canvasRef} className="absolute inset-0" style={{ width, height }} />
      <div ref={textRef} className="textLayer" />
    </div>
  );
};
