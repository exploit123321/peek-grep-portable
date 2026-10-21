import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { ChevronRight, CornerDownLeft } from 'lucide-react';
import { SearchItem } from '../api';
import { FileIcon } from './FileIcon';
import { fileKind, formatBytes, formatRelativeTime } from '../utils/formatters';
import { compactCrumbs, folderCrumbs, highlightName } from '../utils/paths';

// One highlight glides between rows (matrix refs R41 Command Menu, X04 result rows).
// While you move with the keyboard, rows far from the selection fade a little, like a
// slot list (matrix ref E14). New rows rise and sharpen in sequence (X04, R03 Blur Reveal).

interface ResultsListProps {
  items: SearchItem[];
  selectedIndex: number;
  onSelect: (idx: number) => void;
  onOpen: (item: SearchItem) => void;
  onPreview: (idx: number) => void;
  query: string;
  folders: string[];
  keyboardFocus: boolean;
  listRef: React.RefObject<HTMLDivElement>;
  empty: React.ReactNode;
}

export const ResultsList: React.FC<ResultsListProps> = ({
  items,
  selectedIndex,
  onSelect,
  onOpen,
  onPreview,
  query,
  folders,
  keyboardFocus,
  listRef,
  empty,
}) => {
  const rowRefs = useRef<(HTMLDivElement | null)[]>([]);
  const prevPaths = useRef<Set<string>>(new Set());
  const [hl, setHl] = useState({ top: 0, height: 0, visible: false, instant: true });

  // Rows that were not on screen before get an entry animation, in order
  const enterIndex = useMemo(() => {
    const map = new Map<string, number>();
    let n = 0;
    for (const it of items) {
      if (!prevPaths.current.has(it.path)) map.set(it.path, n++);
    }
    return map;
  }, [items]);

  useEffect(() => {
    prevPaths.current = new Set(items.map(i => i.path));
  }, [items]);

  useLayoutEffect(() => {
    const el = rowRefs.current[selectedIndex];
    if (!el) {
      setHl(h => ({ ...h, visible: false }));
      return;
    }
    setHl(h => ({ top: el.offsetTop, height: el.offsetHeight, visible: true, instant: !h.visible }));
    el.scrollIntoView({ block: 'nearest' });
  }, [selectedIndex, items]);

  if (items.length === 0) {
    return <div className="flex-1 flex items-center justify-center">{empty}</div>;
  }

  return (
    <div
      ref={listRef}
      tabIndex={-1}
      className="flex-1 min-h-0 overflow-y-auto outline-none px-2 pb-2"
      role="listbox"
      aria-activedescendant={`row-${selectedIndex}`}
    >
      <div className="relative">
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

        {items.map((item, idx) => {
          const selected = idx === selectedIndex;
          const distance = Math.abs(idx - selectedIndex);
          const fade = keyboardFocus ? Math.max(0.55, 1 - Math.min(distance, 6) * 0.075) : 1;
          const crumbs = compactCrumbs(folderCrumbs(item.path, folders));
          const kind = fileKind(item.category, item.extension);
          const order = enterIndex.get(item.path);
          return (
            <div
              key={item.path}
              id={`row-${idx}`}
              role="option"
              aria-selected={selected}
              ref={el => (rowRefs.current[idx] = el)}
              onClick={() => onSelect(idx)}
              onDoubleClick={() => onOpen(item)}
              className={`group relative flex gap-3 pl-6 pr-3 py-2.5 rounded-xl cursor-default ${order !== undefined && order < 16 ? 'row-enter' : ''}`}
              style={{
                ['--i' as string]: order ?? 0,
                opacity: fade,
                transition: 'opacity 220ms var(--ease-out)',
              }}
              title={item.path}
            >
              {/* Accent prefix of the selected row (E14) */}
              <ChevronRight
                className="absolute left-1.5 top-[18px] w-3.5 h-3.5 text-accent transition-all duration-200"
                style={{ opacity: selected ? 1 : 0, transform: selected ? 'translateX(0)' : 'translateX(-4px)' }}
              />
              {!selected && <span className="absolute inset-0 rounded-xl opacity-0 group-hover:opacity-100 transition-opacity bg-[rgba(255,255,255,0.025)]" />}

              <FileIcon kind={kind} />

              <div className="relative flex-1 min-w-0">
                <div className="flex items-center gap-2 min-w-0">
                  <span
                    className={`truncate text-[13.5px] font-medium ${selected ? 'text-fg' : 'text-[#dcdce6]'}`}
                    dangerouslySetInnerHTML={{ __html: highlightName(item.filename, query) }}
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
                  className="text-[11px] font-mono text-fg-3 transition-opacity duration-200"
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
                  <button type="button" className="kbd hover:text-fg" onClick={e => { e.stopPropagation(); onPreview(idx); }} title="Quick Look (Space)">
                    Space
                  </button>
                  <button type="button" className="kbd hover:text-fg" onClick={e => { e.stopPropagation(); onOpen(item); }} title="Open (Enter)">
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
