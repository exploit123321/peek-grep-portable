import React, { useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Code, Copy, Eye, ExternalLink, FolderOpen, Minus, Pencil, Plus, Save, Search, WrapText, X } from 'lucide-react';
import { api, Delimiter, EditModel, PreviewPayload, SearchItem } from '../api';
import { CsvEditor, DocumentEditor, editorTopLine, TextEditor, WorkbookEditor } from './editors/Editors';
import { useToast } from './Toasts';
import { FileIcon } from './FileIcon';
import { CodePreview, PlainPreview, scrollToCodeLine, topCodeLine } from './previews/CodePreview';
import { MarkdownPreview } from './previews/MarkdownPreview';
import { TablePreview } from './previews/TablePreview';
import { ImagePreview, ZoomCommand } from './previews/ImagePreview';
import { VideoPreview } from './previews/VideoPreview';
import { PdfPreview } from './previews/PdfPreview';
import { EpubPreview } from './previews/EpubPreview';
import { DocumentPreview, SlidesPreview, WorkbookPreview } from './previews/OfficePreviews';
import { fileKind, formatBytes, formatDate } from '../utils/formatters';
import { compactCrumbs, folderCrumbs } from '../utils/paths';
import { clearHits, findHits, paintHits, revealRange } from '../utils/searchHits';
import { HighlightTerm, parseFindText } from '../utils/query';
import { DEFAULT_SEARCH_OPTIONS, SearchOptions } from '../utils/searchOptions';
import { ACTIONS, bindingParts, eventToBinding, Keymap, matches } from '../utils/keymap';
import { AnchorContext, FreezeContext, GridAnchor, HitReport, HitsContext, JumpContext } from './VirtualGrid';
import { FreezeControl } from './FreezeControl';
import { FileFreeze, fileFreeze, parseFreeze, setFileFreeze } from '../utils/freeze';
import { fileDragProps } from '../utils/fileDrag';
import { prefersReducedMotion } from './motion/useReducedMotion';

// Quick Look grows out of the selected row and sharpens from a blur (matrix ref R03 Blur Reveal).

interface QuickLookModalProps {
  item: SearchItem | null;
  originRect: DOMRect | null;
  folders: string[];
  position: { index: number; total: number; label?: string };
  onClose: () => void;
  onOpen: (item: SearchItem) => void;
  onReveal: (item: SearchItem) => void;
  onCopyPath: (item: SearchItem) => void;
  terms: HighlightTerm[];
  keymap: Keymap;
  searchOptions?: SearchOptions;
  /** After a save: the file is indexed again, so the results can be refreshed */
  onSaved?: (item: SearchItem) => void;
}

// Zoom of the preview: text, tables, and documents (CSS zoom), PDF pages (drawn larger); photos zoom
// themselves. One level for all files, kept in this browser profile like the wrap setting.
const ZOOM_STEPS = [0.5, 0.67, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3];
const CSS_ZOOM_TYPES = new Set(['code', 'plain', 'markdown', 'table', 'document', 'epub', 'slides', 'workbook']);

function stored<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

function store(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // No storage: the setting lasts until the app closes
  }
}

/** "14:05" for a backup made today, else "21 Oct 14:05" (from its name: "plan 2026-10-21 14-05-09.txt") */
function backupTime(path: string): string {
  const m = / (\d{4})-(\d{2})-(\d{2}) (\d{2})-(\d{2})-\d{2}(-\d+)?(\.[^.\\/]*)?$/.exec(path);
  if (!m) return '';
  const day = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const time = `${m[4]}:${m[5]}`;
  return day.toDateString() === new Date().toDateString()
    ? time
    : `${day.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })} ${time}`;
}

export const QuickLookModal: React.FC<QuickLookModalProps> = ({
  item,
  originRect,
  folders,
  position,
  onClose,
  onOpen,
  onReveal,
  onCopyPath,
  terms,
  keymap,
  searchOptions = DEFAULT_SEARCH_OPTIONS,
  onSaved,
}) => {
  const panelRef = useRef<HTMLDivElement>(null);
  const [data, setData] = useState<PreviewPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [raw, setRaw] = useState(false);
  const [zoom, setZoom] = useState<number>(() => stored('pg-preview-zoom', 1));
  const [wrap, setWrap] = useState<boolean>(() => stored('pg-preview-wrap', true));
  const [imageZoom, setImageZoom] = useState<ZoomCommand | null>(null);
  const [delimiter, setDelimiter] = useState<Delimiter>('auto');
  const [reload, setReload] = useState(0);
  const [editModel, setEditModel] = useState<EditModel | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const payloadRef = useRef<Record<string, unknown>>({});
  const toast = useToast();
  const editing = editModel !== null;
  const current = data && item && data.path.toLowerCase() === item.path.toLowerCase() ? data : null;

  // While editing, the window's search keys (Space, arrows, Enter, Esc) stay off
  useEffect(() => {
    if (editing) document.body.dataset.editing = '1';
    else delete document.body.dataset.editing;
    return () => {
      delete document.body.dataset.editing;
    };
  }, [editing]);

  // Preview <-> editor: the other view opens where this one was (tables: the row, column and
  // sheet; text: the same part of the file)
  const anchorRef = useRef<GridAnchor | null>(null);
  const [sheet, setSheet] = useState(0);
  const scrollRatio = useRef<number | null>(null);
  // Text and code: the line at the top (the preview wraps lines, the editor does not)
  const placeLine = useRef<number | null>(null);
  useEffect(() => {
    anchorRef.current = null;
    placeLine.current = null;
    setSheet(0);
  }, [item?.path]);
  const mainScroller = (): HTMLElement | null => {
    let best: HTMLElement | null = null;
    bodyRef.current?.querySelectorAll<HTMLElement>('*').forEach(el => {
      if (el.scrollHeight - el.clientHeight > 4 && /(auto|scroll)/.test(getComputedStyle(el).overflowY)
        && (!best || el.scrollHeight > best.scrollHeight)) best = el;
    });
    return best;
  };
  const keepPlace = () => {
    if (anchorRef.current) anchorRef.current.restore = true;
    placeLine.current = editModel ? editorTopLine(bodyRef.current) : topCodeLine(bodyRef.current);
    const el = mainScroller();
    scrollRatio.current = placeLine.current === null && el ? el.scrollTop / Math.max(1, el.scrollHeight - el.clientHeight) : null;
  };

  // Text views: the same part of the file (tables restore themselves from the anchor)
  const gridShown = editModel ? editModel.kind === 'csv' || editModel.kind === 'workbook' : current?.preview_type === 'table' || current?.preview_type === 'workbook';
  useEffect(() => {
    const line = placeLine.current;
    if (line !== null) {
      // The editor opens at the line itself (initialLine); the preview scrolls to it when drawn
      let raf = 0;
      if (!editing) raf = requestAnimationFrame(() => requestAnimationFrame(() => scrollToCodeLine(bodyRef.current, line)));
      const timer = window.setTimeout(() => {
        placeLine.current = null;
      }, 1500);
      return () => {
        cancelAnimationFrame(raf);
        window.clearTimeout(timer);
      };
    }
    const ratio = scrollRatio.current;
    if (ratio === null) return;
    if (gridShown) {
      scrollRatio.current = null;
      return;
    }
    let raf = requestAnimationFrame(() => {
      raf = requestAnimationFrame(() => {
        const el = mainScroller();
        if (el) el.scrollTop = ratio * (el.scrollHeight - el.clientHeight);
      });
    });
    // A saved file is shown again a moment later (and not moved to its first hit meanwhile)
    const timer = window.setTimeout(() => {
      scrollRatio.current = null;
    }, 1500);
    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(timer);
    };
  }, [editing, current]); // eslint-disable-line react-hooks/exhaustive-deps

  const startEdit = async () => {
    if (!item) return;
    try {
      const model = await api.editLoad(item.path);
      payloadRef.current = {};
      setDirty(false);
      keepPlace();
      setEditModel(model);
    } catch (e) {
      toast((e as Error).message, 'error');
    }
  };

  const leaveEdit = (force = false) => {
    if (!force && dirty && !window.confirm('Discard your changes?')) return false;
    keepPlace();
    setEditModel(null);
    setDirty(false);
    return true;
  };

  const saveEdit = async () => {
    if (!item || !editModel || !dirty || saving) return;
    setSaving(true);
    try {
      const res = await api.editSave(item.path, editModel.mtime_ns, payloadRef.current);
      const kept = res.backup_kept ? backupTime(res.backup_kept) : '';
      toast(res.backup ? 'Saved. The old version is in data\\backups.' : kept ? `Saved. Backup from ${kept} kept.` : 'Saved.');
      keepPlace();
      setEditModel(null);
      setDirty(false);
      setReload(r => r + 1);
      onSaved?.(item);
    } catch (e) {
      toast((e as Error).message, 'error');
    } finally {
      setSaving(false);
    }
  };

  const close = () => {
    if (editing && !leaveEdit()) return;
    onClose();
  };

  useEffect(() => {
    if (!editing) return;
    const onKey = (e: KeyboardEvent) => {
      if (matches(e, keymap.save_edit)) {
        e.preventDefault();
        saveEdit();
      } else if ((e.key === 'Escape' || matches(e, keymap.close_preview)) && !(e.target as HTMLElement).closest('td')
        // Esc in the find box (or another field of the header) closes that, not the editor
        && (e.target as HTMLElement).tagName !== 'INPUT') {
        e.preventDefault();
        leaveEdit();
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  });

  // Entry: from the row position, scaled down and blurred
  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (!panel || prefersReducedMotion()) return;
    const box = panel.getBoundingClientRect();
    let from = 'translate(0px, 16px) scale(0.96)';
    if (originRect) {
      const dx = originRect.left + originRect.width / 2 - (box.left + box.width / 2);
      const dy = originRect.top + originRect.height / 2 - (box.top + box.height / 2);
      const s = Math.min(0.9, Math.max(0.55, originRect.width / box.width));
      from = `translate(${dx * 0.55}px, ${dy * 0.55}px) scale(${s})`;
    }
    panel.animate(
      [
        { transform: from, opacity: 0, filter: 'blur(10px)' },
        { transform: 'none', opacity: 1, filter: 'blur(0px)' },
      ],
      { duration: 380, easing: 'cubic-bezier(.22,1,.36,1)' },
    );
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // A new file starts with automatic separator detection
  useEffect(() => setDelimiter('auto'), [item?.path]);

  useEffect(() => {
    if (!item) return;
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    setRaw(false);
    // Workbooks: a quick first answer (first rows of each sheet), then the full sheets
    const isWorkbook = /\.xls[xm]$/i.test(item.path);
    api
      .preview(item.path, ctrl.signal, delimiter, isWorkbook)
      .then(payload => {
        setData(payload);
        setLoading(false);
        if (payload.sheets?.some(s => s.partial)) {
          api
            .preview(item.path, ctrl.signal, delimiter)
            .then(full => setData(full))
            .catch(() => {});
        }
      })
      .catch(err => {
        if (ctrl.signal.aborted) return;
        setData(null);
        setError(err.message || 'Preview failed');
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [item?.path, delimiter, reload]); // eslint-disable-line react-hooks/exhaustive-deps

  // Find in the preview: its own text, or (closed / empty) the terms of the search
  const [findOpen, setFindOpen] = useState(false);
  const [findText, setFindText] = useState('');
  const findRef = useRef<HTMLInputElement>(null);
  const findOpenRef = useRef(false);
  findOpenRef.current = findOpen;
  const findTerms = useMemo(() => parseFindText(findText, searchOptions), [findText, searchOptions]);
  const searchTermsKey = JSON.stringify(terms);
  const activeTerms = useMemo(
    () => (findOpen && findTerms.length ? findTerms : terms),
    [findOpen, findTerms, searchTermsKey], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const termsKey = JSON.stringify(activeTerms);
  // Find always goes to its first hit; the search terms only when the settings say so
  const jumpFirst = (findOpen && findTerms.length > 0) || searchOptions.preview_jump;

  const typesIntoFind = (e: KeyboardEvent) => {
    if (e.key.length !== 1 || e.key === ' ' || e.ctrlKey || e.altKey || e.metaKey) return false;
    const active = document.activeElement as HTMLElement | null;
    if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.isContentEditable)) return false;
    const binding = eventToBinding(e);
    return !ACTIONS.some(a => a.context !== 'results' && binding !== null && keymap[a.id].includes(binding));
  };

  const openFind = () => {
    if (findOpenRef.current && findRef.current) {
      // Already open: select the text, so typing replaces it
      findRef.current.focus();
      findRef.current.select();
      return;
    }
    // New box: autoFocus gives it the focus when it mounts (no select: letters typed meanwhile stay)
    findOpenRef.current = true;
    setFindOpen(true);
  };
  const closeFind = () => {
    setFindOpen(false);
    setFindText('');
    panelRef.current?.focus();
  };

  // Search hits: highlight every match and scroll to the first one
  const bodyRef = useRef<HTMLDivElement>(null);
  const [hits, setHits] = useState<Range[]>([]);
  const [hitIndex, setHitIndex] = useState(0);
  const hitIndexRef = useRef(0);
  hitIndexRef.current = hitIndex;
  // Frozen rows and columns: this file's own, else the settings
  const globalFreeze = useContext(FreezeContext);
  const [ownFreeze, setOwnFreeze] = useState<FileFreeze | null>(null);
  useEffect(() => setOwnFreeze(item ? fileFreeze(item.path) : null), [item?.path]); // eslint-disable-line react-hooks/exhaustive-deps
  const freeze = useMemo(() => (ownFreeze ? parseFreeze(ownFreeze.rows, ownFreeze.cols) : globalFreeze), [ownFreeze, globalFreeze]);
  const changeFreeze = (value: FileFreeze | null) => {
    if (item) setFileFreeze(item.path, value);
    setOwnFreeze(value);
  };
  const isGrid = data?.preview_type === 'table' || data?.preview_type === 'workbook';

  // Table and PDF views report their hits from the data (they draw only the visible rows or pages)
  const [tableHits, setTableHits] = useState<HitReport | null>(null);
  const isTableView = data?.preview_type === 'table' || data?.preview_type === 'workbook' || data?.preview_type === 'pdf';

  useEffect(() => {
    const root = bodyRef.current;
    if (!root || editing || !data || !activeTerms.length || isTableView) {
      clearHits();
      setHits([]);
      return;
    }
    let timer = 0;
    let firstRun = true;
    const scan = () => {
      const found = findHits(root, activeTerms);
      setHits(found);
      setHitIndex(0);
      paintHits(found, 0);
      if (found.length && firstRun && jumpFirst && scrollRatio.current === null && placeLine.current === null) revealRange(found[0]);
      firstRun = firstRun && !found.length;
    };
    // Views that render later (sheet tabs, chapters, large code) change the DOM: scan again
    const observer = new MutationObserver(() => {
      window.clearTimeout(timer);
      timer = window.setTimeout(scan, 120);
    });
    observer.observe(root, { childList: true, subtree: true, characterData: true });
    const raf = requestAnimationFrame(() => requestAnimationFrame(scan));
    return () => {
      observer.disconnect();
      cancelAnimationFrame(raf);
      window.clearTimeout(timer);
    };
  }, [data, raw, editing, termsKey, isTableView, jumpFirst]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => clearHits(), []);

  const goHit = (step: number) => {
    if (tableHits) {
      tableHits.go(step);
      return;
    }
    if (!hits.length) return;
    const next = (hitIndexRef.current + step + hits.length) % hits.length;
    hitIndexRef.current = next;
    setHitIndex(next);
    paintHits(hits, next);
    revealRange(hits[next]);
  };

  const previewType = editModel ? 'editor' : current?.preview_type;
  const zoomKind = previewType === 'image' ? 'image' : previewType === 'pdf' ? 'pdf'
    : previewType === 'editor' || (previewType && CSS_ZOOM_TYPES.has(previewType)) ? 'css' : null;
  const canWrap = !editModel && (previewType === 'code' || previewType === 'plain' || (previewType === 'markdown' && raw));
  const stepZoom = (dir: 1 | -1 | 0) => {
    if (zoomKind === 'image') {
      setImageZoom(z => ({ dir, n: (z?.n ?? 0) + 1 }));
      return;
    }
    if (!zoomKind) return;
    setZoom(z => {
      const i = ZOOM_STEPS.findIndex(s => s >= z - 0.001);
      const next = dir === 0 ? 1 : ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, Math.max(0, (i < 0 ? ZOOM_STEPS.length - 1 : i) + dir))];
      store('pg-preview-zoom', next);
      return next;
    });
  };
  const toggleWrap = () =>
    setWrap(w => {
      store('pg-preview-wrap', !w);
      return !w;
    });

  // Ctrl + mouse wheel zooms (also a touchpad pinch); the WebView's own page zoom stays off
  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      stepZoom(e.deltaY < 0 ? 1 : -1);
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (matches(e, keymap.zoom_in) || matches(e, keymap.zoom_out) || matches(e, keymap.zoom_reset)) {
        e.preventDefault();
        e.stopPropagation();
        stepZoom(matches(e, keymap.zoom_in) ? 1 : matches(e, keymap.zoom_out) ? -1 : 0);
        return;
      }
      if (matches(e, keymap.wrap_lines) && canWrap) {
        e.preventDefault();
        e.stopPropagation();
        toggleWrap();
        return;
      }
      if (matches(e, keymap.find_in_preview)) {
        e.preventDefault();
        e.stopPropagation();
        openFind();
      } else if (matches(e, keymap.next_hit) || matches(e, keymap.prev_hit)) {
        e.preventDefault();
        e.stopPropagation();
        goHit(matches(e, keymap.prev_hit) ? -1 : 1);
      } else if (editing) {
        // While editing, letters are for the editor: no type to find
      } else if (matches(e, keymap.edit_file) && current?.editable && document.activeElement !== findRef.current) {
        e.preventDefault();
        e.stopPropagation();
        startEdit();
      } else if (searchOptions.type_to_find && typesIntoFind(e)) {
        // Type to find: letters go to the find box (also the ones typed before it has the focus)
        e.preventDefault();
        e.stopPropagation();
        const open = findOpenRef.current;
        findOpenRef.current = true; // the next key (before the next render) appends
        setFindText(t => (open ? t : '') + e.key);
        setFindOpen(true);
        findRef.current?.focus();
        requestAnimationFrame(() => findRef.current?.focus());
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  });

  if (!item) return null;

  const kind = fileKind(item.category, item.extension);
  const crumbs = compactCrumbs(folderCrumbs(item.path, folders), 5);

  const editorProps = {
    onChange: (payload: Record<string, unknown>, isDirty: boolean) => {
      payloadRef.current = payload;
      setDirty(isDirty);
    },
  };

  const body = () => {
    if (editModel) {
      switch (editModel.kind) {
        case 'text':
          return <TextEditor model={editModel} terms={activeTerms} initialLine={placeLine.current} {...editorProps} />;
        case 'csv':
          return <CsvEditor model={editModel} terms={activeTerms} {...editorProps} />;
        case 'workbook':
          return <WorkbookEditor model={editModel} terms={activeTerms} sheet={sheet} onSheet={setSheet} {...editorProps} />;
        case 'document':
          return <DocumentEditor model={editModel} terms={activeTerms} {...editorProps} />;
      }
    }
    if (error) {
      return (
        <div className="flex flex-col items-center justify-center h-full gap-2 text-center px-6">
          <span className="text-[13px] font-medium text-danger">Preview is not available</span>
          <span className="text-[12px] text-fg-3 font-mono">{error}</span>
        </div>
      );
    }
    if (!current) {
      return (
        <div className="flex items-center justify-center h-full">
          <span className="w-5 h-5 rounded-full spin" style={{ border: '2px solid var(--line-strong)', borderTopColor: 'var(--accent)' }} />
        </div>
      );
    }
    switch (current.preview_type) {
      case 'code':
        return <CodePreview content={current.content || ''} language={current.language} wrap={wrap} />;
      case 'markdown':
        return <MarkdownPreview content={current.content || ''} raw={raw} wrap={wrap} />;
      case 'table':
        return current.table_data ? <TablePreview tableData={current.table_data} delimiter={delimiter} onDelimiterChange={setDelimiter} terms={activeTerms} /> : null;
      case 'image':
        return current.raw_url ? (
          <ImagePreview
            rawUrl={current.raw_url}
            displayUrl={current.display_url}
            filename={current.filename}
            imageMeta={current.image_meta}
            overlayUrl={current.overlay_url}
            zoomCommand={imageZoom}
          />
        ) : null;
      case 'video':
        return current.raw_url ? (
          <VideoPreview
            rawUrl={current.raw_url}
            filename={current.filename}
            meta={current.video_meta}
            mime={current.media_mime}
            overlayUrl={current.overlay_url}
          />
        ) : null;
      case 'pdf':
        return current.raw_url ? <PdfPreview rawUrl={current.raw_url} filename={current.filename} terms={activeTerms} zoom={zoom} /> : null;
      case 'epub':
        return <EpubPreview filename={current.filename} epubData={current.epub_data} />;
      case 'document':
        return <DocumentPreview html={current.document_html || ''} />;
      case 'workbook':
        return <WorkbookPreview sheets={current.sheets || []} terms={activeTerms} sheet={sheet} onSheet={setSheet} />;
      case 'slides':
        return <SlidesPreview slides={current.slides || []} />;
      case 'plain':
        return <PlainPreview content={current.content || ''} wrap={wrap} />;
      default:
        return (
          <div className="flex flex-col items-center justify-center h-full gap-4 text-center">
            <FileIcon kind={kind} size="lg" />
            <div>
              <div className="text-[13px] font-medium text-fg">No preview for {item.extension || 'this file'}</div>
              <div className="text-[12px] text-fg-3 mt-1">Open it in its own app.</div>
            </div>
            <button type="button" className="btn-primary" onClick={() => onOpen(item)}>
              <ExternalLink className="w-4 h-4" /> Open
            </button>
          </div>
        );
    }
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-5 sm:p-8">
      <div className="absolute inset-0 fade-up" style={{ background: 'rgba(5,5,8,0.62)', backdropFilter: 'blur(6px)', animationDuration: '260ms' }} onClick={close} />
      <div
        ref={panelRef}
        className="relative flex flex-col w-full max-w-[1100px] h-full max-h-[860px] rounded-2xl overflow-hidden"
        style={{
          background: 'var(--bg-elev)',
          boxShadow: 'inset 0 0 0 1px var(--line-strong), 0 40px 100px -30px rgba(0,0,0,0.9)',
        }}
        role="dialog"
        tabIndex={-1}
        aria-label={`Quick Look: ${item.filename}`}
      >
        <div className="flex items-center gap-3 h-[58px] pl-4 pr-3 shrink-0" style={{ borderBottom: '1px solid var(--line)' }}>
          {/* The icon and the name: drag the file into another app (Telegram, mail, Explorer) */}
          <span
            className="shrink-0 cursor-grab active:cursor-grabbing"
            title="Drag the file into another app (Telegram, mail, Explorer)"
            {...fileDragProps(() => ({ paths: [item.path], rawUrl: current?.raw_url, filename: item.filename }))}
          >
            <FileIcon kind={kind} />
          </span>
          <div className="flex flex-col min-w-0 flex-1">
            <span
              className="truncate text-[14px] font-semibold text-fg cursor-grab active:cursor-grabbing self-start max-w-full"
              title="Drag the file into another app (Telegram, mail, Explorer)"
              {...fileDragProps(() => ({ paths: [item.path], rawUrl: current?.raw_url, filename: item.filename }))}
            >
              {item.filename}
            </span>
            <span className="flex items-center gap-1 min-w-0 font-mono text-[11px] text-fg-3">
              {crumbs.map((c, i) => (
                <React.Fragment key={i}>
                  {i > 0 && <span className="opacity-50">›</span>}
                  <span className="truncate">{c}</span>
                </React.Fragment>
              ))}
            </span>
          </div>
          {isGrid && <FreezeControl global={globalFreeze} own={ownFreeze} onChange={changeFreeze} />}
          {canWrap && (
            <button
              type="button"
              className={`btn !h-7 !px-2 ${wrap ? 'text-accent' : ''}`}
              onClick={toggleWrap}
              title={`Wrap long lines (${keymap.wrap_lines.join(', ') || 'no key'}). Editing never wraps: the spacing stays exact`}
            >
              <WrapText className="w-3.5 h-3.5" /> Wrap
            </button>
          )}
          {(zoomKind === 'css' || zoomKind === 'pdf') && (
            <span className="flex items-center h-7 rounded-lg" style={{ boxShadow: 'inset 0 0 0 1px var(--line)' }} title="Zoom: Ctrl + mouse wheel, Ctrl + / Ctrl − / Ctrl 0">
              <button type="button" className="icon-btn !w-6 !h-6" onClick={() => stepZoom(-1)} title={`Zoom out (${keymap.zoom_out[0] ?? ''})`}>
                <Minus className="w-3.5 h-3.5" />
              </button>
              <button type="button" className="num text-[11.5px] text-fg-2 w-10 text-center hover:text-fg" onClick={() => stepZoom(0)} title={`100% (${keymap.zoom_reset[0] ?? ''})`}>
                {Math.round(zoom * 100)}%
              </button>
              <button type="button" className="icon-btn !w-6 !h-6" onClick={() => stepZoom(1)} title={`Zoom in (${keymap.zoom_in[0] ?? ''})`}>
                <Plus className="w-3.5 h-3.5" />
              </button>
            </span>
          )}
          {!findOpen && (
            <button type="button" className="icon-btn" onClick={openFind} title={`Find in the preview (${keymap.find_in_preview.join(', ') || 'no key'})`}>
              <Search className="w-4 h-4" />
            </button>
          )}
          {(tableHits ? tableHits.count : hits.length) > 0 && !findOpen && (
            <span className="flex items-center h-7 rounded-lg text-[11.5px] text-fg-2" style={{ background: 'var(--bg)', boxShadow: 'inset 0 0 0 1px var(--line-strong)' }} title="Search hits in this file (F3, Shift+F3)">
              <button type="button" className="icon-btn !w-6 !h-6" onClick={() => goHit(-1)} title="Previous hit (Shift+F3)">
                <ChevronLeft className="w-3.5 h-3.5" />
              </button>
              <span className="num px-1" style={{ color: '#facc15' }}>
                {tableHits ? `${tableHits.index + 1}/${tableHits.count.toLocaleString()}` : `${hitIndex + 1}/${hits.length}`}
              </span>
              <button type="button" className="icon-btn !w-6 !h-6" onClick={() => goHit(1)} title="Next hit (F3)">
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </span>
          )}
          <span className="hidden sm:inline num text-[11.5px] text-fg-3 mr-1 max-w-[180px] truncate" title="File position in the results">
            {position.label ? `${position.label} · ` : ''}{position.index + 1} / {position.total.toLocaleString()}
          </span>
          {!editing && current?.preview_type === 'markdown' && (
            <button type="button" className="btn !h-7" onClick={() => setRaw(r => !r)} title="Rendered or source">
              {raw ? <Eye className="w-3.5 h-3.5" /> : <Code className="w-3.5 h-3.5" />}
              {raw ? 'Rendered' : 'Source'}
            </button>
          )}
          {editing ? (
            <>
              <span className={`text-[11.5px] mr-1 ${dirty ? 'text-warn' : 'text-fg-3'}`}>{dirty ? '● Unsaved changes' : 'Editing'}</span>
              <button type="button" className="btn !h-7" onClick={() => leaveEdit()} title="Stop editing (Esc)">
                Cancel
              </button>
              <button type="button" className="btn-primary !h-7" disabled={!dirty || saving} onClick={saveEdit} title="Save (Ctrl+S)">
                <Save className="w-3.5 h-3.5" /> {saving ? 'Saving…' : 'Save'}
              </button>
            </>
          ) : (
            current?.editable && (
              <button type="button" className="btn !h-7" onClick={startEdit} title="Edit this file">
                <Pencil className="w-3.5 h-3.5" /> Edit
              </button>
            )
          )}
          <button type="button" className="btn !h-7" onClick={() => onCopyPath(item)} title="Copy path (Ctrl+C)">
            <Copy className="w-3.5 h-3.5" /> Copy path
          </button>
          <button type="button" className="btn !h-7" onClick={() => onReveal(item)} title="Show in Explorer (Ctrl+Enter)">
            <FolderOpen className="w-3.5 h-3.5" /> Show
          </button>
          <button type="button" className="btn-primary !h-7" onClick={() => onOpen(item)} title="Open (Enter)">
            <ExternalLink className="w-3.5 h-3.5" /> Open
          </button>
          <button type="button" className="icon-btn ml-1" onClick={close} title="Close (Space or Esc)">
            <X className="w-4 h-4" />
          </button>
        </div>

        <AnchorContext.Provider value={anchorRef}>
        <FreezeContext.Provider value={freeze}>
        <JumpContext.Provider value={jumpFirst}>
        <HitsContext.Provider value={setTableHits}>
        <div className="relative flex-1 min-h-0" style={{ background: 'var(--bg)' }}>
          {loading && current && <div className="absolute top-0 left-0 right-0 h-[2px] overflow-hidden loading-line z-10" />}
          {findOpen && (
            <div
              className="absolute top-2 right-4 z-20 flex items-center gap-1 h-9 pl-2.5 pr-1 rounded-xl fade-up"
              style={{
                background: 'rgba(24,24,31,0.97)',
                boxShadow: 'inset 0 0 0 1px var(--accent-line), 0 14px 34px -14px rgba(0,0,0,0.85)',
                animationDuration: '220ms',
              }}
            >
              <Search className="w-3.5 h-3.5 text-fg-3 shrink-0" />
              <input
                ref={findRef}
                autoFocus
                value={findText}
                onChange={e => setFindText(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Escape') {
                    e.preventDefault();
                    e.stopPropagation();
                    closeFind();
                  } else if (e.key === 'Enter') {
                    e.preventDefault();
                    e.stopPropagation();
                    goHit(e.shiftKey ? -1 : 1);
                  } else if (matches(e, keymap.next_hit) || matches(e, keymap.prev_hit)) {
                    e.preventDefault();
                    e.stopPropagation();
                    goHit(matches(e, keymap.prev_hit) ? -1 : 1);
                  } else {
                    e.stopPropagation();
                  }
                }}
                placeholder="Find in this file"
                title="Wildcards: * and ?. Several terms: a+b. Literal text: /text"
                className="w-52 h-full bg-transparent text-[13px] text-fg placeholder:text-fg-3 outline-none select-text"
                spellCheck={false}
                autoComplete="off"
              />
              <span className="num text-[11.5px] min-w-[52px] text-right px-1" style={{ color: findText.trim() ? '#facc15' : 'var(--text-3)' }}>
                {findText.trim()
                  ? (tableHits ? tableHits.count : hits.length) > 0
                    ? tableHits ? `${tableHits.index + 1}/${tableHits.count.toLocaleString()}` : `${hitIndex + 1}/${hits.length.toLocaleString()}`
                    : 'no hits'
                  : ''}
              </span>
              <button type="button" className="icon-btn !w-6 !h-6" onClick={() => goHit(-1)} title={`Previous hit (Shift+Enter, ${keymap.prev_hit.join(', ')})`}>
                <ChevronUp className="w-3.5 h-3.5" />
              </button>
              <button type="button" className="icon-btn !w-6 !h-6" onClick={() => goHit(1)} title={`Next hit (Enter, ${keymap.next_hit.join(', ')})`}>
                <ChevronDown className="w-3.5 h-3.5" />
              </button>
              <button type="button" className="icon-btn !w-6 !h-6" onClick={closeFind} title="Close (Esc)">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
          <div ref={bodyRef} className="absolute inset-0">
            {/* Always this wrapper: adding it only when zoomed would draw the preview anew (scroll lost) */}
            <div className="absolute inset-0" style={zoomKind === 'css' && zoom !== 1 ? { zoom } : undefined}>
              {body()}
            </div>
          </div>
        </div>
        </HitsContext.Provider>
        </JumpContext.Provider>
        </FreezeContext.Provider>
        </AnchorContext.Provider>

        <div className="flex items-center justify-between gap-3 h-9 px-4 shrink-0 text-[11.5px] text-fg-3" style={{ borderTop: '1px solid var(--line)' }}>
          <div className="flex items-center gap-3 num">
            <span>{formatBytes(item.size_bytes)}</span>
            <span>{item.extension || 'file'}</span>
            <span>{formatDate(item.mtime)}</span>
            {current?.truncated && <span className="text-warn">First 2 MB shown</span>}
          </div>
          <div className="flex items-center gap-3 whitespace-nowrap overflow-hidden">
            <KeyHint keys={[keymap.move_up[0], keymap.move_down[0]]} label="Next file" />
            <KeyHint keys={[keymap.find_in_preview[0]]} label="Find" />
            {zoomKind && <KeyHint keys={[keymap.zoom_in[0]]} label="Zoom" />}
            <KeyHint keys={[keymap.open[0]]} label="Open" />
            <KeyHint keys={[keymap.close_preview[0]]} label="Close" />
          </div>
        </div>
      </div>
    </div>
  );
};

/** Footer hint: the current keys of an action as <kbd> chips (nothing when the action has no key). */
export const KeyHint: React.FC<{ keys: (string | undefined)[]; label: string; className?: string }> = ({ keys, label, className }) => {
  const list = keys.filter((k): k is string => !!k);
  if (!list.length) return null;
  return (
    <span className={`flex items-center gap-1.5 ${className ?? ''}`}>
      {list.map((k, i) => (
        <React.Fragment key={i}>
          {bindingParts(k).map((part, j) => <span key={j} className="kbd">{part}</span>)}
        </React.Fragment>
      ))}
      {label}
    </span>
  );
};
