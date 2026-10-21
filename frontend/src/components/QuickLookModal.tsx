import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Code, Copy, Eye, ExternalLink, FolderOpen, Pencil, Save, X } from 'lucide-react';
import { api, Delimiter, EditModel, PreviewPayload, SearchItem } from '../api';
import { CsvEditor, DocumentEditor, TextEditor, WorkbookEditor } from './editors/Editors';
import { useToast } from './Toasts';
import { FileIcon } from './FileIcon';
import { CodePreview, PlainPreview } from './previews/CodePreview';
import { MarkdownPreview } from './previews/MarkdownPreview';
import { TablePreview } from './previews/TablePreview';
import { ImagePreview } from './previews/ImagePreview';
import { PdfPreview } from './previews/PdfPreview';
import { EpubPreview } from './previews/EpubPreview';
import { DocumentPreview, SlidesPreview, WorkbookPreview } from './previews/OfficePreviews';
import { fileKind, formatBytes, formatDate } from '../utils/formatters';
import { compactCrumbs, folderCrumbs } from '../utils/paths';
import { clearHits, findHits, paintHits, revealRange } from '../utils/searchHits';
import { prefersReducedMotion } from './motion/useReducedMotion';

// Quick Look grows out of the selected row and sharpens from a blur (matrix ref R03 Blur Reveal).

interface QuickLookModalProps {
  item: SearchItem | null;
  originRect: DOMRect | null;
  folders: string[];
  position: { index: number; total: number };
  onClose: () => void;
  onOpen: (item: SearchItem) => void;
  onReveal: (item: SearchItem) => void;
  onCopyPath: (item: SearchItem) => void;
  query: string;
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
  query,
}) => {
  const panelRef = useRef<HTMLDivElement>(null);
  const [data, setData] = useState<PreviewPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [raw, setRaw] = useState(false);
  const [delimiter, setDelimiter] = useState<Delimiter>('auto');
  const [reload, setReload] = useState(0);
  const [editModel, setEditModel] = useState<EditModel | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const payloadRef = useRef<Record<string, unknown>>({});
  const toast = useToast();
  const editing = editModel !== null;

  // While editing, the window's search keys (Space, arrows, Enter, Esc) stay off
  useEffect(() => {
    if (editing) document.body.dataset.editing = '1';
    else delete document.body.dataset.editing;
    return () => {
      delete document.body.dataset.editing;
    };
  }, [editing]);

  const startEdit = async () => {
    if (!item) return;
    try {
      const model = await api.editLoad(item.path);
      payloadRef.current = {};
      setDirty(false);
      setEditModel(model);
    } catch (e) {
      toast((e as Error).message, 'error');
    }
  };

  const leaveEdit = (force = false) => {
    if (!force && dirty && !window.confirm('Discard your changes?')) return false;
    setEditModel(null);
    setDirty(false);
    return true;
  };

  const saveEdit = async () => {
    if (!item || !editModel || !dirty || saving) return;
    setSaving(true);
    try {
      await api.editSave(item.path, editModel.mtime_ns, payloadRef.current);
      toast('Saved. The old version is in data\\backups.');
      setEditModel(null);
      setDirty(false);
      setReload(r => r + 1);
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
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        saveEdit();
      } else if (e.key === 'Escape' && !(e.target as HTMLElement).closest('td')) {
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
    api
      .preview(item.path, ctrl.signal, delimiter)
      .then(payload => {
        setData(payload);
        setLoading(false);
      })
      .catch(err => {
        if (ctrl.signal.aborted) return;
        setData(null);
        setError(err.message || 'Preview failed');
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [item?.path, delimiter, reload]); // eslint-disable-line react-hooks/exhaustive-deps

  // Search hits: highlight every match and scroll to the first one
  const bodyRef = useRef<HTMLDivElement>(null);
  const [hits, setHits] = useState<Range[]>([]);
  const [hitIndex, setHitIndex] = useState(0);

  useEffect(() => {
    const root = bodyRef.current;
    if (!root || editing || !data || !query.trim()) {
      clearHits();
      setHits([]);
      return;
    }
    let timer = 0;
    let firstRun = true;
    const scan = () => {
      const found = findHits(root, query);
      setHits(found);
      setHitIndex(0);
      paintHits(found, 0);
      if (found.length && firstRun) revealRange(found[0]);
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
  }, [data, raw, editing, query]);

  useEffect(() => () => clearHits(), []);

  const goHit = (step: number) => {
    if (!hits.length) return;
    const next = (hitIndex + step + hits.length) % hits.length;
    setHitIndex(next);
    paintHits(hits, next);
    revealRange(hits[next]);
  };

  useEffect(() => {
    if (editing) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'F3') {
        e.preventDefault();
        goHit(e.shiftKey ? -1 : 1);
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  });

  if (!item) return null;

  const kind = fileKind(item.category, item.extension);
  const crumbs = compactCrumbs(folderCrumbs(item.path, folders), 5);
  const current = data && data.path.toLowerCase() === item.path.toLowerCase() ? data : null;

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
          return <TextEditor model={editModel} {...editorProps} />;
        case 'csv':
          return <CsvEditor model={editModel} {...editorProps} />;
        case 'workbook':
          return <WorkbookEditor model={editModel} {...editorProps} />;
        case 'document':
          return <DocumentEditor model={editModel} {...editorProps} />;
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
        return <CodePreview content={current.content || ''} language={current.language} />;
      case 'markdown':
        return <MarkdownPreview content={current.content || ''} raw={raw} />;
      case 'table':
        return current.table_data ? <TablePreview tableData={current.table_data} delimiter={delimiter} onDelimiterChange={setDelimiter} /> : null;
      case 'image':
        return current.raw_url ? <ImagePreview rawUrl={current.raw_url} filename={current.filename} imageMeta={current.image_meta} /> : null;
      case 'pdf':
        return current.raw_url ? <PdfPreview rawUrl={current.raw_url} filename={current.filename} query={query} /> : null;
      case 'epub':
        return <EpubPreview filename={current.filename} epubData={current.epub_data} />;
      case 'document':
        return <DocumentPreview html={current.document_html || ''} />;
      case 'workbook':
        return <WorkbookPreview sheets={current.sheets || []} query={query} />;
      case 'slides':
        return <SlidesPreview slides={current.slides || []} />;
      case 'plain':
        return <PlainPreview content={current.content || ''} />;
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
        aria-label={`Quick Look: ${item.filename}`}
      >
        <div className="flex items-center gap-3 h-[58px] pl-4 pr-3 shrink-0" style={{ borderBottom: '1px solid var(--line)' }}>
          <FileIcon kind={kind} />
          <div className="flex flex-col min-w-0 flex-1">
            <span className="truncate text-[14px] font-semibold text-fg select-text">{item.filename}</span>
            <span className="flex items-center gap-1 min-w-0 font-mono text-[11px] text-fg-3">
              {crumbs.map((c, i) => (
                <React.Fragment key={i}>
                  {i > 0 && <span className="opacity-50">›</span>}
                  <span className="truncate">{c}</span>
                </React.Fragment>
              ))}
            </span>
          </div>
          {hits.length > 0 && !editing && (
            <span className="flex items-center h-7 rounded-lg text-[11.5px] text-fg-2" style={{ background: 'var(--bg)', boxShadow: 'inset 0 0 0 1px var(--line-strong)' }} title="Search hits in this file (F3, Shift+F3)">
              <button type="button" className="icon-btn !w-6 !h-6" onClick={() => goHit(-1)} title="Previous hit (Shift+F3)">
                <ChevronLeft className="w-3.5 h-3.5" />
              </button>
              <span className="font-mono px-1 tabular-nums" style={{ color: '#facc15' }}>
                {hitIndex + 1}/{hits.length}
              </span>
              <button type="button" className="icon-btn !w-6 !h-6" onClick={() => goHit(1)} title="Next hit (F3)">
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </span>
          )}
          <span className="hidden sm:inline font-mono text-[11px] text-fg-3 mr-1" title="File position in the results">
            {position.index + 1} / {position.total}
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

        <div ref={bodyRef} className="relative flex-1 min-h-0" style={{ background: 'var(--bg)' }}>
          {loading && current && <div className="absolute top-0 left-0 right-0 h-[2px] overflow-hidden loading-line z-10" />}
          {body()}
        </div>

        <div className="flex items-center justify-between gap-3 h-9 px-4 shrink-0 text-[11.5px] text-fg-3" style={{ borderTop: '1px solid var(--line)' }}>
          <div className="flex items-center gap-3 font-mono">
            <span>{formatBytes(item.size_bytes)}</span>
            <span>{item.extension || 'file'}</span>
            <span>{formatDate(item.mtime)}</span>
            {current?.truncated && <span className="text-warn">First 2 MB shown</span>}
          </div>
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5"><span className="kbd">↑</span><span className="kbd">↓</span> Next file</span>
            <span className="flex items-center gap-1.5"><span className="kbd">↵</span> Open</span>
            <span className="flex items-center gap-1.5"><span className="kbd">Esc</span> Close</span>
          </div>
        </div>
      </div>
    </div>
  );
};
