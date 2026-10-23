import React, { createContext, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Lock } from 'lucide-react';
import { HighlightTerm, pickRegexes, textTerms } from '../utils/query';
import { Freeze, NO_FREEZE } from '../utils/freeze';

// A table that holds all rows but draws only the visible ones, so large sheets scroll smoothly.
// Search hits come from the data, so a hit in any row can be found and scrolled to.

const ROW_H = 28;
const OVERSCAN = 12;

export interface HitReport {
  count: number;
  index: number;
  go: (step: number) => void;
}

/** Quick Look listens here for hits in table views (the DOM has only the visible rows). */
export const HitsContext = createContext<(report: HitReport | null) => void>(() => {});

/** False: new hits are marked, but the table does not scroll to the first one. */
export const JumpContext = createContext(true);

/** Rows that stay at the top and columns that stay at the left (Settings > Tables, or one file in Quick Look). */
export const FreezeContext = createContext<Freeze>(NO_FREEZE);

/** Where a table is scrolled to: the top row (its row number, or its index without numbers) and
 * the left edge. Quick Look keeps it, so preview and editor open where the other one was. */
export interface GridAnchor {
  row: number;
  left: number;
  /** The next table that opens goes here (once) */
  restore: boolean;
}
export const AnchorContext = createContext<React.MutableRefObject<GridAnchor | null> | null>(null);

/** A color over an opaque base: sticky cells must hide what scrolls below them. */
const solid = (tint: string | undefined, base: string) => (tint ? `linear-gradient(${tint}, ${tint}), ${base}` : base);

interface VirtualGridProps {
  columns: string[];
  rows: string[][];
  rowLabel?: (index: number) => React.ReactNode;
  /** The row number of a row (for frozen rows); default index + 1 */
  rowNumber?: (index: number) => number;
  terms?: HighlightTerm[];
  // Editing (optional)
  editable?: boolean;
  locked?: Set<string>;
  edited?: Set<string>;
  onEdit?: (r: number, c: number, value: string) => void;
  selectedRow?: number | null;
  onSelectRow?: (r: number) => void;
}

function columnWidths(columns: string[], rows: string[][], extra: string[][]): number[] {
  // A sample of rows (start, spread, and the rows with search hits) sets the column widths
  const base = rows.length > 400 ? [...rows.slice(0, 300), ...rows.filter((_, i) => i % Math.ceil(rows.length / 100) === 0)] : rows;
  const sample = [...base, ...extra];
  return columns.map((col, c) => {
    let chars = col.length;
    for (const row of sample) chars = Math.max(chars, (row[c] ?? '').length);
    return Math.max(72, Math.min(360, chars * 7.4 + 26));
  });
}

function splitHits(text: string, regexes: RegExp[], current: boolean): React.ReactNode {
  if (!regexes.length || !text) return text;
  const spans: [number, number][] = [];
  for (const re of regexes) {
    re.lastIndex = 0;
    for (let m = re.exec(text); m; m = re.exec(text)) {
      if (!m[0].length) { re.lastIndex++; continue; }
      spans.push([m.index, m.index + m[0].length]);
    }
  }
  if (!spans.length) return text;
  spans.sort((a, b) => a[0] - b[0]);
  const out: React.ReactNode[] = [];
  let pos = 0;
  for (const [a, b] of spans) {
    if (a < pos) continue;
    if (a > pos) out.push(text.slice(pos, a));
    out.push(<mark key={a} className={current ? 'grid-hit-current' : 'grid-hit'}>{text.slice(a, b)}</mark>);
    pos = b;
  }
  if (pos < text.length) out.push(text.slice(pos));
  return out;
}

const cellHas = (v: string, regexes: RegExp[]) => regexes.some(re => {
  re.lastIndex = 0;
  return re.test(v);
});

export const VirtualGrid: React.FC<VirtualGridProps> = ({
  columns, rows, rowLabel, rowNumber, terms, editable, locked, edited, onEdit, selectedRow, onSelectRow,
}) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [box, setBox] = useState({ width: 800, height: 600 });
  const height = box.height;
  const [active, setActive] = useState<{ r: number; c: number } | null>(null);
  const [draft, setDraft] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const report = useContext(HitsContext);
  const jump = useContext(JumpContext);
  const freeze = useContext(FreezeContext);
  const anchor = useContext(AnchorContext);
  const skipJump = useRef(false);

  // Frozen rows (indexes, in order) are drawn in the sticky header; the others scroll below them.
  // At most what leaves a few rows for scrolling; the rest stay in their place.
  const fit = Math.max(0, Math.floor(height / ROW_H) - 4);
  const frozen = useMemo(() => {
    const wanted = freeze.rows;
    if (!wanted.size || !fit) return [] as number[];
    const found = rowNumber
      ? rows.map((_, i) => i).filter(i => wanted.has(rowNumber(i)))
      : [...wanted].map(n => n - 1).filter(i => i < rows.length).sort((a, b) => a - b);
    return found.slice(0, fit);
  }, [freeze.rows, fit, rows, rowNumber]);
  const frozenSet = useMemo(() => new Set(frozen), [frozen]);
  // Place in the scrolling part <-> row index (frozen is short and sorted)
  const bodyCount = rows.length - frozen.length;
  const rowAt = (p: number) => {
    let r = p;
    for (const f of frozen) {
      if (f <= r) r++;
      else break;
    }
    return r;
  };
  const placeOf = (r: number) => r - frozen.filter(f => f < r).length;
  const headH = ROW_H * (1 + frozen.length);

  // Hits from the data: per term the whole term, or its words when the whole term has no hit
  const { hits, regexes } = useMemo(() => {
    const list = textTerms(terms ?? []);
    if (!list.length) return { hits: [] as [number, number][], regexes: [] as RegExp[] };
    const anyCell = (re: RegExp) => rows.some(row => row.some(v => !!v && cellHas(v, [re])));
    const picked = pickRegexes(list, 'text', anyCell);
    const found: [number, number][] = [];
    for (let r = 0; r < rows.length && found.length < 20000; r++) {
      const row = rows[r];
      for (let c = 0; c < row.length; c++) {
        const v = row[c];
        if (v && cellHas(v, picked)) found.push([r, c]);
      }
    }
    return { hits: found, regexes: picked };
  }, [rows, terms]);
  const [hitIndex, setHitIndex] = useState(0);
  const hitRef = useRef(0);
  hitRef.current = hitIndex;
  const widths = useMemo(
    () => columnWidths(columns, rows, hits.slice(0, 200).map(([r]) => rows[r])),
    [columns, rows, hits],
  );

  // Row numbers: as wide as the largest one
  const lastNumber = rows.length ? (rowNumber ? rowNumber(rows.length - 1) : rows.length) : 0;
  const labelW = Math.max(48, Math.ceil(String(lastNumber).length * 7.6 + 22));

  // Frozen columns come first and stay at the left; as many as leave room to scroll the others
  const { order, frozenCols, lefts, frozenW } = useMemo(() => {
    const wanted = [...freeze.cols].map(n => n - 1).filter(c => c < columns.length).sort((a, b) => a - b);
    const kept: number[] = [];
    const at = new Map<number, number>();
    let w = 0;
    for (const c of wanted) {
      if (labelW + w + widths[c] > box.width - 160) break;
      at.set(c, labelW + w);
      kept.push(c);
      w += widths[c];
    }
    return {
      order: [...kept, ...columns.map((_, c) => c).filter(c => !at.has(c))],
      frozenCols: kept,
      lefts: at,
      frozenW: w,
    };
  }, [freeze.cols, columns, widths, labelW, box.width]);
  const lastFrozenCol = frozenCols[frozenCols.length - 1];

  const scrollToCell = (r: number, c: number) => {
    const el = scrollRef.current;
    if (!el) return;
    if (!frozenSet.has(r)) el.scrollTop = Math.max(0, placeOf(r) * ROW_H - (el.clientHeight - headH) / 2 + ROW_H);
    if (lefts.has(c)) return;
    // Columns scroll in the space right of the row numbers and the frozen columns
    const fixed = labelW + frozenW;
    const pos = order.indexOf(c);
    const left = labelW + order.slice(0, pos).reduce((a, k) => a + widths[k], 0);
    if (left < el.scrollLeft + fixed || left + widths[c] > el.scrollLeft + el.clientWidth) {
      el.scrollLeft = Math.max(0, left - fixed - (el.clientWidth - fixed) / 3);
    }
  };

  // Opened from the other view (preview <-> editor): the same place, not the first hit
  const keyOf = (r: number) => (rowNumber ? rowNumber(r) : r);
  useLayoutEffect(() => {
    const el = scrollRef.current;
    const at = anchor?.current;
    if (!el || !at?.restore) return;
    at.restore = false;
    skipJump.current = true;
    let i = rowNumber ? rows.findIndex((_, k) => rowNumber(k) >= at.row) : Math.min(at.row, rows.length - 1);
    if (i < 0) i = rows.length - 1;
    el.scrollTop = frozenSet.has(i) ? 0 : placeOf(i) * ROW_H;
    el.scrollLeft = at.left;
    setScrollTop(el.scrollTop);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // New hits: go to the first one
  useEffect(() => {
    setHitIndex(0);
    if (skipJump.current) {
      skipJump.current = false;
      return;
    }
    if (hits.length && jump) requestAnimationFrame(() => scrollToCell(hits[0][0], hits[0][1]));
  }, [hits]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!hits.length) {
      report(null);
      return;
    }
    report({
      count: hits.length,
      index: hitIndex,
      go: step => {
        // From the ref: two quick presses come before this report is renewed
        const next = (hitRef.current + step + hits.length) % hits.length;
        hitRef.current = next;
        setHitIndex(next);
        scrollToCell(hits[next][0], hits[next][1]);
      },
    });
  }, [hits, hitIndex]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => report(null), [report]);

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const measure = () => setBox({ width: el.clientWidth, height: el.clientHeight });
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    measure();
    return () => ro.disconnect();
  }, []);

  useLayoutEffect(() => {
    if (active) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [active]);

  const current = hits[hitIndex];
  const start = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN);
  const end = Math.min(bodyCount, Math.ceil((scrollTop + height) / ROW_H) + OVERSCAN);

  const open = (r: number, c: number) => {
    if (!editable || locked?.has(`${r},${c}`)) return;
    setActive({ r, c });
    setDraft(rows[r]?.[c] ?? '');
  };
  const commit = (move?: [number, number]) => {
    if (!active) return;
    if ((rows[active.r]?.[active.c] ?? '') !== draft) onEdit?.(active.r, active.c, draft);
    if (move) {
      const r = Math.max(0, active.r + move[0]);
      const c = Math.max(0, Math.min(columns.length - 1, active.c + move[1]));
      if (r < rows.length) {
        open(r, c);
        scrollToCellIfNeeded(r);
        return;
      }
    }
    setActive(null);
  };
  const scrollToCellIfNeeded = (r: number) => {
    const el = scrollRef.current;
    if (!el || frozenSet.has(r)) return;
    const top = placeOf(r) * ROW_H;
    if (top < el.scrollTop) el.scrollTop = top;
    else if (top + headH + ROW_H > el.scrollTop + el.clientHeight) el.scrollTop = top + headH + ROW_H - el.clientHeight;
  };

  const totalWidth = labelW + widths.reduce((a, b) => a + b, 0);

  const renderRow = (r: number, isFrozen = false) => {
    const row = rows[r];
    const isSelected = selectedRow === r;
    // A line under the last frozen row (a border is lost in a sticky header)
    const edge = isFrozen && r === frozen[frozen.length - 1] ? 'inset 0 -2px 0 var(--line-strong)' : undefined;
    return (
      <tr
        key={r}
        style={{
          height: ROW_H,
          borderBottom: '1px solid var(--line)',
          background: isSelected ? 'var(--accent-soft)' : isFrozen ? 'var(--bg-elev)' : undefined,
        }}
        className="hover:bg-[rgba(255,255,255,0.025)]"
      >
        <td
          // Always above the cells (also the frozen columns), on an opaque background
          className="sticky left-0 z-[3] px-2 text-center text-fg-3 select-none overflow-hidden whitespace-nowrap"
          style={{
            background: solid(isSelected ? 'rgba(124,156,255,0.22)' : undefined, isFrozen ? 'var(--bg-elev)' : 'var(--bg)'),
            boxShadow: edge,
            cursor: onSelectRow ? 'pointer' : 'default',
          }}
          title={isFrozen ? 'Frozen row' : undefined}
          onClick={() => onSelectRow?.(r)}
        >
          {rowLabel ? rowLabel(r) : r + 1}
        </td>
        {order.map(c => {
          const key = `${r},${c}`;
          const value = row[c] ?? '';
          const isActive = active?.r === r && active?.c === c;
          const isLocked = locked?.has(key);
          const isCurrent = current?.[0] === r && current?.[1] === c;
          const left = lefts.get(c);
          const tint = edited?.has(key) ? 'rgba(62,207,142,0.13)' : isCurrent ? 'rgba(250,204,21,0.12)' : undefined;
          const shadows = [
            isActive ? 'inset 0 0 0 2px var(--accent)' : isCurrent ? 'inset 0 0 0 1px rgba(250,204,21,0.7)' : edge,
            c === lastFrozenCol ? 'inset -2px 0 0 var(--line-strong)' : undefined,
            // A table border does not move with a sticky cell: draw the line in the cell
            left !== undefined ? 'inset 1px 0 0 var(--line)' : undefined,
          ].filter(Boolean);
          return (
            <td
              key={c}
              onClick={() => open(r, c)}
              title={isLocked ? 'Formula cell: edit it in Excel' : value.length > 40 ? value : undefined}
              className={`relative px-3 truncate ${isLocked ? 'text-fg-3 italic' : 'text-fg-2'} ${editable && !isLocked ? 'cursor-text' : ''}`}
              style={{
                borderLeft: left !== undefined ? 'none' : '1px solid var(--line)',
                // A frozen column stays at the left, opaque, below the row numbers
                ...(left !== undefined
                  ? {
                      position: 'sticky',
                      left,
                      zIndex: 2,
                      background: solid(tint ?? (isSelected ? 'var(--accent-soft)' : undefined), isFrozen ? 'var(--bg-elev)' : 'var(--bg)'),
                    }
                  : { background: tint }),
                boxShadow: shadows.join(', ') || undefined,
              }}
            >
              {isActive ? (
                <input
                  ref={inputRef}
                  value={draft}
                  onChange={e => setDraft(e.target.value)}
                  onBlur={() => commit()}
                  onKeyDown={e => {
                    e.stopPropagation();
                    if (e.key === 'Enter') { e.preventDefault(); commit([e.shiftKey ? -1 : 1, 0]); }
                    else if (e.key === 'Tab') { e.preventDefault(); commit([0, e.shiftKey ? -1 : 1]); }
                    else if (e.key === 'Escape') { e.preventDefault(); setActive(null); }
                  }}
                  className="absolute inset-0 w-full px-3 bg-[#101016] text-fg outline-none num text-[12.5px]"
                />
              ) : (
                <>
                  {isLocked && <Lock className="inline w-3 h-3 mr-1 -mt-0.5 opacity-60" />}
                  {regexes.length ? splitHits(value, regexes, isCurrent) : value}
                </>
              )}
            </td>
          );
        })}
      </tr>
    );
  };

  return (
    <div
      ref={scrollRef}
      className="h-full overflow-auto select-text"
      onScroll={e => {
        const el = e.target as HTMLDivElement;
        const top = el.scrollTop;
        requestAnimationFrame(() => setScrollTop(top));
        if (anchor && rows.length) {
          const r = rowAt(Math.min(bodyCount - 1, Math.floor(top / ROW_H)));
          anchor.current = { row: keyOf(Math.min(r, rows.length - 1)), left: el.scrollLeft, restore: false };
        }
      }}
    >
      <table className="border-collapse num text-[12.5px]" style={{ tableLayout: 'fixed', width: totalWidth }}>
        <colgroup>
          <col style={{ width: labelW }} />
          {order.map(c => <col key={c} style={{ width: widths[c] }} />)}
        </colgroup>
        <thead className="sticky top-0 z-10" style={{ background: 'var(--surface-2)' }}>
          <tr style={{ height: ROW_H }}>
            <th className="sticky left-0 z-[3]" style={{ background: 'var(--surface-2)', borderBottom: '1px solid var(--line-strong)' }} />
            {order.map(c => {
              const left = lefts.get(c);
              return (
                <th
                  key={c}
                  className="px-3 text-left text-fg font-semibold truncate"
                  style={{
                    borderBottom: '1px solid var(--line-strong)',
                    borderLeft: left !== undefined ? 'none' : '1px solid var(--line)',
                    ...(left !== undefined ? { position: 'sticky', left, zIndex: 2, background: 'var(--surface-2)' } : {}),
                    boxShadow: [
                      c === lastFrozenCol ? 'inset -2px 0 0 var(--line-strong)' : '',
                      left !== undefined ? 'inset 1px 0 0 var(--line)' : '',
                    ].filter(Boolean).join(', ') || undefined,
                  }}
                  title={left !== undefined ? `${columns[c]} (frozen column)` : columns[c]}
                >
                  {columns[c]}
                </th>
              );
            })}
          </tr>
          {frozen.map(r => renderRow(r, true))}
        </thead>
        <tbody>
          {start > 0 && <tr style={{ height: start * ROW_H }} />}
          {Array.from({ length: Math.max(0, end - start) }, (_, k) => renderRow(rowAt(start + k)))}
          {end < bodyCount && <tr style={{ height: (bodyCount - end) * ROW_H }} />}
        </tbody>
      </table>
    </div>
  );
};
