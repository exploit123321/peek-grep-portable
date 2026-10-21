import React, { useMemo, useState } from 'react';
import { Image as ImageIcon } from 'lucide-react';
import { VirtualGrid } from '../VirtualGrid';
import { SheetData, SlideData } from '../../api';
import { sanitizeHtml } from '../../utils/sanitize';

// Word: the text, headings, lists, and tables (no page layout or images)
export const DocumentPreview: React.FC<{ html: string }> = ({ html }) => {
  const safe = useMemo(() => sanitizeHtml(html), [html]);
  return (
    <div className="h-full overflow-auto">
      <div
        className="markdown-body max-w-[760px] mx-auto px-8 py-7 text-[13.5px] fade-up"
        style={{ animationDuration: '360ms' }}
        dangerouslySetInnerHTML={{ __html: safe || '<p>This document has no text.</p>' }}
      />
    </div>
  );
};

// Excel: one tab per sheet, a grid with column letters and row numbers like Excel.
// The whole sheet is loaded; only the visible rows are drawn.
export const WorkbookPreview: React.FC<{ sheets: SheetData[]; query?: string }> = ({ sheets, query }) => {
  // Start on the first sheet that has the searched text
  const [index, setIndex] = useState(() => {
    const q = (query ?? '').trim().toLowerCase();
    if (!q) return 0;
    const i = sheets.findIndex(s => s.name.toLowerCase().includes(q) || s.rows.some(r => r.some(c => c.toLowerCase().includes(q))));
    return Math.max(0, i);
  });
  const sheet = sheets[Math.min(index, sheets.length - 1)];
  if (!sheet) return <div className="py-20 text-center text-fg-3">This workbook has no sheets.</div>;
  const shown = sheet.rows.length;

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-4 h-11 shrink-0 text-[12px] text-fg-3" style={{ borderBottom: '1px solid var(--line)' }}>
        <span className="whitespace-nowrap">
          {sheet.total_rows.toLocaleString()} rows · {sheet.total_columns} columns
          {shown < sheet.total_rows && ` · first ${shown.toLocaleString()} rows shown (preview limit)`}
          {sheet.total_columns > sheet.columns.length && ` · first ${sheet.columns.length} columns shown`}
        </span>
      </div>
      <div className="flex-1 min-h-0">
        <VirtualGrid key={index} columns={sheet.columns} rows={sheet.rows} query={query} />
      </div>
      {sheets.length > 1 && (
        <div className="flex items-center gap-1 px-2 h-10 shrink-0 overflow-x-auto" style={{ borderTop: '1px solid var(--line)' }}>
          {sheets.map((s, i) => (
            <button
              key={`${s.name}-${i}`}
              type="button"
              onClick={() => setIndex(i)}
              className={`h-7 px-3 rounded-md text-[12px] whitespace-nowrap transition-colors ${
                i === index ? 'bg-surface-2 text-fg shadow-[inset_0_-2px_0_var(--ok)]' : 'text-fg-3 hover:text-fg hover:bg-surface-2'
              }`}
            >
              {s.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

// PowerPoint: one 16:9 card per slide with its title and text
export const SlidesPreview: React.FC<{ slides: SlideData[] }> = ({ slides }) => (
  <div className="h-full overflow-y-auto">
    <div className="flex flex-col gap-5 max-w-[760px] mx-auto px-8 py-7">
      {slides.length === 0 && <div className="py-20 text-center text-fg-3">This presentation has no slides.</div>}
      {slides.map((s, i) => (
        <div key={s.number} className="flex gap-3 fade-up" style={{ ['--d' as string]: `${Math.min(i, 8) * 50}ms` }}>
          <span className="w-6 pt-1 text-right font-mono text-[11px] text-fg-3 shrink-0">{s.number}</span>
          <div
            className="relative flex-1 aspect-[16/9] rounded-xl overflow-hidden px-8 py-6 flex flex-col"
            style={{ background: 'linear-gradient(160deg, #1c1c24, #15151b)', boxShadow: 'inset 0 0 0 1px var(--line-strong), 0 14px 30px -18px rgba(0,0,0,0.8)' }}
          >
            {s.title && <div className="font-display text-[20px] font-semibold leading-tight text-fg mb-3 select-text">{s.title}</div>}
            <ul className="flex flex-col gap-1.5 overflow-hidden select-text">
              {s.paragraphs.map((p, k) => (
                <li key={k} className="flex gap-2 text-[13px] leading-snug text-fg-2" style={{ paddingLeft: p.level * 18 }}>
                  <span className="text-fg-3">•</span>
                  <span>{p.text}</span>
                </li>
              ))}
            </ul>
            {!s.title && s.paragraphs.length === 0 && <div className="m-auto text-[12px] text-fg-3">No text on this slide</div>}
            {s.images > 0 && (
              <span className="absolute bottom-3 right-4 flex items-center gap-1 text-[11px] text-fg-3">
                <ImageIcon className="w-3.5 h-3.5" /> {s.images} image{s.images > 1 ? 's' : ''}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  </div>
);
