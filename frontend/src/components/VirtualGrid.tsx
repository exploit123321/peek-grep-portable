import React, { createContext, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Lock } from 'lucide-react';
import { searchTerms } from '../utils/searchHits';

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

interface VirtualGridProps {
  columns: string[];
  rows: string[][];
  rowLabel?: (index: number) => React.ReactNode;
  query?: string;
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

function splitHits(text: string, terms: string[], current: boolean): React.ReactNode {
  if (!terms.length || !text) return text;
  const lower = text.toLowerCase();
  const out: React.ReactNode[] = [];
  let pos = 0;
  while (pos < text.length) {
    let best = -1, len = 0;
    for (const t of terms) {
      const i = lower.indexOf(t, pos);
      if (i >= 0 && (best < 0 || i < best)) { best = i; len = t.length; }
    }
    if (best < 0) break;
    if (best > pos) out.push(text.slice(pos, best));
    out.push(<mark key={best} className={current ? 'grid-hit-current' : 'grid-hit'}>{text.slice(best, best + len)}</mark>);
    pos = best + len;
  }
  if (pos < text.length) out.push(text.slice(pos));
  return out;
}

export const VirtualGrid: React.FC<VirtualGridProps> = ({
  columns, rows, rowLabel, query = '', editable, locked, edited, onEdit, selectedRow, onSelectRow,
}) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [height, setHeight] = useState(600);
  const [active, setActive] = useState<{ r: number; c: number } | null>(null);
  const [draft, setDraft] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const report = useContext(HitsContext);

  // Hits from the data: the whole query, or its words when the whole query has no hit
  const { hits, terms } = useMemo(() => {
    const all = searchTerms(query);
    if (!all.length) return { hits: [] as [number, number][], terms: [] as string[] };
    const scan = (list: string[]) => {
      const found: [number, number][] = [];
      for (let r = 0; r < rows.length && found.length < 20000; r++) {
        const row = rows[r];
        for (let c = 0; c < row.length; c++) {
          const v = row[c];
          if (v && list.some(t => v.toLowerCase().includes(t))) found.push([r, c]);
        }
      }
      return found;
    };
    let list = [all[0]];
    let found = scan(list);
    if (!found.length && all.length > 1) {
      list = all.slice(1);
      found = scan(list);
    }
    return { hits: found, terms: list };
  }, [rows, query]);
  const [hitIndex, setHitIndex] = useState(0);
  const widths = useMemo(
    () => columnWidths(columns, rows, hits.slice(0, 200).map(([r]) => rows[r])),
    [columns, rows, hits],
  );

  const scrollToCell = (r: number, c: number) => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = Math.max(0, r * ROW_H - el.clientHeight / 2 + ROW_H);
    const left = 48 + widths.slice(0, c).reduce((a, b) => a + b, 0);
    if (left < el.scrollLeft || left + widths[c] > el.scrollLeft + el.clientWidth) {
      el.scrollLeft = Math.max(0, left - el.clientWidth / 3);
    }
  };

  // New hits: go to the first one
  useEffect(() => {
    setHitIndex(0);
    if (hits.length) requestAnimationFrame(() => scrollToCell(hits[0][0], hits[0][1]));
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
        const next = (hitIndex + step + hits.length) % hits.length;
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
  const end = Math.min(rows.length, Math.ceil((scrollTop + height) / ROW_H) + OVERSCAN);

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
    if (!el) return;
    const top = r * ROW_H;
    if (top < el.scrollTop) el.scrollTop = top;
    else if (top + ROW_H * 2 > el.scrollTop + el.clientHeight) el.scrollTop = top + ROW_H * 2 - el.clientHeight;
  };

  const totalWidth = 48 + widths.reduce((a, b) => a + b, 0);

  return (
    <div
      ref={scrollRef}
      className="h-full overflow-auto select-text"
      onScroll={e => {
        const top = (e.target as HTMLDivElement).scrollTop;
        requestAnimationFrame(() => setScrollTop(top));
      }}
    >
      <table className="border-collapse font-mono text-[12px]" style={{ tableLayout: 'fixed', width: totalWidth }}>
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
        </thead>
        <tbody>
          {start > 0 && <tr style={{ height: start * ROW_H }} />}
          {rows.slice(start, end).map((row, k) => {
            const r = start + k;
            const isSelected = selectedRow === r;
            return (
              <tr key={r} style={{ height: ROW_H, borderBottom: '1px solid var(--line)', background: isSelected ? 'var(--accent-soft)' : undefined }} className="hover:bg-[rgba(255,255,255,0.025)]">
                <td
                  className="sticky left-0 px-2 text-center text-fg-3 select-none"
                  style={{ background: isSelected ? 'rgba(124,156,255,0.22)' : 'var(--bg)', cursor: onSelectRow ? 'pointer' : 'default' }}
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
                        boxShadow: isActive ? 'inset 0 0 0 2px var(--accent)' : isCurrent ? 'inset 0 0 0 1px rgba(250,204,21,0.7)' : undefined,
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
                          className="absolute inset-0 w-full px-3 bg-[#101016] text-fg outline-none font-mono text-[12px]"
                        />
                      ) : (
                        <>
                          {isLocked && <Lock className="inline w-3 h-3 mr-1 -mt-0.5 opacity-60" />}
                          {terms.length ? splitHits(value, terms, isCurrent) : value}
                        </>
                      )}
                    </td>
                  );
                })}
              </tr>
            );
          })}
          {end < rows.length && <tr style={{ height: (rows.length - end) * ROW_H }} />}
        </tbody>
      </table>
    </div>
  );
};
