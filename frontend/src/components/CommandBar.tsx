import React, { useEffect, useRef, useState } from 'react';
import { ChevronDown, Folder, FolderTree, Search, X } from 'lucide-react';
import { SearchMode } from '../api';
import { SegmentedControl } from './motion/SegmentedControl';
import { folderLabel } from '../utils/paths';

// Command-palette search field (matrix ref R41 Command Menu). A folder scope shows as a
// breadcrumb chip with a stacked layer behind the bar; Backspace on an empty field
// leaves the scope (matrix ref R23 ⌘K Breadcrumbs).

interface CommandBarProps {
  query: string;
  onQueryChange: (q: string) => void;
  mode: SearchMode;
  onModeChange: (m: SearchMode) => void;
  scope: string | null;
  onScopeChange: (folder: string | null) => void;
  folders: string[];
  busy: boolean;
  inputRef: React.RefObject<HTMLInputElement>;
  onArrow: (dir: 1 | -1) => void;
  onSubmit: (e: React.KeyboardEvent) => void;
}

const MODES = [
  { id: 'all' as const, label: 'All', hint: 'Names and file text' },
  { id: 'filename' as const, label: 'Names', hint: 'File and folder names only' },
  { id: 'content' as const, label: 'Text', hint: 'Text inside files only' },
];

export const CommandBar: React.FC<CommandBarProps> = ({
  query,
  onQueryChange,
  mode,
  onModeChange,
  scope,
  onScopeChange,
  folders,
  busy,
  inputRef,
  onArrow,
  onSubmit,
}) => {
  const [scopeOpen, setScopeOpen] = useState(false);
  const scopeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!scopeOpen) return;
    const close = (e: MouseEvent) => {
      if (!scopeRef.current?.contains(e.target as Node)) setScopeOpen(false);
    };
    window.addEventListener('mousedown', close);
    return () => window.removeEventListener('mousedown', close);
  }, [scopeOpen]);

  return (
    <div className="relative">
      {/* Stacked layer behind the bar when a scope is active */}
      <div
        aria-hidden
        className="absolute left-4 right-4 -top-[7px] h-6 rounded-t-xl px-3 text-[10.5px] text-fg-3 flex items-start pt-1"
        style={{
          background: 'var(--surface)',
          boxShadow: 'inset 0 1px 0 var(--line-strong)',
          opacity: scope ? 1 : 0,
          transform: scope ? 'translateY(0) scale(1)' : 'translateY(8px) scale(0.98)',
          transition: 'opacity 260ms var(--ease-out), transform 360ms var(--ease-spring)',
        }}
      >
        All folders
      </div>

      <div
        className="command-bar relative flex items-center gap-2 h-[52px] pl-4 pr-2 rounded-2xl"
      >
        <span className="relative w-[18px] h-[18px] shrink-0 text-fg-3">
          <Search
            className="absolute inset-0 w-[18px] h-[18px] transition-all duration-200"
            style={{ opacity: busy ? 0 : 1, transform: busy ? 'scale(0.6)' : 'scale(1)' }}
          />
          {/* Mounted only while busy: an invisible endless animation still costs GPU time */}
          {busy && (
            <span
              className="absolute inset-[2px] rounded-full spin"
              style={{ border: '2px solid var(--line-strong)', borderTopColor: 'var(--accent)' }}
            />
          )}
        </span>

        {scope && (
          <button
            type="button"
            onClick={() => onScopeChange(null)}
            className="group flex items-center gap-1.5 h-7 pl-2 pr-1.5 rounded-lg text-[12px] font-medium text-fg shrink-0 fade-up"
            style={{ background: 'var(--accent-soft)', boxShadow: 'inset 0 0 0 1px var(--accent-line)', animationDuration: '320ms' }}
            title={`Searching only in ${scope}. Click or press Backspace to search all folders.`}
          >
            <Folder className="w-3.5 h-3.5 text-accent" />
            <span className="max-w-[160px] truncate">{folderLabel(scope)}</span>
            <X className="w-3 h-3 text-fg-3 group-hover:text-fg" />
          </button>
        )}

        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={e => onQueryChange(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
              // Focus moves to the list here, so the window key handler must not see this press too
              e.preventDefault();
              e.stopPropagation();
              onArrow(e.key === 'ArrowDown' ? 1 : -1);
            } else if (e.key === 'Backspace' && !query && scope) {
              e.preventDefault();
              onScopeChange(null);
            } else if (e.key === 'Enter') {
              onSubmit(e);
            }
          }}
          placeholder={scope ? `Search in ${folderLabel(scope)}…` : 'Search file names and text…'}
          className="flex-1 min-w-0 h-full bg-transparent text-[16px] text-fg placeholder:text-fg-3 outline-none select-text"
          autoFocus
          spellCheck={false}
          autoComplete="off"
        />

        {query && (
          <button
            type="button"
            className="icon-btn shrink-0"
            onClick={() => {
              onQueryChange('');
              inputRef.current?.focus();
            }}
            title="Clear (Esc)"
          >
            <X className="w-4 h-4" />
          </button>
        )}

        {folders.length > 1 && (
          <div className="relative shrink-0" ref={scopeRef}>
            <button
              type="button"
              onClick={() => setScopeOpen(v => !v)}
              className="flex items-center gap-1 h-8 px-2 rounded-lg text-[12px] text-fg-3 hover:text-fg hover:bg-surface-2 transition-colors"
              title="Search in one folder"
            >
              <FolderTree className="w-4 h-4" />
              <ChevronDown className="w-3 h-3" />
            </button>
            {scopeOpen && (
              <div
                className="absolute right-0 top-10 z-40 w-72 p-1 rounded-xl fade-up"
                style={{
                  background: 'rgba(24,24,31,0.97)',
                  backdropFilter: 'blur(14px)',
                  boxShadow: 'inset 0 0 0 1px var(--line-strong), 0 18px 40px -12px rgba(0,0,0,0.75)',
                  animationDuration: '260ms',
                }}
              >
                <div className="label-caps px-2.5 pt-2 pb-1.5">Search in</div>
                {[null, ...folders].map(f => (
                  <button
                    key={f ?? '*'}
                    type="button"
                    onClick={() => {
                      onScopeChange(f);
                      setScopeOpen(false);
                      inputRef.current?.focus();
                    }}
                    className={`flex items-center gap-2.5 w-full h-9 px-2.5 rounded-md text-left text-[12.5px] transition-colors ${
                      scope === f ? 'bg-surface-2 text-fg' : 'text-fg-2 hover:bg-surface-2 hover:text-fg'
                    }`}
                  >
                    {f ? <Folder className="w-4 h-4 text-fg-3 shrink-0" /> : <FolderTree className="w-4 h-4 text-fg-3 shrink-0" />}
                    <span className="flex flex-col min-w-0">
                      <span className="truncate">{f ? folderLabel(f) : 'All folders'}</span>
                      {f && <span className="truncate font-mono text-[10.5px] text-fg-3">{f}</span>}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        <SegmentedControl options={MODES} value={mode} onChange={onModeChange} size="sm" className="shrink-0" />
      </div>
    </div>
  );
};
