import React, { useEffect, useState } from 'react';
import { FolderOpen, RefreshCw, X } from 'lucide-react';
import { api, FolderDetails, IndexerStatus } from '../api';
import { FolderManager } from './FolderManager';
import { HoldButton } from './motion/HoldButton';
import { useToast } from './Toasts';

// Side sheet to manage working folders after setup. Every change applies at once.

interface FoldersPanelProps {
  open: boolean;
  details: FolderDetails | null;
  status: IndexerStatus | null;
  onClose: () => void;
  onChanged: () => void;
}

export const FoldersPanel: React.FC<FoldersPanelProps> = ({ open, details, status, onClose, onChanged }) => {
  const toast = useToast();
  const [mounted, setMounted] = useState(open);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (open) {
      setMounted(true);
      requestAnimationFrame(() => requestAnimationFrame(() => setVisible(true)));
    } else {
      setVisible(false);
      const t = window.setTimeout(() => setMounted(false), 320);
      return () => window.clearTimeout(t);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [open, onClose]);

  if (!mounted) return null;

  const folders = details?.folders.map(f => f.path) ?? [];
  // Live stats from the indexer, file counts from the folder list
  const stats = (details?.folders ?? []).map(f => {
    const live = status?.folders.find(s => s.path.toLowerCase() === f.path.toLowerCase());
    const busy = live && (live.state === 'scanning' || live.state === 'queued');
    return { ...f, state: busy ? live!.state : f.state, files: busy ? live!.files : f.files };
  });

  const save = async (next: string[], message: string) => {
    try {
      await api.saveFolders(next);
      toast(message);
      onChanged();
    } catch (e) {
      toast((e as Error).message, 'error');
    }
  };

  return (
    <div className="fixed inset-0 z-50">
      <div
        className="absolute inset-0 transition-opacity duration-300"
        style={{ background: 'rgba(5,5,8,0.55)', backdropFilter: 'blur(3px)', opacity: visible ? 1 : 0 }}
        onClick={onClose}
      />
      <aside
        className="absolute top-2 right-2 bottom-2 w-[min(520px,calc(100%-16px))] flex flex-col rounded-2xl overflow-hidden"
        style={{
          background: 'var(--bg-elev)',
          boxShadow: 'inset 0 0 0 1px var(--line-strong), 0 30px 80px -20px rgba(0,0,0,0.85)',
          transform: visible ? 'translateX(0)' : 'translateX(calc(100% + 16px))',
          transition: 'transform 380ms var(--ease-out)',
        }}
        role="dialog"
        aria-label="Working folders"
      >
        <div className="flex items-center justify-between h-14 px-5 shrink-0" style={{ borderBottom: '1px solid var(--line)' }}>
          <div className="flex flex-col">
            <span className="font-display text-[15px] font-semibold text-fg">Working folders</span>
            <span className="text-[11.5px] text-fg-3">Only these folders are indexed, previewed, and opened.</span>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} title="Close (Esc)">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto p-5">
          <FolderManager
            mode="live"
            selected={folders}
            stats={stats}
            canPick={details?.can_pick ?? false}
            onAdd={paths => save([...folders, ...paths], paths.length > 1 ? `${paths.length} folders added` : 'Folder added. Scanning now.')}
            onRemove={path => save(folders.filter(f => f !== path), 'Folder removed from the index')}
            onReindex={async path => {
              await api.reindex(path);
              toast('Scanning again');
              onChanged();
            }}
          />
        </div>

        <div className="flex items-center justify-between gap-3 px-5 h-14 shrink-0" style={{ borderTop: '1px solid var(--line)' }}>
          <button
            type="button"
            className="flex items-center gap-1.5 min-w-0 text-[11.5px] text-fg-3 hover:text-fg transition-colors"
            onClick={() => api.openDataFolder()}
            title="Open the data folder"
          >
            <FolderOpen className="w-3.5 h-3.5 shrink-0" />
            <span className="truncate font-mono">{details?.data_dir}</span>
          </button>
          <HoldButton
            tone="accent"
            disabled={!folders.length}
            title="Hold to scan all folders again"
            onShortPress={() => toast('Hold the button to re-index', 'info')}
            onConfirm={async () => {
              await api.reindex();
              toast('Scanning all folders again');
              onChanged();
            }}
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Hold to re-index all
          </HoldButton>
        </div>
      </aside>
    </div>
  );
};
