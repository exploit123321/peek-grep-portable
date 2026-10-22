import React, { useEffect, useMemo, useState } from 'react';
import { BookOpen, ChevronLeft, ChevronRight } from 'lucide-react';
import { PreviewPayload } from '../../api';
import { sanitizeHtml } from '../../utils/sanitize';

type EpubData = NonNullable<PreviewPayload['epub_data']>;

export const EpubPreview: React.FC<{ filename: string; epubData?: EpubData }> = ({ filename, epubData }) => {
  const [index, setIndex] = useState(0);
  const [fontSize, setFontSize] = useState(16);
  const chapters = epubData?.chapters ?? [];
  const chapter = chapters[index];
  const html = useMemo(() => (chapter ? sanitizeHtml(chapter.content) : ''), [chapter]);

  useEffect(() => setIndex(0), [filename]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft') setIndex(i => Math.max(0, i - 1));
      if (e.key === 'ArrowRight') setIndex(i => Math.min(chapters.length - 1, i + 1));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [chapters.length]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between gap-3 px-4 h-14 shrink-0" style={{ borderBottom: '1px solid var(--line)' }}>
        <div className="flex items-center gap-3 min-w-0">
          {epubData?.cover_data_url ? (
            <img src={epubData.cover_data_url} alt="" className="w-7 h-10 object-cover rounded shadow" />
          ) : (
            <span className="flex items-center justify-center w-7 h-10 rounded" style={{ background: 'rgba(192,132,252,0.12)', color: '#d8b4fe' }}>
              <BookOpen className="w-4 h-4" />
            </span>
          )}
          <div className="flex flex-col min-w-0">
            <span className="truncate text-[13px] font-semibold text-fg">{epubData?.title || filename}</span>
            <span className="truncate text-[11.5px] text-fg-3">{epubData?.author || 'Unknown author'}</span>
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button type="button" className="icon-btn text-[11px] font-semibold" onClick={() => setFontSize(s => Math.max(12, s - 2))} title="Smaller text">A−</button>
          <button type="button" className="icon-btn text-[13px] font-semibold" onClick={() => setFontSize(s => Math.min(26, s + 2))} title="Larger text">A+</button>
          {chapters.length > 1 && (
            <>
              <span className="w-px h-4 mx-1 bg-line-strong" />
              <button type="button" className="icon-btn" disabled={index === 0} onClick={() => setIndex(i => i - 1)} title="Previous chapter (←)">
                <ChevronLeft className="w-4 h-4" />
              </button>
              <span className="num text-[11.5px] text-fg-3 w-14 text-center">{index + 1} / {chapters.length}</span>
              <button type="button" className="icon-btn" disabled={index >= chapters.length - 1} onClick={() => setIndex(i => i + 1)} title="Next chapter (→)">
                <ChevronRight className="w-4 h-4" />
              </button>
            </>
          )}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto select-text">
        {chapter ? (
          <div
            key={index}
            className="markdown-body max-w-[680px] mx-auto px-8 py-8 font-serif fade-up"
            style={{ fontSize, lineHeight: 1.75, animationDuration: '360ms' }}
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          <div className="py-20 text-center text-fg-3">No chapter text to show.</div>
        )}
      </div>
    </div>
  );
};
