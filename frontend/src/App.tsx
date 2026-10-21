import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FileCode2, FileText, Image as ImageIcon, Layers, SearchX, Sheet, Sparkles } from 'lucide-react';
import { api, Category, FolderDetails, IndexerStatus, SearchItem, SearchMode } from './api';
import { TitleBar } from './components/TitleBar';
import { CommandBar } from './components/CommandBar';
import { ResultsList } from './components/ResultsList';
import { QuickLookModal } from './components/QuickLookModal';
import { Onboarding } from './components/Onboarding';
import { FoldersPanel } from './components/FoldersPanel';
import { ToastProvider, useToast } from './components/Toasts';
import { SegmentedControl } from './components/motion/SegmentedControl';
import { RollingNumber } from './components/motion/RollingNumber';
import { folderLabel } from './utils/paths';

type View = 'loading' | 'onboarding' | 'search';

const CATEGORIES = [
  { id: 'all' as const, label: 'All', icon: Layers, hint: 'Ctrl+1' },
  { id: 'code' as const, label: 'Code', icon: FileCode2, hint: 'Ctrl+2' },
  { id: 'docs' as const, label: 'Docs', icon: FileText, hint: 'Ctrl+3: Word, PowerPoint, PDF, Markdown, EPUB, text' },
  { id: 'data' as const, label: 'Data', icon: Sheet, hint: 'Ctrl+4: Excel, CSV, TSV' },
  { id: 'media' as const, label: 'Images', icon: ImageIcon, hint: 'Ctrl+5' },
];

function Workspace() {
  const toast = useToast();
  const [view, setView] = useState<View>('loading');
  const [details, setDetails] = useState<FolderDetails | null>(null);
  const [status, setStatus] = useState<IndexerStatus | null>(null);
  const [onboardAtIndexing, setOnboardAtIndexing] = useState(false);
  const [foldersOpen, setFoldersOpen] = useState(false);

  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<SearchMode>('all');
  const [category, setCategory] = useState<Category>('all');
  const [scope, setScope] = useState<string | null>(null);
  const [items, setItems] = useState<SearchItem[]>([]);
  const [tookMs, setTookMs] = useState(0);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState(0);
  const [keyboardFocus, setKeyboardFocus] = useState(false);
  const [quickLook, setQuickLook] = useState<{ open: boolean; origin: DOMRect | null }>({ open: false, origin: null });
  const [refreshTick, setRefreshTick] = useState(0);

  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const lastRefresh = useRef(0);
  const lastTotal = useRef(0);

  const folders = useMemo(() => details?.folders.map(f => f.path) ?? [], [details]);

  const loadDetails = useCallback(async () => {
    try {
      const d = await api.folders();
      setDetails(d);
      return d;
    } catch {
      return null;
    }
  }, []);

  // Start: setup screen until working folders exist
  useEffect(() => {
    loadDetails().then(d => {
      if (!d) return;
      setView(d.setup_done && d.folders.length ? 'search' : 'onboarding');
    });
  }, [loadDetails]);

  // Poll indexer status: fast while work runs, slow when idle, very slow while hidden in the tray
  const hiddenRef = useRef(false);
  useEffect(() => {
    const onHidden = () => { hiddenRef.current = true; };
    const onShown = () => { hiddenRef.current = false; };
    window.addEventListener('peekgrep:hidden', onHidden);
    window.addEventListener('peekgrep:shown', onShown);
    return () => {
      window.removeEventListener('peekgrep:hidden', onHidden);
      window.removeEventListener('peekgrep:shown', onShown);
    };
  }, []);

  useEffect(() => {
    let alive = true;
    let timer = 0;
    const tick = async () => {
      try {
        const s = await api.indexer();
        if (!alive) return;
        setStatus(s);
        const now = Date.now();
        if (s.total_indexed !== lastTotal.current && now - lastRefresh.current > 1500) {
          lastTotal.current = s.total_indexed;
          lastRefresh.current = now;
          setRefreshTick(t => t + 1);
        }
        timer = window.setTimeout(tick, hiddenRef.current ? 30000 : s.phase === 'ready' ? 4000 : 900);
      } catch {
        timer = window.setTimeout(tick, 2000);
      }
    };
    tick();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, []);

  // Search with a short debounce; stale requests are cancelled
  useEffect(() => {
    if (view !== 'search') return;
    const ctrl = new AbortController();
    const timer = window.setTimeout(async () => {
      setBusy(true);
      try {
        const res = await api.search({ q: query, mode, type: category, folder: scope }, ctrl.signal);
        setItems(res.results);
        setTookMs(res.took_ms);
        setSelected(prev => (prev < res.results.length ? prev : 0));
      } catch (e) {
        if (!ctrl.signal.aborted) console.error(e);
      } finally {
        if (!ctrl.signal.aborted) setBusy(false);
      }
    }, query ? 110 : 0);
    return () => {
      ctrl.abort();
      window.clearTimeout(timer);
    };
  }, [query, mode, category, scope, view, refreshTick]);

  // New query: start at the top
  useEffect(() => setSelected(0), [query, mode, category, scope]);

  const selectedItem = items[selected] ?? null;

  const openItem = useCallback(async (item: SearchItem) => {
    try {
      await api.open(item.path);
      toast(`Opening ${item.filename}`);
    } catch (e) {
      toast((e as Error).message, 'error');
    }
  }, [toast]);

  const revealItem = useCallback(async (item: SearchItem) => {
    try {
      await api.reveal(item.path);
      toast('Shown in Explorer');
    } catch (e) {
      toast((e as Error).message, 'error');
    }
  }, [toast]);

  const copyPath = useCallback(async (item: SearchItem) => {
    try {
      await navigator.clipboard.writeText(item.path);
      toast('Path copied');
    } catch {
      toast('Could not copy the path', 'error');
    }
  }, [toast]);

  const openQuickLook = useCallback((idx: number) => {
    if (!items[idx]) return;
    setSelected(idx);
    const row = document.getElementById(`row-${idx}`);
    setQuickLook({ open: true, origin: row ? row.getBoundingClientRect() : null });
  }, [items]);

  const closeQuickLook = useCallback(() => {
    setQuickLook({ open: false, origin: null });
    requestAnimationFrame(() => listRef.current?.focus());
  }, []);

  const move = useCallback((dir: 1 | -1) => {
    if (!items.length) return;
    setKeyboardFocus(true);
    setSelected(i => Math.min(items.length - 1, Math.max(0, i + dir)));
  }, [items.length]);

  // Desktop window events (tray menu, hotkey)
  useEffect(() => {
    const onFolders = () => {
      if (view === 'search') setFoldersOpen(true);
    };
    const onShown = () => {
      if (view === 'search') {
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    };
    window.addEventListener('peekgrep:open-folders', onFolders);
    window.addEventListener('peekgrep:shown', onShown);
    return () => {
      window.removeEventListener('peekgrep:open-folders', onFolders);
      window.removeEventListener('peekgrep:shown', onShown);
    };
  }, [view]);

  // Links inside previews must never navigate the app window away
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      const a = (e.target as HTMLElement).closest('a');
      if (a && !a.getAttribute('href')?.startsWith('#')) e.preventDefault();
    };
    document.addEventListener('click', onClick);
    return () => document.removeEventListener('click', onClick);
  }, []);

  // Keyboard model: arrows move, Space previews, Enter opens, Esc steps back
  useEffect(() => {
    if (view !== 'search' || foldersOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (document.body.dataset.editing === '1') return; // the Quick Look editor has the keyboard
      const active = document.activeElement as HTMLElement | null;
      const inSearch = active === inputRef.current;
      const inOtherField = !inSearch && !!active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA');
      const hasTextSelection = (window.getSelection()?.toString() ?? '') !== '' ||
        (inSearch && inputRef.current!.selectionStart !== inputRef.current!.selectionEnd);

      if (quickLook.open) {
        if (inOtherField) return;
        if (e.key === 'Escape' || e.key === ' ') {
          e.preventDefault();
          closeQuickLook();
        } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
          e.preventDefault();
          move(e.key === 'ArrowDown' ? 1 : -1);
        } else if (e.key === 'Enter' && selectedItem) {
          e.preventDefault();
          if (e.ctrlKey) revealItem(selectedItem);
          else openItem(selectedItem);
        } else if (e.key.toLowerCase() === 'c' && e.ctrlKey && !hasTextSelection && selectedItem) {
          e.preventDefault();
          copyPath(selectedItem);
        }
        return;
      }

      if (inOtherField) return;

      if (e.ctrlKey && /^[1-5]$/.test(e.key)) {
        e.preventDefault();
        setCategory(CATEGORIES[Number(e.key) - 1].id);
        return;
      }
      if ((e.ctrlKey && (e.key.toLowerCase() === 'k' || e.key.toLowerCase() === 'f')) || (e.key === '/' && !inSearch)) {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        if (query) {
          setQuery('');
          inputRef.current?.focus();
        } else if (scope) {
          setScope(null);
        } else {
          api.hideWindow();
        }
        return;
      }
      if (e.key.toLowerCase() === 'c' && e.ctrlKey && !hasTextSelection && selectedItem) {
        e.preventDefault();
        copyPath(selectedItem);
        return;
      }
      if (inSearch) return; // the input handles arrows and Enter itself

      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        move(e.key === 'ArrowDown' ? 1 : -1);
      } else if (e.key === ' ' && selectedItem) {
        e.preventDefault();
        openQuickLook(selected);
      } else if (e.key === 'Enter' && selectedItem) {
        e.preventDefault();
        if (e.ctrlKey) revealItem(selectedItem);
        else openItem(selectedItem);
      } else if ((e.key.length === 1 || e.key === 'Backspace') && !e.ctrlKey && !e.altKey && !e.metaKey) {
        // Typing anywhere goes to the search field
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [view, foldersOpen, quickLook.open, query, scope, selected, selectedItem, move, openItem, revealItem, copyPath, openQuickLook, closeQuickLook]);

  // Corner grip to resize the frameless window
  const startResize = (e: React.PointerEvent) => {
    e.preventDefault();
    const startX = e.screenX;
    const startY = e.screenY;
    const w0 = window.outerWidth;
    const h0 = window.outerHeight;
    let frame = 0;
    const onMove = (ev: PointerEvent) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => api.resizeWindow(w0 + ev.screenX - startX, h0 + ev.screenY - startY));
    };
    const onUp = () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  };

  const refreshAfterChange = async () => {
    const d = await loadDetails();
    if (d && !d.folders.length) {
      setFoldersOpen(false);
      setOnboardAtIndexing(false);
      setView('onboarding');
    }
    if (scope && d && !d.folders.some(f => f.path === scope)) setScope(null);
    setRefreshTick(t => t + 1);
  };

  const indexing = status?.phase === 'scanning' || status?.phase === 'reading';

  const emptyState = () => {
    if (busy && !items.length) return null;
    if (!query && indexing) {
      return (
        <div className="flex flex-col items-center gap-3 text-center fade-up">
          <span className="w-6 h-6 rounded-full spin" style={{ border: '2px solid var(--line-strong)', borderTopColor: 'var(--accent)' }} />
          <div className="text-[13px] text-fg">Scanning your folders</div>
          <div className="text-[12px] text-fg-3 max-w-[300px]">Files show up here as soon as they are found.</div>
        </div>
      );
    }
    if (!query) {
      return (
        <div className="flex flex-col items-center gap-3 text-center fade-up">
          <Sparkles className="w-6 h-6 text-fg-3" />
          <div className="text-[13px] text-fg">No files here yet</div>
          <div className="text-[12px] text-fg-3">Add a folder with files, or choose another type.</div>
        </div>
      );
    }
    return (
      <div className="flex flex-col items-center gap-3 text-center fade-up" style={{ animationDuration: '360ms' }}>
        <SearchX className="w-6 h-6 text-fg-3" />
        <div className="text-[13px] text-fg">No matches for “{query}”</div>
        <div className="flex flex-wrap items-center justify-center gap-2 mt-1">
          {category !== 'all' && <button type="button" className="btn !h-7" onClick={() => setCategory('all')}>Search all types</button>}
          {scope && <button type="button" className="btn !h-7" onClick={() => setScope(null)}>Search all folders</button>}
          {mode !== 'all' && <button type="button" className="btn !h-7" onClick={() => setMode('all')}>Names and text</button>}
          {status?.phase === 'reading' && <span className="text-[12px] text-fg-3">Text is still being read in some files.</span>}
        </div>
      </div>
    );
  };

  return (
    <div className="relative flex flex-col h-full overflow-hidden" style={{ background: 'radial-gradient(1200px 500px at 50% -220px, rgba(124,156,255,0.07), transparent 70%), var(--bg)' }}>
      <TitleBar
        status={status}
        showFolderButton={view === 'search'}
        onOpenFolders={() => setFoldersOpen(true)}
        onReindexAll={async () => {
          try {
            await api.reindex();
            toast('Scanning all folders again');
          } catch (e) {
            toast((e as Error).message, 'error');
          }
        }}
        onHide={() => api.hideWindow()}
        onMaximize={() => api.toggleMaximize()}
        onOpenDataFolder={() => api.openDataFolder()}
        onQuit={() => api.quit()}
      />

      {view === 'loading' && <div className="flex-1" />}

      {view === 'onboarding' && (
        <Onboarding
          details={details}
          status={status}
          startAtIndexing={onboardAtIndexing}
          onSaved={() => {
            loadDetails();
            setOnboardAtIndexing(true);
          }}
          onFinish={() => {
            setView('search');
            requestAnimationFrame(() => inputRef.current?.focus());
          }}
        />
      )}

      {view === 'search' && (
        <>
          <div className="flex flex-col gap-3 px-4 pt-3 pb-2 shrink-0 fade-up" style={{ animationDuration: '420ms' }}>
            <CommandBar
              query={query}
              onQueryChange={setQuery}
              mode={mode}
              onModeChange={setMode}
              scope={scope}
              onScopeChange={setScope}
              folders={folders}
              busy={busy}
              inputRef={inputRef}
              onArrow={dir => {
                move(dir);
                listRef.current?.focus();
              }}
              onSubmit={e => {
                if (selectedItem) {
                  e.preventDefault();
                  if (e.ctrlKey) revealItem(selectedItem);
                  else openItem(selectedItem);
                }
              }}
            />
            <div className="flex items-center justify-between gap-3">
              <SegmentedControl options={CATEGORIES} value={category} onChange={setCategory} size="sm" />
              <div className="flex items-center gap-2 text-[11.5px] text-fg-3 whitespace-nowrap">
                <span className="label-caps !text-[10px]">{query ? 'Best matches' : 'Recently changed'}</span>
                <span className="w-1 h-1 rounded-full bg-line-strong" />
                <span>
                  <RollingNumber value={items.length} className="font-mono text-fg-2" /> results
                </span>
                {query && <span className="font-mono">{tookMs.toFixed(0)} ms</span>}
              </div>
            </div>
          </div>

          <div className="relative flex-1 min-h-0 flex flex-col" onPointerMove={() => keyboardFocus && setKeyboardFocus(false)}>
            {busy && items.length > 0 && <div className="absolute top-0 left-4 right-4 h-px overflow-hidden loading-line z-10" />}
            <ResultsList
              items={items}
              selectedIndex={selected}
              onSelect={idx => {
                setSelected(idx);
                listRef.current?.focus();
              }}
              onOpen={openItem}
              onPreview={openQuickLook}
              query={query}
              folders={folders}
              keyboardFocus={keyboardFocus}
              listRef={listRef}
              empty={emptyState()}
            />
          </div>

          <footer className="flex items-center justify-between gap-4 h-9 px-4 shrink-0 text-[11.5px] text-fg-3" style={{ borderTop: '1px solid var(--line)' }}>
            <div className="flex items-center gap-3.5 overflow-hidden whitespace-nowrap">
              <span className="flex items-center gap-1.5"><span className="kbd">↑</span><span className="kbd">↓</span> Move</span>
              <span className="flex items-center gap-1.5"><span className="kbd">Space</span> Preview</span>
              <span className="flex items-center gap-1.5"><span className="kbd">↵</span> Open</span>
              <span className="flex items-center gap-1.5"><span className="kbd">Ctrl</span><span className="kbd">↵</span> Show in folder</span>
              <span className="hidden md:flex items-center gap-1.5"><span className="kbd">Ctrl</span><span className="kbd">C</span> Copy path</span>
            </div>
            <div className="flex items-center gap-1.5 whitespace-nowrap" title={folders.join('\n')}>
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: status?.watcher_active ? 'var(--ok)' : 'var(--text-3)' }} />
              {scope ? `In ${folderLabel(scope)}` : `Watching ${folders.length} folder${folders.length === 1 ? '' : 's'}`}
            </div>
          </footer>
        </>
      )}

      {quickLook.open && selectedItem && (
        <QuickLookModal
          item={selectedItem}
          originRect={quickLook.origin}
          folders={folders}
          position={{ index: selected, total: items.length }}
          onClose={closeQuickLook}
          onOpen={openItem}
          onReveal={revealItem}
          onCopyPath={copyPath}
          query={query}
        />
      )}

      <FoldersPanel
        open={foldersOpen}
        details={details}
        status={status}
        onClose={() => {
          setFoldersOpen(false);
          requestAnimationFrame(() => inputRef.current?.focus());
        }}
        onChanged={refreshAfterChange}
      />

      <div
        onPointerDown={startResize}
        className="absolute bottom-0 right-0 w-4 h-4 z-[70] cursor-nwse-resize text-fg-3 opacity-40 hover:opacity-100 transition-opacity"
        title="Drag to resize"
      >
        <svg viewBox="0 0 16 16" className="w-full h-full" fill="currentColor">
          <path d="M13 13h-2v-2h2zm0-4h-2V7h2zm-4 4H7v-2h2z" />
        </svg>
      </div>
    </div>
  );
}

export function App() {
  return (
    <ToastProvider>
      <Workspace />
    </ToastProvider>
  );
}

export default App;
