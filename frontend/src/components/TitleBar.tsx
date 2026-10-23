import React, { useEffect, useRef, useState } from 'react';
import { FolderCog, FolderOpen, Keyboard, Maximize2, Minus, MoreHorizontal, Power, RefreshCw, Settings, SlidersHorizontal, X } from 'lucide-react';
import { IndexerStatus } from '../api';
import { RollingNumber } from './motion/RollingNumber';
import { baseName } from '../utils/paths';

interface TitleBarProps {
  status: IndexerStatus | null;
  showFolderButton: boolean;
  onOpenFolders: () => void;
  onReindexAll: () => void;
  onHide: () => void;
  onMaximize: () => void;
  onOpenDataFolder: () => void;
  onOpenShortcuts: () => void;
  onOpenSearchSettings: () => void;
  onOpenSettings: () => void;
  onQuit: () => void;
}

export const StatusPill: React.FC<{ status: IndexerStatus | null }> = ({ status }) => {
  if (!status || status.phase === 'setup') return null;
  const scanning = status.phase === 'scanning';
  const reading = status.phase === 'reading';
  const dot = scanning ? 'var(--accent)' : reading ? 'var(--warn)' : 'var(--ok)';
  const label = scanning
    ? `Scanning ${status.current_folder ? baseName(status.current_folder) : ''}`.trim()
    : reading
      ? 'Reading text'
      : 'Up to date';
  return (
    <div
      className="flex items-center gap-2 h-7 pl-2.5 pr-3 rounded-full text-[11.5px] text-fg-2"
      style={{ background: 'var(--bg-elev)', boxShadow: 'inset 0 0 0 1px var(--line)' }}
      title={
        reading
          ? `${status.content.pending.toLocaleString()} files are waiting for text extraction`
          : status.watcher_active
            ? 'Changes in your working folders are picked up live'
            : undefined
      }
    >
      <span className={`w-1.5 h-1.5 rounded-full ${scanning || reading ? 'live-dot' : ''}`} style={{ background: dot }} />
      <span className="text-fg-3">{label}</span>
      <span className="w-px h-3 bg-line-strong" />
      <RollingNumber value={status.total_indexed} className="text-[12px] font-semibold text-fg" />
      <span className="text-fg-3">files</span>
    </div>
  );
};

export const TitleBar: React.FC<TitleBarProps> = ({
  status,
  showFolderButton,
  onOpenFolders,
  onReindexAll,
  onHide,
  onMaximize,
  onOpenDataFolder,
  onOpenShortcuts,
  onOpenSearchSettings,
  onOpenSettings,
  onQuit,
}) => {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const close = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    window.addEventListener('mousedown', close);
    return () => window.removeEventListener('mousedown', close);
  }, [menuOpen]);

  const menuItem = (icon: React.ReactNode, label: string, action: () => void, danger = false) => (
    <button
      type="button"
      onClick={() => {
        setMenuOpen(false);
        action();
      }}
      className={`flex items-center gap-2.5 w-full h-8 px-2.5 rounded-md text-[12.5px] text-left transition-colors ${
        danger ? 'text-danger hover:bg-[rgba(240,97,109,0.1)]' : 'text-fg-2 hover:text-fg hover:bg-surface-2'
      }`}
    >
      {icon}
      {label}
    </button>
  );

  return (
    <header
      className="pywebview-drag-region relative z-30 flex items-center justify-between h-11 pl-4 pr-2 shrink-0"
      onDoubleClick={e => {
        if ((e.target as HTMLElement).closest('button')) return;
        onMaximize();
      }}
    >
      <div className="flex items-center gap-2.5 pointer-events-none">
        <span
          className="flex items-center justify-center w-6 h-6 rounded-[7px]"
          style={{ background: 'linear-gradient(160deg, #20222c, #14151b)', boxShadow: 'inset 0 0 0 1px var(--line-strong)' }}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2.6" strokeLinecap="round">
            <circle cx="10.5" cy="10.5" r="6.5" />
            <path d="m20 20-4.6-4.6" />
          </svg>
        </span>
        <span className="font-display text-[13px] font-semibold tracking-[-0.01em] text-fg">Peek &amp; Grep</span>
      </div>

      <div className="flex items-center gap-1.5">
        <StatusPill status={status} />
        {showFolderButton && (
          <button type="button" className="icon-btn ml-1" onClick={onOpenFolders} title="Working folders">
            <FolderCog className="w-4 h-4" />
          </button>
        )}
        <div className="relative" ref={menuRef}>
          <button type="button" className="icon-btn" onClick={() => setMenuOpen(v => !v)} title="More">
            <MoreHorizontal className="w-4 h-4" />
          </button>
          {menuOpen && (
            <div
              className="absolute right-0 top-9 w-56 p-1 rounded-xl fade-up"
              style={{
                background: 'rgba(24,24,31,0.97)',
                backdropFilter: 'blur(14px)',
                boxShadow: 'inset 0 0 0 1px var(--line-strong), 0 18px 40px -12px rgba(0,0,0,0.75)',
                ['--d' as string]: '0ms',
                animationDuration: '260ms',
              }}
            >
              {showFolderButton && menuItem(<FolderCog className="w-4 h-4" />, 'Working folders…', onOpenFolders)}
              {showFolderButton && menuItem(<RefreshCw className="w-4 h-4" />, 'Re-index all folders', onReindexAll)}
              {menuItem(<Settings className="w-4 h-4" />, 'Settings…', onOpenSettings)}
              {showFolderButton && menuItem(<SlidersHorizontal className="w-4 h-4" />, 'Search settings…', onOpenSearchSettings)}
              {showFolderButton && menuItem(<Keyboard className="w-4 h-4" />, 'Keyboard shortcuts…', onOpenShortcuts)}
              {menuItem(<FolderOpen className="w-4 h-4" />, 'Open data folder', onOpenDataFolder)}
              <div className="h-px my-1 bg-line" />
              {menuItem(<Power className="w-4 h-4" />, 'Quit Peek & Grep', onQuit, true)}
            </div>
          )}
        </div>
        <div className="w-px h-4 mx-1 bg-line-strong" />
        <button type="button" className="icon-btn" onClick={onHide} title="Hide to tray (Esc)">
          <Minus className="w-4 h-4" />
        </button>
        <button type="button" className="icon-btn" onClick={onMaximize} title="Maximize or restore">
          <Maximize2 className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          className="icon-btn hover:!bg-[rgba(240,97,109,0.14)] hover:!text-danger"
          onClick={onHide}
          title="Close to tray. Quit from the … menu or the tray icon."
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
};
