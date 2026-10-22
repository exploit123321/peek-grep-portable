import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ClipboardList, Plus, Search, Trash2, X } from 'lucide-react';
import { SegmentedControl } from './motion/SegmentedControl';
import { AnimatedCheckbox } from './motion/AnimatedCheckbox';
import { ListMode, listToQuery, ListWhere } from '../utils/query';

// Search a list: values pasted from Excel (one per cell or per row) open here as a table.
// Edit, remove, or add values, then search them in file names or in the text, as expandable
// groups ([a, b]) or together (a+b).

interface ListEditorProps {
  grid: string[][];
  mode: ListMode;
  where: ListWhere;
  filter: string;
  source: 'paste' | 'edit' | 'new';
  onConfirm: (values: string[], mode: ListMode, where: ListWhere, filter: string) => void;
  onClose: () => void;
}

type Split = 'cells' | 'rows';

interface Value {
  id: number;
  text: string;
  on: boolean;
}

let nextId = 1;

function valuesFrom(grid: string[][], split: Split): { values: Value[]; duplicates: number } {
  const raw = split === 'rows'
    ? grid.map(r => r.map(c => c.trim()).filter(Boolean).join(' '))
    : grid.flat().map(c => c.trim());
  const seen = new Set<string>();
  const values: Value[] = [];
  let duplicates = 0;
  for (const v of raw) {
    const text = v.replace(/\s+/g, ' ').trim();
    if (!text) continue;
    const key = text.toLowerCase();
    if (seen.has(key)) {
      duplicates++;
      continue;
    }
    seen.add(key);
    values.push({ id: nextId++, text, on: true });
  }
  return { values, duplicates };
}

const MODES = [
  { id: 'groups' as const, label: 'Expandable', hint: 'One expandable row per value: [a, b, c]' },
  { id: 'together' as const, label: 'Together (+)', hint: 'Files that hit every value: a+b+c' },
];

const WHERE = [
  { id: 'names' as const, label: 'File names', hint: 'Values in the file names' },
  { id: 'text' as const, label: 'Text', hint: 'Values in the text inside the files (after ":")' },
];

const SPLITS = [
  { id: 'cells' as const, label: 'Each cell', hint: 'Every cell is a value' },
  { id: 'rows' as const, label: 'Each row', hint: 'The cells of a row are one value' },
];

export const ListEditor: React.FC<ListEditorProps> = ({ grid, mode: initialMode, where: initialWhere, filter: initialFilter, source, onConfirm, onClose }) => {
  const columns = useMemo(() => Math.max(0, ...grid.map(r => r.length)), [grid]);
  const [split, setSplit] = useState<Split>('cells');
  const [{ values, duplicates }, setState] = useState(() => valuesFrom(grid, 'cells'));
  const [mode, setMode] = useState<ListMode>(initialMode);
  const [where, setWhere] = useState<ListWhere>(initialWhere);
  const [filter, setFilter] = useState(initialFilter);
  const inputs = useRef<Map<number, HTMLInputElement>>(new Map());
  const focusId = useRef<number | null>(null);

  useEffect(() => {
    if (focusId.current !== null) {
      inputs.current.get(focusId.current)?.focus();
      focusId.current = null;
    }
  });

  useEffect(() => {
    if (!values.length) addValue();
    else if (source === 'new') inputs.current.get(values[0].id)?.focus();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const setValues = (fn: (v: Value[]) => Value[]) => setState(s => ({ ...s, values: fn(s.values) }));

  const addValue = (after?: number) => {
    const v: Value = { id: nextId++, text: '', on: true };
    focusId.current = v.id;
    setValues(list => {
      if (after === undefined) return [...list, v];
      const i = list.findIndex(x => x.id === after);
      return [...list.slice(0, i + 1), v, ...list.slice(i + 1)];
    });
  };

  const active = values.filter(v => v.on && v.text.trim()).map(v => v.text);
  const preview = listToQuery(active, mode, where, filter);
  const confirm = () => {
    if (active.length) onConfirm(active, mode, where, filter);
  };

  return (
    <div
      className="fixed inset-0 z-[75] flex items-center justify-center p-6"
      onKeyDown={e => {
        e.stopPropagation();
        if (e.key === 'Escape') {
          e.preventDefault();
          onClose();
        } else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
          e.preventDefault();
          confirm();
        }
      }}
    >
      <div className="absolute inset-0 fade-up" style={{ background: 'rgba(5,5,8,0.62)', backdropFilter: 'blur(6px)', animationDuration: '220ms' }} onClick={onClose} />
      <div
        className="relative flex flex-col w-full max-w-[620px] max-h-full rounded-2xl overflow-hidden fade-up"
        style={{ background: 'var(--bg-elev)', boxShadow: 'inset 0 0 0 1px var(--line-strong), 0 40px 100px -30px rgba(0,0,0,0.9)', animationDuration: '320ms' }}
        role="dialog"
        aria-label="Search a list"
      >
        <div className="flex items-center gap-3 h-[58px] pl-4 pr-3 shrink-0" style={{ borderBottom: '1px solid var(--line)' }}>
          <span className="flex items-center justify-center w-8 h-8 rounded-lg text-accent bg-accent-soft">
            <ClipboardList className="w-4 h-4" />
          </span>
          <div className="flex flex-col min-w-0 flex-1">
            <span className="text-[14px] font-semibold text-fg">Search a list</span>
            <span className="text-[11.5px] text-fg-3">
              {source === 'paste' ? 'Pasted ' : ''}
              <span className="num text-fg-2">{active.length.toLocaleString()}</span> value{active.length === 1 ? '' : 's'}
              {duplicates > 0 && <> · <span className="num">{duplicates}</span> duplicate{duplicates === 1 ? '' : 's'} left out</>}
            </span>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} title="Close (Esc)">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 shrink-0" style={{ borderBottom: '1px solid var(--line)' }}>
          <div className="flex items-center gap-2">
            <span className="label-caps">Look in</span>
            <SegmentedControl options={WHERE} value={where} onChange={setWhere} size="sm" />
          </div>
          <div className="flex items-center gap-2">
            <span className="label-caps">Search as</span>
            <SegmentedControl options={MODES} value={mode} onChange={setMode} size="sm" />
          </div>
          {columns > 1 && (
            <div className="flex items-center gap-2">
              <span className="label-caps">Values</span>
              <SegmentedControl
                options={SPLITS}
                value={split}
                onChange={s => {
                  setSplit(s);
                  setState(valuesFrom(grid, s));
                }}
                size="sm"
              />
            </div>
          )}
          <label className="flex items-center gap-2 flex-1 min-w-[180px]">
            <span className="label-caps whitespace-nowrap">Only files</span>
            <input
              className="input !h-7 text-[12px] font-mono"
              value={filter}
              onChange={e => setFilter(e.target.value)}
              placeholder=".xlsx   invoice-old+.pdf   (optional)"
              title="Which files: types like .xlsx and words of the file name, for example invoice-old+.pdf"
              spellCheck={false}
            />
          </label>
        </div>

        <div className="flex-1 min-h-[120px] overflow-y-auto px-2 py-2">
          {values.map((v, i) => (
            <div key={v.id} className="group flex items-center gap-2 h-9 px-2 rounded-lg hover:bg-[rgba(255,255,255,0.025)]">
              <span className="w-7 text-right num text-[11.5px] text-fg-3 shrink-0">{i + 1}</span>
              <button
                type="button"
                className="shrink-0"
                onClick={() => setValues(list => list.map(x => (x.id === v.id ? { ...x, on: !x.on } : x)))}
                title={v.on ? 'Leave this value out' : 'Search this value'}
              >
                <AnimatedCheckbox checked={v.on} />
              </button>
              <input
                ref={el => {
                  if (el) inputs.current.set(v.id, el);
                  else inputs.current.delete(v.id);
                }}
                value={v.text}
                onChange={e => setValues(list => list.map(x => (x.id === v.id ? { ...x, text: e.target.value } : x)))}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey) {
                    e.preventDefault();
                    const next = values[i + 1];
                    if (next) inputs.current.get(next.id)?.focus();
                    else addValue(v.id);
                  } else if (e.key === 'Backspace' && !v.text && values.length > 1) {
                    e.preventDefault();
                    const prev = values[i - 1] ?? values[i + 1];
                    if (prev) focusId.current = prev.id;
                    setValues(list => list.filter(x => x.id !== v.id));
                  } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                    e.preventDefault();
                    const other = values[i + (e.key === 'ArrowDown' ? 1 : -1)];
                    if (other) inputs.current.get(other.id)?.focus();
                  }
                }}
                className={`flex-1 min-w-0 h-7 px-2 rounded-md bg-transparent text-[13px] outline-none select-text focus:bg-[var(--bg)] focus:shadow-[inset_0_0_0_1px_var(--accent-line)] ${v.on ? 'text-fg' : 'text-fg-3 line-through'}`}
                spellCheck={false}
                placeholder="Value"
              />
              <button
                type="button"
                className="icon-btn opacity-0 group-hover:opacity-100 focus:opacity-100"
                onClick={() => setValues(list => list.filter(x => x.id !== v.id))}
                title="Remove"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
          <button type="button" className="flex items-center gap-2 h-9 px-2 ml-9 text-[12.5px] text-fg-3 hover:text-fg transition-colors" onClick={() => addValue()}>
            <Plus className="w-3.5 h-3.5" /> Add value
          </button>
        </div>

        <div className="px-4 py-3 shrink-0 flex flex-col gap-2.5" style={{ borderTop: '1px solid var(--line)' }}>
          <div className="text-[11.5px] text-fg-3 font-mono truncate select-text" title={preview}>
            <span className="label-caps !text-[10px] mr-2 font-sans">Search</span>
            {preview || '—'}
          </div>
          <div className="flex items-center justify-end gap-2">
            <span className="mr-auto text-[11.5px] text-fg-3 flex items-center gap-1.5">
              <span className="kbd">Ctrl</span><span className="kbd">↵</span> Search
            </span>
            <button type="button" className="btn" onClick={onClose}>Cancel</button>
            <button type="button" className="btn-primary" disabled={!active.length} onClick={confirm}>
              <Search className="w-4 h-4" /> Search {active.length > 0 && <span className="num">{active.length}</span>}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
