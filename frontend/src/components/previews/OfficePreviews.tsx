import React, { useMemo, useState } from 'react';
import { Image as ImageIcon, Search } from 'lucide-react';
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

// Excel: one tab per sheet, a grid with column letters and row numbers like Excel
export const WorkbookPreview: React.FC<{ sheets: SheetData[] }> = ({ sheets }) => {
  const [index, setIndex] = useState(0);
  const [filter, setFilter] = useState('');
  const sheet = sheets[Math.min(index, sheets.length - 1)];
  const rows = useMemo(() => {
    if (!sheet) return [];
    const q = filter.toLowerCase();
    const all = sheet.rows.map((r, i) => ({ n: i + 1, cells: r }));
    return q ? all.filter(r => r.cells.some(c => c.toLowerCase().includes(q))) : all;
  }, [sheet, filter]);

  if (!sheet) return <div className="py-20 text-center text-fg-3">This workbook has no sheets.</div>;

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between gap-3 px-4 h-11 shrink-0" style={{ borderBottom: '1px solid var(--line)' }}>
        <span className="text-[12px] text-fg-3 whitespace-nowrap">
          {sheet.total_rows.toLocaleString()} rows · {sheet.total_columns} columns
          {sheet.truncated && ` · first ${sheet.rows.length} rows and ${sheet.columns.length} columns shown`}
        </span>
        <div className="relative w-56">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-fg-3" />
          <input
            className="input !h-7 pl-8 text-[12px]"
            placeholder="Filter rows"
            value={filter}
            onChange={e => setFilter(e.target.value)}
            onKeyDown={e => e.stopPropagation()}
          />
        </div>
      </div>
      <div className="flex-1 overflow-auto select-text">
        <table className="text-left text-[12px] border-collapse font-mono">
          <thead className="sticky top-0 z-10" style={{ background: 'var(--surface-2)' }}>
            <tr>
              <th className="sticky left-0 px-2 py-1.5 w-12 text-center text-fg-3 font-medium" style={{ background: 'var(--surface-2)', borderBottom: '1px solid var(--line-strong)' }} />
              {sheet.columns.map(col => (
                <th key={col} className="px-3 py-1.5 min-w-[90px] text-center text-fg-3 font-medium" style={{ borderBottom: '1px solid var(--line-strong)', borderLeft: '1px solid var(--line)' }}>
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <tr key={row.n} className="hover:bg-[rgba(255,255,255,0.03)]" style={{ borderBottom: '1px solid var(--line)' }}>
                <td className="sticky left-0 px-2 py-1 text-center text-fg-3 select-none" style={{ background: 'var(--bg)' }}>{row.n}</td>
                {sheet.columns.map((_, c) => (
                  <td key={c} className="px-3 py-1 whitespace-nowrap text-fg-2 max-w-[360px] truncate" style={{ borderLeft: '1px solid var(--line)' }}>
                    {row.cells[c] ?? ''}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <div className="py-10 text-center text-fg-3 text-[12.5px]">No rows match “{filter}”</div>}
      </div>
      {sheets.length > 1 && (
        <div className="flex items-center gap-1 px-2 h-10 shrink-0 overflow-x-auto" style={{ borderTop: '1px solid var(--line)' }}>
          {sheets.map((s, i) => (
            <button
              key={`${s.name}-${i}`}
              type="button"
              onClick={() => {
                setIndex(i);
                setFilter('');
              }}
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
