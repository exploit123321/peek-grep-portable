import React, { createContext, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Lock } from 'lucide-react';
import { HighlightTerm, pickRegexes, textTerms } from '../utils/query';

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

/** Row numbers (as shown at the left) that stay at the top under the column names (Settings > Tables). */
export const FreezeContext = createContext<ReadonlySet<number>>(new Set());

/** "1-3, 7" (the form the settings save) to the row numbers 1, 2, 3, 7. */
export function parseFrozenRows(spec: string): ReadonlySet<number> {
  const rows = new Set<number>();
  for (const part of spec.split(/[,;\s]+/)) {
    const m = /^(\d+)(?:-(\d+))?$/.exec(part);
    if (!m) continue;
    const a = Number(m[1]), b = Number(m[2] ?? m[1]);
    for (let n = Math.min(a, b); n <= Math.max(a, b) && rows.size < 100; n++) rows.add(n);
  }
  return rows;
}

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
  const [height, setHeight] = useState(600);
  const [active, setActive] = useState<{ r: number; c: number } | null>(null);
  const [draft, setDraft] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const report = useContext(HitsContext);
  const jump = useContext(JumpContext);
  const freeze = useContext(FreezeContext);

  // Frozen rows (indexes, in order) are drawn in the sticky header; the others scroll below them.
  // At most what leaves a few rows for scrolling; the rest stay in their place.
  const fit = Math.max(0, Math.floor(height / ROW_H) - 4);
  const frozen = useMemo(() => {
    if (!freeze.size || !fit) return [] as number[];
    const found = rowNumber
      ? rows.map((_, i) => i).filter(i => freeze.has(rowNumber(i)))
      : [...freeze].map(n => n - 1).filter(i => i < rows.length).sort((a, b) => a - b);
    return found.slice(0, fit);
  }, [freeze, fit, rows, rowNumber]);
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

  const scrollToCell = (r: number, c: number) => {
    const el = scrollRef.current;
    if (!el) return;
    if (!frozenSet.has(r)) el.scrollTop = Math.max(0, placeOf(r) * ROW_H - (el.clientHeight - headH) / 2 + ROW_H);
    const left = 48 + widths.slice(0, c).reduce((a, b) => a + b, 0);
    if (left < el.scrollLeft || left + widths[c] > el.scrollLeft + el.clientWidth) {
      el.scrollLeft = Math.max(0, left - el.clientWidth / 3);
    }
  };

  // New hits: go to the first one
  useEffect(() => {
    setHitIndex(0);
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
    const ro = new ResizeObserver(() => setHeight(el.clientHeight));
    ro.observe(el);
    setHeight(el.clientHeight);
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

  const totalWidth = 48 + widths.reduce((a, b) => a + b, 0);

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
          className={`sticky left-0 px-2 text-center text-fg-3 select-none ${isFrozen ? 'z-20' : ''}`}
          style={{ background: isSelected ? 'rgba(124,156,255,0.22)' : isFrozen ? 'var(--bg-elev)' : 'var(--bg)', boxShadow: edge, cursor: onSelectRow ? 'pointer' : 'default' }}
          title={isFrozen ? 'Frozen row (Settings > Tables)' : undefined}
          onClick={() => onSelectRow?.(r)}
        >
          {rowLabel ? rowLabel(r) : r + 1}
        </td>
        {columns.map((_, c) => {
          const key = `${r},${c}`;
          const value = row[c] ?? '';
          const isActive = active?.r === r && active?.c === c;
          const isLocked = locked?.has(key);
          const isCurrent = current?.[0] === r && current?.[1] === c;
          return (
            <td
              key={c}
              onClick={() => open(r, c)}
              title={isLocked ? 'Formula cell: edit it in Excel' : value.length > 40 ? value : undefined}
              className={`relative px-3 truncate ${isLocked ? 'text-fg-3 italic' : 'text-fg-2'} ${editable && !isLocked ? 'cursor-text' : ''}`}
              style={{
                borderLeft: '1px solid var(--line)',
                background: edited?.has(key) ? 'rgba(62,207,142,0.13)' : isCurrent ? 'rgba(250,204,21,0.12)' : undefined,
                boxShadow: isActive ? 'inset 0 0 0 2px var(--accent)' : isCurrent ? 'inset 0 0 0 1px rgba(250,204,21,0.7)' : edge,
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
        const top = (e.target as HTMLDivElement).scrollTop;
        requestAnimationFrame(() => setScrollTop(top));
      }}
    >
      <table className="border-collapse num text-[12.5px]" style={{ tableLayout: 'fixed', width: totalWidth }}>
        <colgroup>
          <col style={{ width: 48 }} />
          {widths.map((w, i) => <col key={i} style={{ width: w }} />)}
        </colgroup>
        <thead className="sticky top-0 z-10" style={{ background: 'var(--surface-2)' }}>
          <tr style={{ height: ROW_H }}>
            <th className="sticky left-0 z-20" style={{ background: 'var(--surface-2)', borderBottom: '1px solid var(--line-strong)' }} />
            {columns.map((col, i) => (
              <th key={i} className="px-3 text-left text-fg font-semibold truncate" style={{ borderBottom: '1px solid var(--line-strong)', borderLeft: '1px solid var(--line)' }} title={col}>
                {col}
              </th>
            ))}
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
