import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, CornerDownLeft } from 'lucide-react';
import { SearchItem } from '../api';
import { FileIcon } from './FileIcon';
import { fileKind, formatBytes, formatRelativeTime } from '../utils/formatters';
import { compactCrumbs, folderCrumbs, highlightName } from '../utils/paths';
import { HighlightTerm } from '../utils/query';

// One highlight glides between rows (matrix refs R41 Command Menu, X04 result rows).
// While you move with the keyboard, rows far from the selection fade a little, like a
// slot list (matrix ref E14). New rows rise and sharpen in sequence (X04, R03 Blur Reveal).
// A search with [a, b] shows one expandable row per element. More rows load while you
// scroll: the "more" row at the end of a list asks for the next page when it comes into view.

export type Row =
  | { kind: 'item'; key: string; item: SearchItem; group: number | null; index: number }
  | { kind: 'header'; key: string; group: number; label: string; total: number; expanded: boolean; loading: boolean }
  | { kind: 'more'; key: string; group: number | null; loading: boolean };

interface ResultsListProps {
  rows: Row[];
  selectedIndex: number;
  onSelect: (idx: number) => void;
  onOpen: (item: SearchItem) => void;
  onPreview: (idx: number) => void;
  onToggleGroup: (group: number) => void;
  onLoadMore: (group: number | null) => void;
  termsFor: (group: number | null) => HighlightTerm[];
  folders: string[];
  keyboardFocus: boolean;
  listRef: React.RefObject<HTMLDivElement>;
  empty: React.ReactNode;
  previewKey?: string;
}

const MoreRow: React.FC<{ row: Extract<Row, { kind: 'more' }>; root: React.RefObject<HTMLDivElement>; onLoadMore: (g: number | null) => void }> = ({ row, root, onLoadMore }) => {
  const ref = useRef<HTMLDivElement>(null);
  const load = useRef(onLoadMore);
  load.current = onLoadMore;
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      entries => {
        if (entries.some(e => e.isIntersecting)) load.current(row.group);
      },
      { root: root.current, rootMargin: '600px 0px' },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [row.group, row.loading, root]);
  return (
    <div ref={ref} className={`flex items-center gap-2 h-9 text-[12px] text-fg-3 ${row.group !== null ? 'pl-12' : 'pl-6'}`}>
      <span className="w-3 h-3 rounded-full spin" style={{ border: '1.5px solid var(--line-strong)', borderTopColor: 'var(--accent)' }} />
      Loading more…
    </div>
  );
};

export const ResultsList: React.FC<ResultsListProps> = ({
  rows,
  selectedIndex,
  onSelect,
  onOpen,
  onPreview,
  onToggleGroup,
  onLoadMore,
  termsFor,
  folders,
  keyboardFocus,
  listRef,
  empty,
  previewKey = 'Space',
}) => {
  const rowRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const prevKeys = useRef<Set<string>>(new Set());
  const [hl, setHl] = useState({ top: 0, height: 0, visible: false, instant: true });

  // Rows that were not on screen before get an entry animation, in order
  const enterIndex = useMemo(() => {
    const map = new Map<string, number>();
    let n = 0;
    for (const r of rows) {
      if (r.kind !== 'more' && !prevKeys.current.has(r.key)) map.set(r.key, n++);
    }
    return map;
  }, [rows]);

  useEffect(() => {
    prevKeys.current = new Set(rows.map(r => r.key));
  }, [rows]);

  const selectedKey = rows[selectedIndex]?.key;
  const innerRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = selectedKey ? rowRefs.current.get(selectedKey) : undefined;
    if (!el) {
      setHl(h => ({ ...h, visible: false }));
      return;
    }
    const measure = () => setHl(h => (h.top === el.offsetTop && h.height === el.offsetHeight && h.visible
      ? h
      : { top: el.offsetTop, height: el.offsetHeight, visible: true, instant: !h.visible }));
    measure();
    el.scrollIntoView({ block: 'nearest' });
    // Rows off screen are drawn later (content-visibility) and get their real height then
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    if (innerRef.current) ro.observe(innerRef.current);
    return () => ro.disconnect();
  }, [selectedKey, rows]);

  if (rows.length === 0) {
    return <div className="flex-1 flex items-center justify-center">{empty}</div>;
  }

  const setRef = (key: string) => (el: HTMLDivElement | null) => {
    if (el) rowRefs.current.set(key, el);
    else rowRefs.current.delete(key);
  };

  return (
    <div
      ref={listRef}
      tabIndex={-1}
      className="flex-1 min-h-0 overflow-y-auto outline-none px-2 pb-2"
      role="listbox"
      aria-activedescendant={`row-${selectedIndex}`}
    >
      <div ref={innerRef} className="relative">
        {/* Gliding highlight */}
        <div
          aria-hidden
          className="absolute left-0 right-0 rounded-xl pointer-events-none"
          style={{
            transform: `translateY(${hl.top}px)`,
            height: hl.height,
            opacity: hl.visible ? 1 : 0,
            background: 'linear-gradient(90deg, rgba(124,156,255,0.11), rgba(124,156,255,0.045) 60%, rgba(124,156,255,0.03))',
            boxShadow: 'inset 0 0 0 1px rgba(124,156,255,0.22)',
            transition: hl.instant
              ? 'opacity 160ms'
              : 'transform 260ms var(--ease-spring), height 260ms var(--ease-out), opacity 160ms',
          }}
        >
          <span className="absolute left-0 top-3 bottom-3 w-[2px] rounded-full" style={{ background: 'var(--accent)' }} />
        </div>

        {rows.map((row, idx) => {
          if (row.kind === 'more') {
            return <MoreRow key={row.key} row={row} root={listRef} onLoadMore={onLoadMore} />;
          }
          const selected = idx === selectedIndex;
          const distance = Math.abs(idx - selectedIndex);
          const fade = keyboardFocus ? Math.max(0.55, 1 - Math.min(distance, 6) * 0.075) : 1;
          const order = enterIndex.get(row.key);
          const enter = order !== undefined && order < 16 ? 'row-enter' : '';

          if (row.kind === 'header') {
            const Chevron = row.expanded ? ChevronDown : ChevronRight;
            return (
              <div
                key={row.key}
                id={`row-${idx}`}
                role="option"
                aria-selected={selected}
                aria-expanded={row.expanded}
                ref={setRef(row.key)}
                onClick={() => {
                  onSelect(idx);
                  onToggleGroup(row.group);
                }}
                className={`group relative flex items-center gap-2.5 pl-3 pr-3 h-11 mt-1 rounded-xl cursor-default ${enter}`}
                style={{ ['--i' as string]: order ?? 0, opacity: fade, transition: 'opacity 220ms var(--ease-out)' }}
                title={row.expanded ? 'Close this group (←)' : 'Open this group (→)'}
              >
                {!selected && <span className="absolute inset-0 rounded-xl opacity-0 group-hover:opacity-100 transition-opacity bg-[rgba(255,255,255,0.025)]" />}
                <span
                  className="relative flex items-center justify-center w-6 h-6 rounded-md text-fg-2"
                  style={{ background: 'var(--surface-2)', boxShadow: 'inset 0 0 0 1px var(--line)' }}
                >
                  <Chevron className="w-3.5 h-3.5" />
                </span>
                <span className={`relative truncate text-[13.5px] font-semibold ${row.total ? 'text-fg' : 'text-fg-3'}`}>{row.label}</span>
                <span
                  className={`relative shrink-0 num text-[11.5px] px-2 h-[19px] inline-flex items-center rounded-full ${row.total ? 'text-accent bg-accent-soft' : 'text-fg-3'}`}
                  style={row.total ? undefined : { boxShadow: 'inset 0 0 0 1px var(--line)' }}
                >
                  {row.total ? `${row.total.toLocaleString()} file${row.total === 1 ? '' : 's'}` : 'no hits'}
                </span>
                {row.loading && <span className="relative w-3 h-3 rounded-full spin" style={{ border: '1.5px solid var(--line-strong)', borderTopColor: 'var(--accent)' }} />}
                <span className="relative flex-1 h-px ml-1 bg-line" />
              </div>
            );
          }

          const { item } = row;
          const nested = row.group !== null;
          const crumbs = compactCrumbs(folderCrumbs(item.path, folders));
          const kind = fileKind(item.category, item.extension);
          return (
            <div
              key={row.key}
              id={`row-${idx}`}
              role="option"
              aria-selected={selected}
              ref={setRef(row.key)}
              onClick={() => onSelect(idx)}
              onDoubleClick={() => onOpen(item)}
              className={`group relative flex gap-3 pr-3 py-2.5 rounded-xl cursor-default ${nested ? 'pl-12' : 'pl-6'} ${enter}`}
              style={{
                ['--i' as string]: order ?? 0,
                opacity: fade,
                transition: 'opacity 220ms var(--ease-out)',
                contentVisibility: 'auto',
                containIntrinsicSize: 'auto 44px',
              }}
              title={item.path}
            >
              {nested && <span aria-hidden className="absolute left-[23px] top-0 bottom-0 w-px bg-line" />}
              {/* Accent prefix of the selected row (E14) */}
              <ChevronRight
                className={`absolute top-[18px] w-3.5 h-3.5 text-accent transition-all duration-200 ${nested ? 'left-[30px]' : 'left-1.5'}`}
                style={{ opacity: selected ? 1 : 0, transform: selected ? 'translateX(0)' : 'translateX(-4px)' }}
              />
              {!selected && <span className="absolute inset-0 rounded-xl opacity-0 group-hover:opacity-100 transition-opacity bg-[rgba(255,255,255,0.025)]" />}

              <FileIcon kind={kind} />

              <div className="relative flex-1 min-w-0">
                <div className="flex items-center gap-2 min-w-0">
                  <span
                    className={`truncate text-[13.5px] font-medium ${selected ? 'text-fg' : 'text-[#dcdce6]'}`}
                    dangerouslySetInnerHTML={{ __html: highlightName(item.filename, termsFor(row.group)) }}
                  />
                  {item.match_type === 'both' && (
                    <span className="shrink-0 text-[10px] font-medium px-1.5 h-[17px] inline-flex items-center rounded-[5px] text-accent bg-accent-soft">
                      name + text
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-1 min-w-0 mt-0.5 font-mono text-[11px] text-fg-3">
                  {crumbs.map((c, i) => (
                    <React.Fragment key={i}>
                      {i > 0 && <span className="opacity-50">›</span>}
                      <span className={`truncate ${i === 0 ? 'text-fg-2' : ''}`}>{c}</span>
                    </React.Fragment>
                  ))}
                </div>
                {item.snippet && (
                  <div
                    className="mt-1.5 text-[12px] leading-[1.55] text-fg-2 line-clamp-2 select-text"
                    dangerouslySetInnerHTML={{ __html: item.snippet }}
                  />
                )}
              </div>

              <div className="relative shrink-0 flex flex-col items-end gap-1 pt-0.5 w-[92px]">
                <div
                  className="flex items-center gap-1 transition-all duration-200"
                  style={{ opacity: selected ? 0 : 1, transform: selected ? 'translateY(-3px)' : 'none' }}
                >
                  <span className="text-[11.5px] text-fg-3">{formatRelativeTime(item.mtime)}</span>
                </div>
                <span
                  className="text-[11.5px] num text-fg-3 transition-opacity duration-200"
                  style={{ opacity: selected ? 0 : 1 }}
                >
                  {formatBytes(item.size_bytes)}
                </span>
                <div
                  className="absolute top-0 right-0 flex items-center gap-1 transition-all duration-200"
                  style={{
                    opacity: selected ? 1 : 0,
                    transform: selected ? 'none' : 'translateY(3px)',
                    pointerEvents: selected ? 'auto' : 'none',
                  }}
                >
                  <button type="button" className="kbd hover:text-fg" onClick={e => { e.stopPropagation(); onPreview(idx); }} title="Quick Look">
                    {previewKey}
                  </button>
                  <button type="button" className="kbd hover:text-fg" onClick={e => { e.stopPropagation(); onOpen(item); }} title="Open">
                    <CornerDownLeft className="w-3 h-3" />
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
