import React, { useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { Delimiter } from '../../api';
import { SegmentedControl } from '../motion/SegmentedControl';

interface TableData {
  columns: string[];
  rows: string[][];
  total_rows: number;
  total_columns: number;
  delimiter: Exclude<Delimiter, 'auto'>;
  detected: boolean;
}

// Auto finds the separator; the other options force one (comma, semicolon, tab, colon, pipe, space)
const SEPARATORS: { id: Delimiter; label: string; hint: string }[] = [
  { id: 'auto', label: 'Auto', hint: 'Find the separator automatically' },
  { id: 'comma', label: ',', hint: 'Comma' },
  { id: 'semicolon', label: ';', hint: 'Semicolon' },
  { id: 'tab', label: 'Tab', hint: 'Tab' },
  { id: 'colon', label: ':', hint: 'Colon' },
  { id: 'pipe', label: '|', hint: 'Pipe' },
  { id: 'space', label: 'Space', hint: 'Space' },
];

const NAMES: Record<string, string> = {
  comma: 'comma', semicolon: 'semicolon', tab: 'tab', colon: 'colon', pipe: 'pipe', space: 'space',
};

interface TablePreviewProps {
  tableData: TableData;
  delimiter: Delimiter;
  onDelimiterChange: (d: Delimiter) => void;
}

export const TablePreview: React.FC<TablePreviewProps> = ({ tableData, delimiter, onDelimiterChange }) => {
  const [filter, setFilter] = useState('');
  const rows = useMemo(() => {
    const q = filter.toLowerCase();
    return q ? tableData.rows.filter(r => r.some(c => c.toLowerCase().includes(q))) : tableData.rows;
  }, [tableData, filter]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between gap-3 px-4 h-11 shrink-0" style={{ borderBottom: '1px solid var(--line)' }}>
        <div className="flex items-center gap-2.5 min-w-0">
          <SegmentedControl options={SEPARATORS} value={delimiter} onChange={onDelimiterChange} size="sm" />
          {delimiter === 'auto' && tableData.detected && (
            <span className="text-[11.5px] text-fg-3 whitespace-nowrap">Found: {NAMES[tableData.delimiter]}</span>
          )}
        </div>
        <span className="text-[12px] text-fg-3 whitespace-nowrap ml-auto">
          {tableData.total_columns} columns · {Math.max(0, tableData.total_rows - 1).toLocaleString()} rows
          {tableData.rows.length < tableData.total_rows - 1 && ` · first ${tableData.rows.length} shown`}
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
        <table className="w-full text-left text-[12px] border-collapse font-mono">
          <thead className="sticky top-0 z-10" style={{ background: 'var(--surface-2)' }}>
            <tr>
              <th className="px-3 py-2 w-10 text-center text-fg-3 font-medium" style={{ borderBottom: '1px solid var(--line-strong)' }}>#</th>
              {tableData.columns.map((col, i) => (
                <th key={i} className="px-3.5 py-2 whitespace-nowrap text-fg font-semibold" style={{ borderBottom: '1px solid var(--line-strong)' }}>
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, r) => (
              <tr key={r} className="hover:bg-[rgba(255,255,255,0.03)]" style={{ borderBottom: '1px solid var(--line)' }}>
                <td className="px-3 py-1.5 text-center text-fg-3 select-none">{r + 1}</td>
                {row.map((cell, c) => (
                  <td key={c} className="px-3.5 py-1.5 whitespace-nowrap text-fg-2">{cell}</td>
                ))}
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={tableData.columns.length + 1} className="px-4 py-10 text-center text-fg-3 font-sans">
                  No rows match “{filter}”
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
