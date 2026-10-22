import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronsDownUp, ChevronsUpDown, ClipboardList, FileCode2, FileText, Image as ImageIcon, Layers, Pencil, SearchX, Sheet, Sparkles, X } from 'lucide-react';
import { api, AppSettings, Category, ExplainChip, FolderDetails, IndexerStatus, SearchItem } from './api';
import { TitleBar } from './components/TitleBar';
import { CommandBar } from './components/CommandBar';
import { ResultsList, Row } from './components/ResultsList';
import { KeyHint, QuickLookModal } from './components/QuickLookModal';
import { Onboarding } from './components/Onboarding';
import { FoldersPanel } from './components/FoldersPanel';
import { ListEditor } from './components/ListEditor';
import { ShortcutsPanel } from './components/ShortcutsPanel';
import { SearchSettingsPanel } from './components/SearchSettingsPanel';
import { chipsWorthShowing, QueryChips } from './components/QueryHints';
import { ToastProvider, useToast } from './components/Toasts';
import { SegmentedControl } from './components/motion/SegmentedControl';
import { RollingNumber } from './components/motion/RollingNumber';
import { folderLabel } from './utils/paths';
import { HighlightTerm, ListMode, listToQuery, ListWhere, parseClipboardGrid, isListPaste } from './utils/query';
import { canWriteLists, DEFAULT_SEARCH_OPTIONS, SearchOptions } from './utils/searchOptions';
import { ActionId, bindingParts, buildKeymap, DEFAULT_KEYMAP, eventToBinding, isTypingKey, Keymap, keymapOverrides } from './utils/keymap';

type View = 'loading' | 'onboarding' | 'search';

const CATEGORIES = [
  { id: 'all' as const, label: 'All', icon: Layers, hint: 'All file types' },
  { id: 'code' as const, label: 'Code', icon: FileCode2, hint: 'Code' },
  { id: 'docs' as const, label: 'Docs', icon: FileText, hint: 'Word, PowerPoint, PDF, Markdown, EPUB, text' },
  { id: 'data' as const, label: 'Data', icon: Sheet, hint: 'Excel, CSV, TSV' },
  { id: 'media' as const, label: 'Images', icon: ImageIcon, hint: 'Images' },
];

/** One list of results: the whole search, or one group of [a, b]. */
interface ListState {
  label: string;
  items: SearchItem[];
  total: number;
  hasMore: boolean;
  loading: boolean;
  highlight: HighlightTerm[];
}

const EMPTY_LIST: ListState = { label: '', items: [], total: 0, hasMore: false, loading: false, highlight: [] };

/** A list searched from the list table: its values stay visible under the search field. */
interface PastedList {
  values: string[];
  mode: ListMode;
  where: ListWhere;
  filter: string;
  query: string;
}

function appendUnique(items: SearchItem[], more: SearchItem[]): SearchItem[] {
  const seen = new Set(items.map(i => i.path));
  return [...items, ...more.filter(i => !seen.has(i.path))];
}

function Workspace() {
  const toast = useToast();
  const [view, setView] = useState<View>('loading');
  const [details, setDetails] = useState<FolderDetails | null>(null);
  const [status, setStatus] = useState<IndexerStatus | null>(null);
  const [onboardAtIndexing, setOnboardAtIndexing] = useState(false);
  const [foldersOpen, setFoldersOpen] = useState(false);

  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<Category>('all');
  const [scope, setScope] = useState<string | null>(null);
  const [flat, setFlat] = useState<ListState>(EMPTY_LIST);
  const [groups, setGroups] = useState<ListState[] | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [chips, setChips] = useState<ExplainChip[]>([]);
  const [tookMs, setTookMs] = useState(0);
  const [busy, setBusy] = useState(false);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [keyboardFocus, setKeyboardFocus] = useState(false);
  const [quickLook, setQuickLook] = useState<{ open: boolean; origin: DOMRect | null }>({ open: false, origin: null });
  const [refreshTick, setRefreshTick] = useState(0);

  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [keymap, setKeymap] = useState<Keymap>(DEFAULT_KEYMAP);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [searchSettingsOpen, setSearchSettingsOpen] = useState(false);
  const [searchOpts, setSearchOpts] = useState<SearchOptions>(DEFAULT_SEARCH_OPTIONS);
  const [listEditor, setListEditor] = useState<{ grid: string[][]; mode: ListMode; where: ListWhere; filter: string; source: 'paste' | 'edit' | 'new' } | null>(null);
  const [pasted, setPasted] = useState<PastedList | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const lastRefresh = useRef(0);
  const lastTotal = useRef(0);
  const searchGen = useRef(0);
  const lastSearchKey = useRef('');
  const flatRef = useRef(flat);
  const groupsRef = useRef(groups);
  flatRef.current = flat;
  groupsRef.current = groups;

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

  // Keyboard shortcuts from data\settings.json
  useEffect(() => {
    api.settings()
      .then(s => {
        setSettings(s);
        setKeymap(buildKeymap(s.shortcuts));
        if (s.search) setSearchOpts(s.search);
      })
      .catch(() => {});
  }, []);

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

  // Search with a short debounce; stale requests are cancelled. A refresh (the index changed)
  // keeps the rows that are already loaded.
  useEffect(() => {
    if (view !== 'search') return;
    const ctrl = new AbortController();
    const key = JSON.stringify([query, category, scope]);
    const refresh = key === lastSearchKey.current;
    lastSearchKey.current = key;
    const timer = window.setTimeout(async () => {
      const gen = ++searchGen.current;
      setBusy(true);
      try {
        const page = searchOpts.page_size;
        const keep = refresh ? Math.min(500, Math.max(page, flatRef.current.items.length)) : page;
        const res = await api.search({ q: query, type: category, folder: scope, limit: keep }, ctrl.signal);
        if (gen !== searchGen.current) return;
        if (res.grouped) {
          setGroups(res.groups.map(g => ({
            label: g.label, items: g.results, total: g.total, hasMore: g.has_more, loading: false, highlight: g.highlight,
          })));
          setFlat(EMPTY_LIST);
          if (!refresh) {
            // As set: one group opens by itself and several start closed, or all open, or all closed
            const labels = res.groups.map(g => g.label);
            setExpanded(prev => {
              if (searchOpts.groups_open === 'all') return new Set(labels);
              if (searchOpts.groups_open === 'none') return new Set([...prev].filter(l => labels.includes(l)));
              return labels.length === 1 ? new Set(labels) : new Set([...prev].filter(l => labels.includes(l)));
            });
          }
        } else {
          setGroups(null);
          setFlat({ label: '', items: res.results, total: res.total, hasMore: res.has_more, loading: false, highlight: res.highlight });
        }
        setChips(res.explain);
        setTookMs(res.took_ms);
        if (!refresh) setSelectedKey(null);
      } catch (e) {
        if (!ctrl.signal.aborted) console.error(e);
      } finally {
        if (!ctrl.signal.aborted) setBusy(false);
      }
    }, query ? searchOpts.search_delay_ms : 0);
    return () => {
      ctrl.abort();
      window.clearTimeout(timer);
    };
  }, [query, category, scope, view, refreshTick, searchOpts]);

  // Next page of the whole list (group null) or of one group
  const loadMore = useCallback(async (group: number | null) => {
    const list = group === null ? flatRef.current : groupsRef.current?.[group];
    if (!list || list.loading || !list.hasMore) return;
    const gen = searchGen.current;
    const update = (fn: (l: ListState) => ListState) => {
      if (group === null) setFlat(l => fn(l));
      else setGroups(gs => gs && gs.map((g, i) => (i === group ? fn(g) : g)));
    };
    update(l => ({ ...l, loading: true }));
    try {
      const res = await api.search({ q: query, type: category, folder: scope, offset: list.items.length, limit: searchOpts.page_size, group });
      if (gen !== searchGen.current) return;
      update(l => ({ ...l, items: appendUnique(l.items, res.results), total: res.total, hasMore: res.has_more, loading: false }));
    } catch {
      if (gen === searchGen.current) update(l => ({ ...l, loading: false, hasMore: false }));
    }
  }, [query, category, scope, searchOpts.page_size]);

  // Rows on screen: files, or group rows with their files when open
  const rows = useMemo<Row[]>(() => {
    if (!groups) {
      const out: Row[] = flat.items.map((item, index) => ({ kind: 'item', key: `i::${item.path}`, item, group: null, index }));
      if (flat.hasMore) out.push({ kind: 'more', key: 'm:', group: null, loading: flat.loading });
      return out;
    }
    const out: Row[] = [];
    groups.forEach((g, gi) => {
      const open = expanded.has(g.label);
      out.push({ kind: 'header', key: `h:${gi}`, group: gi, label: g.label, total: g.total, expanded: open, loading: g.loading });
      if (!open) return;
      g.items.forEach((item, index) => out.push({ kind: 'item', key: `i:${gi}:${item.path}`, item, group: gi, index }));
      if (g.hasMore) out.push({ kind: 'more', key: `m:${gi}`, group: gi, loading: g.loading });
    });
    return out;
  }, [groups, flat, expanded]);

  const found = rows.findIndex(r => r.key === selectedKey);
  const selected = found >= 0 ? found : rows.findIndex(r => r.kind !== 'more');
  const selectedRow = selected >= 0 ? rows[selected] : null;
  const selectedItem = selectedRow?.kind === 'item' ? selectedRow.item : null;
  const totalFiles = groups ? groups.reduce((n, g) => n + g.total, 0) : flat.total;

  const termsFor = useCallback(
    (group: number | null) => (group === null ? flat.highlight : groups?.[group]?.highlight ?? []),
    [flat.highlight, groups],
  );

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

  const toggleGroup = useCallback((group: number, open?: boolean) => {
    const label = groupsRef.current?.[group]?.label;
    if (label === undefined) return;
    setExpanded(prev => {
      const next = new Set(prev);
      const want = open ?? !next.has(label);
      if (want) next.add(label);
      else next.delete(label);
      return next;
    });
  }, []);

  const toggleAllGroups = useCallback(() => {
    const gs = groupsRef.current;
    if (!gs) return;
    setExpanded(prev => (gs.every(g => prev.has(g.label)) ? new Set() : new Set(gs.map(g => g.label))));
  }, []);

  const openQuickLook = useCallback((idx: number) => {
    const row = rows[idx];
    if (!row || row.kind !== 'item') return;
    setSelectedKey(row.key);
    const el = document.getElementById(`row-${idx}`);
    setQuickLook({ open: true, origin: el ? el.getBoundingClientRect() : null });
  }, [rows]);

  const closeQuickLook = useCallback(() => {
    setQuickLook({ open: false, origin: null });
    requestAnimationFrame(() => listRef.current?.focus());
  }, []);

  /** Move the selection. onlyFiles: skip group rows (Quick Look). Near the end the next page loads. */
  const move = useCallback((dir: 1 | -1, onlyFiles = false) => {
    if (!rows.length) return;
    setKeyboardFocus(true);
    let j = selected;
    for (let k = selected + dir; k >= 0 && k < rows.length; k += dir) {
      const r = rows[k];
      if (r.kind === 'more' || (onlyFiles && r.kind !== 'item')) continue;
      j = k;
      break;
    }
    if (rows[j]) setSelectedKey(rows[j].key);
    // Prefetch: a "more" row a few rows ahead
    for (let k = j; k < Math.min(rows.length, j + 6); k++) {
      const r = rows[k];
      if (r.kind === 'more') loadMore(r.group);
    }
  }, [rows, selected, loadMore]);

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

  const overlayOpen = foldersOpen || shortcutsOpen || searchSettingsOpen || listEditor !== null;

  const openListEditor = useCallback((grid: string[][], source: 'paste' | 'edit' | 'new') => {
    setListEditor({
      grid, source,
      mode: pasted?.mode ?? searchOpts.list_mode,
      where: pasted?.where ?? searchOpts.list_where,
      filter: pasted?.filter ?? '',
    });
  }, [pasted, searchOpts.list_mode, searchOpts.list_where]);

  const confirmList = (values: string[], listMode: ListMode, where: ListWhere, filter: string) => {
    const q = listToQuery(values, listMode, where, filter, searchOpts);
    setPasted({ values, mode: listMode, where, filter, query: q });
    setQuery(q);
    setListEditor(null);
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  /** Cells pasted from Excel: the table, a search at once, or plain text (as set). */
  const pasteList = useCallback((grid: string[][], source: 'paste' | 'edit' | 'new' = 'paste') => {
    const cells = grid.flat().map(c => c.replace(/\s+/g, ' ').trim()).filter(Boolean);
    if (!canWriteLists(searchOpts) || searchOpts.paste_list === 'text') {
      setQuery(q => (q.trim() ? `${q.trim()} ` : '') + cells.join(' '));
      requestAnimationFrame(() => inputRef.current?.focus());
      return;
    }
    if (searchOpts.paste_list === 'groups' && source === 'paste') {
      const seen = new Set<string>();
      const values = cells.filter(c => !seen.has(c.toLowerCase()) && seen.add(c.toLowerCase()));
      const q = listToQuery(values, searchOpts.list_mode, searchOpts.list_where, '', searchOpts);
      setPasted({ values, mode: searchOpts.list_mode, where: searchOpts.list_where, filter: '', query: q });
      setQuery(q);
      return;
    }
    openListEditor(grid, source);
  }, [searchOpts, openListEditor]);

  // Paste while the list (not a text field) has the focus: a list opens the table, text goes to the search
  useEffect(() => {
    if (view !== 'search') return;
    const onPaste = (e: ClipboardEvent) => {
      if (overlayOpen || quickLook.open) return;
      const active = document.activeElement as HTMLElement | null;
      if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.isContentEditable)) return;
      const text = e.clipboardData?.getData('text/plain') ?? '';
      if (!text) return;
      e.preventDefault();
      if (isListPaste(text)) pasteList(parseClipboardGrid(text));
      else {
        setQuery(q => q + text.replace(/[\r\n]+/g, ' ').trim());
        inputRef.current?.focus();
      }
    };
    document.addEventListener('paste', onPaste);
    return () => document.removeEventListener('paste', onPaste);
  }, [view, overlayOpen, quickLook.open, pasteList]);

  // Keyboard model (keys from the keymap): arrows move, Space previews, Enter opens, Esc steps back
  useEffect(() => {
    if (view !== 'search' || overlayOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (document.body.dataset.editing === '1' || e.isComposing) return; // the Quick Look editor has the keyboard
      const active = document.activeElement as HTMLElement | null;
      const inSearch = active === inputRef.current;
      const inOtherField = !inSearch && !!active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.isContentEditable);
      const hasTextSelection = (window.getSelection()?.toString() ?? '') !== '' ||
        (inSearch && inputRef.current!.selectionStart !== inputRef.current!.selectionEnd);
      const binding = eventToBinding(e);
      if (!binding) return;
      const is = (id: ActionId) => keymap[id].includes(binding) && !(inSearch && isTypingKey(binding));
      const stop = () => e.preventDefault();

      if (quickLook.open) {
        if (inOtherField) return;
        if (is('close_preview') || is('preview')) { stop(); closeQuickLook(); }
        else if (is('move_down') || is('move_up')) { stop(); move(is('move_down') ? 1 : -1, true); }
        else if (is('reveal') && selectedItem) { stop(); revealItem(selectedItem); }
        else if (is('open') && selectedItem) { stop(); openItem(selectedItem); }
        else if (is('copy_path') && !hasTextSelection && selectedItem) { stop(); copyPath(selectedItem); }
        return;
      }
      if (inOtherField) return;

      for (let n = 1; n <= 5; n++) {
        if (is(`category_${n}` as ActionId)) { stop(); setCategory(CATEGORIES[n - 1].id); return; }
      }
      if (is('focus_search')) {
        stop();
        inputRef.current?.focus();
        inputRef.current?.select();
        return;
      }
      if (is('list_editor') && canWriteLists(searchOpts)) { stop(); openListEditor(pasted ? pasted.values.map(v => [v]) : [], pasted ? 'edit' : 'new'); return; }
      if (is('shortcuts')) { stop(); setShortcutsOpen(true); return; }
      if (is('search_settings')) { stop(); setSearchSettingsOpen(true); return; }
      if (is('toggle_smart')) { stop(); saveSearchOptions({ ...searchOpts, enabled: !searchOpts.enabled }, true); return; }
      if (is('folders')) { stop(); setFoldersOpen(true); return; }
      if (is('expand_all') && groups) { stop(); toggleAllGroups(); return; }
      if (is('clear')) {
        stop();
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
      if (is('copy_path') && !hasTextSelection && selectedItem) { stop(); copyPath(selectedItem); return; }

      if (is('move_down') || is('move_up')) {
        stop();
        move(is('move_down') ? 1 : -1);
        if (inSearch) listRef.current?.focus();
        return;
      }
      const header = selectedRow?.kind === 'header' ? selectedRow : null;
      if (header && (is('expand') || is('collapse'))) {
        stop();
        toggleGroup(header.group, is('expand'));
        return;
      }
      if (selectedRow?.kind === 'item' && selectedRow.group !== null && is('collapse')) {
        stop();
        toggleGroup(selectedRow.group, false);
        setSelectedKey(`h:${selectedRow.group}`);
        return;
      }
      if (is('reveal') && selectedItem) { stop(); revealItem(selectedItem); return; }
      if (is('open') || is('preview')) {
        if (header) { stop(); toggleGroup(header.group); return; }
        if (selectedItem) {
          stop();
          if (is('open')) openItem(selectedItem);
          else openQuickLook(selected);
          return;
        }
      }
      if (!inSearch && (e.key.length === 1 || e.key === 'Backspace') && !e.ctrlKey && !e.altKey && !e.metaKey) {
        // Typing anywhere goes to the search field
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [view, overlayOpen, quickLook.open, query, scope, keymap, groups, pasted, selected, selectedRow, selectedItem, move, openItem, revealItem, copyPath, openQuickLook, closeQuickLook, toggleGroup, toggleAllGroups, openListEditor, searchOpts]);

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

  const saveShortcuts = async (map: Keymap, hotkey: string): Promise<boolean> => {
    try {
      const s = await api.saveShortcuts({
        shortcuts: keymapOverrides(map),
        hotkey: hotkey !== settings?.hotkey ? hotkey : undefined,
      });
      setSettings(s);
      setKeymap(buildKeymap(s.shortcuts));
      toast('Keyboard shortcuts saved');
      return true;
    } catch (e) {
      toast((e as Error).message, 'error');
      return false;
    }
  };

  /** Save search settings; returns an error message or null. toast: say what changed (quick toggle). */
  const saveSearchOptions = async (next: SearchOptions, quick = false): Promise<string | null> => {
    try {
      const s = await api.saveSearchSettings(next);
      setSettings(s);
      setSearchOpts(s.search);
      toast(quick ? `Smart search ${s.search.enabled ? 'on' : 'off'}` : 'Search settings saved', 'info');
      return null;
    } catch (e) {
      const message = (e as Error).message;
      if (quick) toast(message, 'error');
      return message;
    }
  };

  const indexing = status?.phase === 'scanning' || status?.phase === 'reading';
  const pastedVisible = pasted && pasted.query === query ? pasted : null;
  const allOpen = !!groups && groups.length > 0 && groups.every(g => expanded.has(g.label));

  const emptyState = () => {
    if (busy && !rows.length) return null;
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
        <div className="text-[13px] text-fg max-w-[460px] break-words">No matches for “{query}”</div>
        <div className="flex flex-wrap items-center justify-center gap-2 mt-1">
          {category !== 'all' && <button type="button" className="btn !h-7" onClick={() => setCategory('all')}>Search all types</button>}
          {scope && <button type="button" className="btn !h-7" onClick={() => setScope(null)}>Search all folders</button>}
          {searchOpts.enabled && searchOpts.default_scope === 'names' && searchOpts.text_char && !query.includes(searchOpts.text_char) && (
            <button
              type="button"
              className="btn !h-7"
              onClick={() => setQuery(`${searchOpts.text_char}${query}`)}
              title={`Without “${searchOpts.text_char}” only file names are searched`}
            >
              Search the text: <span className="font-mono">{searchOpts.text_char}{query.length > 24 ? `${query.slice(0, 24)}…` : query}</span>
            </button>
          )}
          {!searchOpts.enabled && searchOpts.default_scope !== 'both' && (
            <button type="button" className="btn !h-7" onClick={() => setSearchSettingsOpen(true)}>Search settings…</button>
          )}
          {status?.phase === 'reading' && <span className="text-[12px] text-fg-3">Text is still being read in some files.</span>}
        </div>
      </div>
    );
  };

  const qlPosition = (() => {
    if (!selectedRow || selectedRow.kind !== 'item') return { index: 0, total: 0 };
    if (selectedRow.group === null) return { index: selectedRow.index, total: flat.total };
    const g = groups?.[selectedRow.group];
    return { index: selectedRow.index, total: g?.total ?? 0, label: g?.label };
  })();

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
        onOpenShortcuts={() => setShortcutsOpen(true)}
        onOpenSearchSettings={() => setSearchSettingsOpen(true)}
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
          <div className="relative z-20 flex flex-col gap-2.5 px-4 pt-3 pb-2 shrink-0 fade-up" style={{ animationDuration: '420ms' }}>
            <CommandBar
              query={query}
              onQueryChange={setQuery}
              scope={scope}
              onScopeChange={setScope}
              folders={folders}
              busy={busy}
              inputRef={inputRef}
              listKey={keymap.list_editor[0]}
              onPasteList={grid => pasteList(grid)}
              onOpenList={canWriteLists(searchOpts) ? () => openListEditor(pastedVisible ? pastedVisible.values.map(v => [v]) : [], pastedVisible ? 'edit' : 'new') : undefined}
              searchOptions={searchOpts}
              onToggleSmart={() => saveSearchOptions({ ...searchOpts, enabled: !searchOpts.enabled }, true)}
              onOpenSearchSettings={() => setSearchSettingsOpen(true)}
              smartKey={keymap.toggle_smart[0]}
            />

            {pastedVisible ? (
              <div className="flex items-center gap-2 min-w-0 fade-up" style={{ animationDuration: '260ms' }}>
                <span className="flex items-center gap-1.5 shrink-0 text-[11.5px] text-fg-3">
                  <ClipboardList className="w-3.5 h-3.5" />
                  <span className="num text-fg-2">{pastedVisible.values.length}</span>
                  {pastedVisible.where === 'text' ? 'values in the text' : 'values in file names'}{pastedVisible.mode === 'groups' ? ', one row each' : ', all together'}
                </span>
                <div className="flex-1 min-w-0 flex items-center gap-1.5 overflow-x-auto pb-0.5" style={{ scrollbarWidth: 'none' }}>
                  {pastedVisible.values.map((v, i) => {
                    const g = groups?.find(x => x.label === v);
                    return (
                      <button
                        key={`${v}-${i}`}
                        type="button"
                        className="shrink-0 inline-flex items-center gap-1.5 h-[22px] px-2 rounded-md text-[11.5px] text-fg bg-surface-2 hover:bg-[var(--surface-3)] transition-colors max-w-[200px]"
                        style={{ boxShadow: 'inset 0 0 0 1px var(--line)' }}
                        title={pastedVisible.mode === 'groups' ? 'Open this group' : v}
                        onClick={() => {
                          const gi = groups?.findIndex(x => x.label === v) ?? -1;
                          if (gi >= 0) {
                            toggleGroup(gi, true);
                            setSelectedKey(`h:${gi}`);
                          }
                        }}
                      >
                        <span className="truncate">{v}</span>
                        {g && <span className={`num ${g.total ? 'text-accent' : 'text-fg-3'}`}>{g.total.toLocaleString()}</span>}
                      </button>
                    );
                  })}
                </div>
                <SegmentedControl
                  options={[
                    { id: 'groups' as const, label: 'Rows', hint: 'One expandable row per value' },
                    { id: 'together' as const, label: '+', hint: 'Files that hit every value' },
                  ]}
                  value={pastedVisible.mode}
                  onChange={m => confirmList(pastedVisible.values, m, pastedVisible.where, pastedVisible.filter)}
                  size="sm"
                  className="shrink-0"
                />
                <button type="button" className="btn !h-7 shrink-0" onClick={() => openListEditor(pastedVisible.values.map(v => [v]), 'edit')} title="Edit the list">
                  <Pencil className="w-3.5 h-3.5" /> Edit
                </button>
                <button type="button" className="icon-btn shrink-0" onClick={() => { setPasted(null); setQuery(''); inputRef.current?.focus(); }} title="Clear the list">
                  <X className="w-4 h-4" />
                </button>
              </div>
            ) : (
              searchOpts.show_chips && chipsWorthShowing(chips, searchOpts) && query && <QueryChips chips={chips} />
            )}

            <div className="flex items-center justify-between gap-3">
              <SegmentedControl options={CATEGORIES} value={category} onChange={setCategory} size="sm" />
              <div className="flex items-center gap-2 text-[11.5px] text-fg-3 whitespace-nowrap">
                {groups && groups.length > 0 && (
                  <button type="button" className="flex items-center gap-1 h-6 px-1.5 rounded-md hover:text-fg hover:bg-surface-2 transition-colors" onClick={toggleAllGroups} title={`Open or close all groups${keymap.expand_all[0] ? ` (${keymap.expand_all[0]})` : ''}`}>
                    {allOpen ? <ChevronsDownUp className="w-3.5 h-3.5" /> : <ChevronsUpDown className="w-3.5 h-3.5" />}
                    {allOpen ? 'Close all' : 'Open all'}
                  </button>
                )}
                <span className="label-caps !text-[10px]">{groups ? `${groups.length} group${groups.length === 1 ? '' : 's'}` : query ? 'Best matches' : 'Recently changed'}</span>
                <span className="w-1 h-1 rounded-full bg-line-strong" />
                <span>
                  <RollingNumber value={totalFiles} className="text-fg-2 font-medium" /> {groups ? 'files' : 'results'}
                </span>
                {query && <span className="num">{tookMs.toFixed(0)} ms</span>}
              </div>
            </div>
          </div>

          <div className="relative flex-1 min-h-0 flex flex-col" onPointerMove={() => keyboardFocus && setKeyboardFocus(false)}>
            {busy && rows.length > 0 && <div className="absolute top-0 left-4 right-4 h-px overflow-hidden loading-line z-10" />}
            <ResultsList
              rows={rows}
              selectedIndex={selected}
              onSelect={idx => {
                if (rows[idx]) setSelectedKey(rows[idx].key);
                listRef.current?.focus();
              }}
              onOpen={openItem}
              onPreview={openQuickLook}
              onToggleGroup={g => toggleGroup(g)}
              onLoadMore={loadMore}
              termsFor={termsFor}
              folders={folders}
              keyboardFocus={keyboardFocus}
              listRef={listRef}
              empty={emptyState()}
              previewKey={keymap.preview[0] ? bindingParts(keymap.preview[0]).join('+') : 'Preview'}
            />
          </div>

          <footer className="flex items-center justify-between gap-4 h-9 px-4 shrink-0 text-[11.5px] text-fg-3" style={{ borderTop: '1px solid var(--line)' }}>
            <div className="flex items-center gap-3.5 overflow-hidden whitespace-nowrap">
              <KeyHint keys={[keymap.move_up[0], keymap.move_down[0]]} label="Move" />
              <KeyHint keys={[keymap.preview[0]]} label="Preview" />
              <KeyHint keys={[keymap.open[0]]} label="Open" />
              <KeyHint keys={[keymap.reveal[0]]} label="Show in folder" />
              <KeyHint keys={[keymap.copy_path[0]]} label="Copy path" className="hidden md:flex" />
              <button type="button" className="hidden lg:flex items-center gap-1.5 hover:text-fg transition-colors" onClick={() => setShortcutsOpen(true)} title="Change the keys">
                <KeyHint keys={[keymap.shortcuts[0]]} label="Keys" />
                {!keymap.shortcuts[0] && 'Keys'}
              </button>
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
          position={qlPosition}
          onClose={closeQuickLook}
          onOpen={openItem}
          onReveal={revealItem}
          onCopyPath={copyPath}
          terms={searchOpts.preview_highlight ? termsFor(selectedRow?.kind === 'item' ? selectedRow.group : null) : []}
          keymap={keymap}
          searchOptions={searchOpts}
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

      {listEditor && (
        <ListEditor
          grid={listEditor.grid}
          mode={listEditor.mode}
          where={listEditor.where}
          filter={listEditor.filter}
          source={listEditor.source}
          onConfirm={confirmList}
          options={searchOpts}
          onClose={() => {
            setListEditor(null);
            requestAnimationFrame(() => inputRef.current?.focus());
          }}
        />
      )}

      {searchSettingsOpen && settings && (
        <SearchSettingsPanel
          options={searchOpts}
          defaults={settings.search_defaults}
          presets={settings.search_presets}
          onSave={next => saveSearchOptions(next)}
          onClose={() => {
            setSearchSettingsOpen(false);
            requestAnimationFrame(() => inputRef.current?.focus());
          }}
        />
      )}

      {shortcutsOpen && (
        <ShortcutsPanel
          keymap={keymap}
          hotkey={settings?.hotkey ?? 'alt+space'}
          defaultHotkey={settings?.default_hotkey ?? 'alt+space'}
          canSetHotkey={!!settings?.can_set_hotkey}
          onSave={saveShortcuts}
          onClose={() => {
            setShortcutsOpen(false);
            requestAnimationFrame(() => inputRef.current?.focus());
          }}
        />
      )}

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
