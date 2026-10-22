import React, { useMemo, useState } from 'react';
import { AlertTriangle, FolderPlus, HardDrive, Folder, RefreshCw, Trash2, Check } from 'lucide-react';
import { api, FolderStatus } from '../api';
import { AnimatedCheckbox } from './motion/AnimatedCheckbox';
import { HoldButton } from './motion/HoldButton';
import { RollingNumber } from './motion/RollingNumber';
import { useToast } from './Toasts';
import { folderLabel } from '../utils/paths';

// Draft mode (first run): tick folders, nothing is saved until "Start indexing".
// Live mode (folders panel): every change applies at once. Remove needs a hold (R12).

interface FolderManagerProps {
  mode: 'draft' | 'live';
  selected: string[];
  suggestions?: { label: string; path: string }[];
  stats?: FolderStatus[];
  canPick: boolean;
  onAdd: (paths: string[]) => void | Promise<void>;
  onRemove: (path: string) => void | Promise<void>;
  onReindex?: (path: string) => void;
}

const sameKey = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();

export const FolderManager: React.FC<FolderManagerProps> = ({
  mode,
  selected,
  suggestions = [],
  stats = [],
  canPick,
  onAdd,
  onRemove,
  onReindex,
}) => {
  const toast = useToast();
  const [typed, setTyped] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [shakeKey, setShakeKey] = useState(0);
  const [extra, setExtra] = useState<string[]>([]);

  // Draft mode keeps unticked rows on screen so that the check animation is visible
  const rows = useMemo(() => {
    if (mode === 'live') return selected.map(p => ({ path: p, label: folderLabel(p) }));
    const list: { path: string; label: string }[] = [];
    const push = (path: string, label: string) => {
      if (!list.some(r => sameKey(r.path, path))) list.push({ path, label });
    };
    selected.forEach(p => push(p, folderLabel(p)));
    extra.forEach(p => push(p, folderLabel(p)));
    suggestions.forEach(s => push(s.path, s.label));
    return list;
  }, [mode, selected, suggestions, extra]);

  const isSelected = (p: string) => selected.some(s => sameKey(s, p));
  const statFor = (p: string) => stats.find(s => sameKey(s.path, p));

  const validateAndAdd = async (paths: string[]) => {
    const accepted: string[] = [];
    let lastWarning: string | null = null;
    for (const raw of paths) {
      try {
        const res = await api.checkFolder(raw, [...selected, ...accepted]);
        if (!res.ok) {
          setError(res.error ?? 'This folder cannot be added.');
          setShakeKey(k => k + 1);
          return false;
        }
        accepted.push(res.path);
        if (res.warning) lastWarning = res.warning;
      } catch (e) {
        setError((e as Error).message);
        setShakeKey(k => k + 1);
        return false;
      }
    }
    if (!accepted.length) return false;
    setError(null);
    setWarning(lastWarning);
    setExtra(x => [...x, ...accepted]);
    await onAdd(accepted);
    return true;
  };

  const pick = async () => {
    const paths = await api.pickFolders();
    if (paths === null) {
      toast('Type or paste the folder path in the field.', 'info');
      return;
    }
    if (paths.length) await validateAndAdd(paths);
  };

  const submitTyped = async () => {
    if (!typed.trim()) return;
    if (await validateAndAdd([typed])) setTyped('');
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col rounded-xl overflow-hidden panel">
        {rows.length === 0 && (
          <div className="px-4 py-6 text-center text-[12.5px] text-fg-3">No folders yet. Add the folders that you want to search.</div>
        )}
        {rows.map((row, i) => {
          const checked = isSelected(row.path);
          const st = statFor(row.path);
          const isDrive = /^[A-Za-z]:\\?$/.test(row.path);
          const Icon = isDrive ? HardDrive : Folder;
          return (
            <div
              key={row.path}
              className="group relative flex items-center gap-3 h-[52px] px-3.5 fade-up"
              style={{ ['--d' as string]: `${i * 45}ms`, borderTop: i ? '1px solid var(--line)' : undefined }}
            >
              {mode === 'draft' ? (
                <button
                  type="button"
                  onClick={() => (checked ? onRemove(row.path) : validateAndAdd([row.path]))}
                  className="absolute inset-0 hover:bg-[rgba(255,255,255,0.025)] transition-colors"
                  aria-pressed={checked}
                  aria-label={`${checked ? 'Remove' : 'Add'} ${row.path}`}
                />
              ) : null}
              {mode === 'draft' && <span className="relative pointer-events-none"><AnimatedCheckbox checked={checked} /></span>}
              <span
                className="relative pointer-events-none flex items-center justify-center w-8 h-8 rounded-lg shrink-0 transition-colors duration-200"
                style={{
                  background: checked || mode === 'live' ? 'var(--accent-soft)' : 'var(--surface-2)',
                  color: checked || mode === 'live' ? 'var(--accent)' : 'var(--text-3)',
                }}
              >
                <Icon className="w-4 h-4" />
              </span>
              <div className="relative pointer-events-none flex flex-col min-w-0 flex-1">
                <span className={`truncate text-[13px] font-medium transition-colors ${checked || mode === 'live' ? 'text-fg' : 'text-fg-2'}`}>
                  {row.label}
                </span>
                <span className="truncate font-mono text-[11px] text-fg-3">{row.path}</span>
              </div>

              {mode === 'live' && st && (
                <div className="relative flex items-center gap-2 shrink-0 text-[11.5px]">
                  {!st.exists ? (
                    <span className="flex items-center gap-1 text-warn"><AlertTriangle className="w-3.5 h-3.5" /> Not found</span>
                  ) : st.state === 'scanning' || st.state === 'queued' ? (
                    <span className="flex items-center gap-1.5 text-accent">
                      <span className="w-3 h-3 rounded-full spin" style={{ border: '1.5px solid var(--line-strong)', borderTopColor: 'var(--accent)' }} />
                      {st.state === 'queued' ? 'Queued' : 'Scanning'}
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-fg-3">
                      <Check className="w-3.5 h-3.5 text-ok" />
                      <RollingNumber value={st.files} className="text-fg-2" /> files
                    </span>
                  )}
                </div>
              )}

              {mode === 'live' && (
                <div className="relative flex items-center gap-1 shrink-0 opacity-60 group-hover:opacity-100 transition-opacity">
                  {onReindex && (
                    <button type="button" className="icon-btn" title="Scan this folder again" onClick={() => onReindex(row.path)}>
                      <RefreshCw className="w-3.5 h-3.5" />
                    </button>
                  )}
                  <HoldButton
                    onConfirm={() => onRemove(row.path)}
                    onShortPress={() => toast('Hold the button to remove the folder', 'info')}
                    title="Hold to remove this folder and its index entries"
                    className="!h-7 !px-2 !bg-transparent !shadow-none text-fg-3"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    <span className="text-[11.5px]">Remove</span>
                  </HoldButton>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-2">
        <button type="button" className="btn shrink-0" onClick={pick} title={canPick ? 'Choose folders in a dialog' : 'Opens a dialog in the desktop app'}>
          <FolderPlus className="w-4 h-4" />
          Add folder…
        </button>
        <div key={shakeKey} className={`flex-1 ${shakeKey ? 'shake' : ''}`}>
          <input
            className="input font-mono text-[12px]"
            placeholder="or paste a path, for example D:\Projects"
            value={typed}
            onChange={e => {
              setTyped(e.target.value);
              setError(null);
            }}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                e.preventDefault();
                e.stopPropagation();
                submitTyped();
              }
            }}
            spellCheck={false}
          />
        </div>
        <button type="button" className="btn shrink-0" onClick={submitTyped} disabled={!typed.trim()}>
          Add
        </button>
      </div>
      {(error || warning) && (
        <div
          className="flex items-center gap-2 text-[12px] fade-up"
          style={{ color: error ? 'var(--danger)' : 'var(--warn)', animationDuration: '280ms' }}
        >
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          {error ?? warning}
        </div>
      )}
    </div>
  );
};
