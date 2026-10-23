import React, { useCallback, useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { Delimiter } from '../../api';
import { HighlightTerm } from '../../utils/query';
import { SegmentedControl } from '../motion/SegmentedControl';
import { VirtualGrid } from '../VirtualGrid';

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

interface TablePreviewProps {
  tableData: TableData;
  delimiter: Delimiter;
  onDelimiterChange: (d: Delimiter) => void;
  terms?: HighlightTerm[];
}

export const TablePreview: React.FC<TablePreviewProps> = ({ tableData, delimiter, onDelimiterChange, terms }) => {
  const [filter, setFilter] = useState('');
  const columns = useMemo(() => {
    const width = Math.max(tableData.columns.length, ...tableData.rows.slice(0, 500).map(r => r.length));
    return Array.from({ length: width }, (_, i) => tableData.columns[i] || `Column ${i + 1}`);
  }, [tableData]);
  const rows = useMemo(() => {
    const q = filter.toLowerCase();
    const all = tableData.rows.map((r, i) => ({ r, n: i + 1 }));
    return q ? all.filter(x => x.r.some(c => c.toLowerCase().includes(q))) : all;
  }, [tableData, filter]);
  const dataRows = tableData.total_rows - 1;
  const rowNumber = useCallback((i: number) => rows[i]?.n ?? i + 1, [rows]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between gap-3 px-4 h-11 shrink-0" style={{ borderBottom: '1px solid var(--line)' }}>
        <div className="flex items-center gap-2.5 min-w-0">
          <SegmentedControl options={SEPARATORS} value={delimiter} onChange={onDelimiterChange} size="sm" />
          {delimiter === 'auto' && tableData.detected && (
            <span className="text-[11.5px] text-fg-3 whitespace-nowrap">Found: {tableData.delimiter}</span>
          )}
        </div>
        <span className="text-[12px] text-fg-3 whitespace-nowrap ml-auto">
          {columns.length} columns · {Math.max(0, dataRows).toLocaleString()} rows
          {tableData.rows.length < dataRows && ` · first ${tableData.rows.length.toLocaleString()} shown`}
        </span>
        <div className="relative w-52">
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
      <div className="flex-1 min-h-0">
        <VirtualGrid columns={columns} rows={rows.map(x => x.r)} rowLabel={i => rows[i]?.n} rowNumber={rowNumber} terms={terms} />
        {rows.length === 0 && <div className="py-10 text-center text-fg-3 text-[12.5px]">No rows match “{filter}”</div>}
      </div>
    </div>
  );
};
