import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Code, Copy, Eye, ExternalLink, FolderOpen, X } from 'lucide-react';
import { api, Delimiter, PreviewPayload, SearchItem } from '../api';
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
}) => {
  const panelRef = useRef<HTMLDivElement>(null);
  const [data, setData] = useState<PreviewPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [raw, setRaw] = useState(false);
  const [delimiter, setDelimiter] = useState<Delimiter>('auto');

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
  }, [item?.path, delimiter]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!item) return null;

  const kind = fileKind(item.category, item.extension);
  const crumbs = compactCrumbs(folderCrumbs(item.path, folders), 5);
  const current = data && data.path.toLowerCase() === item.path.toLowerCase() ? data : null;

  const body = () => {
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
        return current.raw_url ? <PdfPreview rawUrl={current.raw_url} filename={current.filename} /> : null;
      case 'epub':
        return <EpubPreview filename={current.filename} epubData={current.epub_data} />;
      case 'document':
        return <DocumentPreview html={current.document_html || ''} />;
      case 'workbook':
        return <WorkbookPreview sheets={current.sheets || []} />;
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
      <div className="absolute inset-0 fade-up" style={{ background: 'rgba(5,5,8,0.62)', backdropFilter: 'blur(6px)', animationDuration: '260ms' }} onClick={onClose} />
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
          <span className="hidden sm:inline font-mono text-[11px] text-fg-3 mr-1">
            {position.index + 1} / {position.total}
          </span>
          {current?.preview_type === 'markdown' && (
            <button type="button" className="btn !h-7" onClick={() => setRaw(r => !r)} title="Rendered or source">
              {raw ? <Eye className="w-3.5 h-3.5" /> : <Code className="w-3.5 h-3.5" />}
              {raw ? 'Rendered' : 'Source'}
            </button>
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
          <button type="button" className="icon-btn ml-1" onClick={onClose} title="Close (Space or Esc)">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="relative flex-1 min-h-0" style={{ background: 'var(--bg)' }}>
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
