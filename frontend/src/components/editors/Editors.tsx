import React, { useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Lock, Minus, Plus } from 'lucide-react';
import { EditModel } from '../../api';
import { HighlightTerm, textTerms } from '../../utils/query';
import { textSpans } from '../../utils/searchHits';
import { HitsContext, JumpContext, VirtualGrid } from '../VirtualGrid';

// Each editor reports its save payload and whether anything changed.
export interface EditorProps {
  model: EditModel;
  onChange: (payload: Record<string, unknown>, dirty: boolean) => void;
  /** Find (and the search): the hits are counted and shown while editing too */
  terms?: HighlightTerm[];
}

/** Report hits to Quick Look (count, current, next/previous) like the table views do. */
function useHitReport<T>(hits: T[], go: (hit: T) => void, skipFirstJump = false) {
  const report = useContext(HitsContext);
  const jump = useContext(JumpContext);
  const [index, setIndex] = useState(0);
  const ref = useRef(0);
  ref.current = index;
  const skip = useRef(skipFirstJump);
  useEffect(() => {
    setIndex(0);
    ref.current = 0;
    if (skip.current) skip.current = false;
    else if (hits.length && jump) requestAnimationFrame(() => go(hits[0]));
  }, [hits]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!hits.length) {
      report(null);
      return;
    }
    report({
      count: hits.length,
      index: Math.min(index, hits.length - 1),
      go: step => {
        const next = (ref.current + step + hits.length) % hits.length;
        ref.current = next;
        setIndex(next);
        go(hits[next]);
      },
    });
  }, [hits, index]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => report(null), [report]);
  return Math.min(index, Math.max(0, hits.length - 1));
}

const LINE_H = 12 * 1.65;
const CHAR_W = 7.22; // 12px monospace

// -- Text ---------------------------------------------------------------------------

/** The line at the top of the text editor (for the preview to go back there). */
export function editorTopLine(root: HTMLElement | null): number | null {
  const el = root?.querySelector<HTMLElement>('[data-text-editor]');
  return el ? Math.floor(Math.max(0, el.scrollTop - 16) / LINE_H) + 1 : null;
}

// Never wrapped: every line is one row, so the spacing is exactly what is saved
export const TextEditor: React.FC<EditorProps & { initial?: string; initialLine?: number | null }> = ({
  model, onChange, initial, terms, initialLine,
}) => {
  const original = initial ?? model.text ?? '';
  const [text, setText] = useState(original);
  const ref = useRef<HTMLTextAreaElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [shiftX, setShiftX] = useState(0);
  // No scrolling to the cursor: the editor opens where the preview was (at its top line)
  useLayoutEffect(() => {
    if (initialLine && scrollRef.current) scrollRef.current.scrollTop = 16 + (initialLine - 1) * LINE_H;
    ref.current?.focus({ preventScroll: true });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const lines = useMemo(() => text.split('\n').length, [text]);

  // Hits: marked on a layer behind the (transparent) text field
  const termsKey = JSON.stringify(terms ?? []);
  const spans = useMemo(
    () => (textTerms(terms ?? []).length ? textSpans(text, terms ?? []) : []),
    [text, termsKey], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const current = useHitReport(spans, ([a]) => {
    const el = scrollRef.current;
    const area = ref.current;
    if (!el || !area) return;
    const before = text.lastIndexOf('\n', a - 1);
    const line = text.slice(0, a).split('\n').length - 1;
    el.scrollTop = Math.max(0, 16 + line * LINE_H - el.clientHeight / 3);
    const x = (a - before - 1) * CHAR_W;
    if (x < area.scrollLeft || x > area.scrollLeft + area.clientWidth - 40) area.scrollLeft = Math.max(0, x - area.clientWidth / 3);
  }, true);
  const marked = useMemo(() => {
    if (!spans.length) return null;
    const out: React.ReactNode[] = [];
    let pos = 0;
    spans.forEach(([a, b], i) => {
      if (a > pos) out.push(text.slice(pos, a));
      out.push(<mark key={i} className={i === current ? 'edit-hit-current' : 'edit-hit'}>{text.slice(a, b)}</mark>);
      pos = b;
    });
    out.push(text.slice(pos));
    return out;
  }, [spans, current, text]);

  return (
    <div className="flex flex-col h-full">
      <div ref={scrollRef} data-text-editor className="flex-1 min-h-0 flex overflow-auto">
        <pre className="select-none text-right pl-3 pr-3 py-4 font-mono text-[12px] leading-[1.65] text-fg-3 opacity-60" style={{ borderRight: '1px solid var(--line)' }}>
          {Array.from({ length: lines }, (_, i) => i + 1).join('\n')}
        </pre>
        {/* As tall as all lines: the layer with the hits must not be cut at the window height */}
        <div className="relative flex-1 min-w-0" style={{ minHeight: `${lines * LINE_H + 32}px` }}>
        {marked && (
          <pre
            aria-hidden
            className="absolute inset-0 overflow-hidden px-4 py-4 font-mono text-[12px] leading-[1.65] whitespace-pre pointer-events-none"
            style={{ color: 'transparent', tabSize: 4 }}
          >
            <div style={{ transform: `translateX(${-shiftX}px)` }}>{marked}</div>
          </pre>
        )}
        <textarea
          ref={ref}
          value={text}
          spellCheck={false}
          wrap="off"
          onScroll={e => setShiftX((e.target as HTMLTextAreaElement).scrollLeft)}
          onChange={e => {
            setText(e.target.value);
            onChange({ text: e.target.value }, e.target.value !== original);
          }}
          onKeyDown={e => {
            if (e.key === 'Tab') {
              e.preventDefault();
              const el = e.currentTarget;
              const { selectionStart: a, selectionEnd: b } = el;
              const next = text.slice(0, a) + '\t' + text.slice(b);
              setText(next);
              onChange({ text: next }, next !== original);
              requestAnimationFrame(() => el.setSelectionRange(a + 1, a + 1));
            }
          }}
          className="relative block w-full h-full resize-none bg-transparent px-4 py-4 font-mono text-[12px] leading-[1.65] text-fg outline-none select-text"
          style={{ tabSize: 4, minHeight: `${lines * 1.65 * 12 + 32}px` }}
        />
        </div>
      </div>
      <div className="flex items-center gap-3 h-8 px-4 shrink-0 text-[11.5px] text-fg-3 num" style={{ borderTop: '1px solid var(--line)' }}>
        <span>{model.encoding}</span>
        <span>{model.newline === '\r\n' ? 'CRLF' : model.newline === '\r' ? 'CR' : 'LF'}</span>
        <span>{lines.toLocaleString()} lines</span>
      </div>
    </div>
  );
};

// -- CSV ----------------------------------------------------------------------------

const csvRowNumber = (r: number) => r;

export const CsvEditor: React.FC<EditorProps> = ({ model, onChange, terms }) => {
  const [rows, setRows] = useState<string[][]>(() => (model.rows ?? []).map(r => [...r]));
  const [edited, setEdited] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<number | null>(null);
  const [structural, setStructural] = useState(false);
  const width = Math.max(1, ...rows.map(r => r.length));
  const columns = Array.from({ length: width }, (_, i) => String(i + 1));

  const emit = (next: string[][], dirty: boolean) => {
    setRows(next);
    onChange({ rows: next, delimiter: model.delimiter }, dirty);
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-4 h-11 shrink-0 text-[12px] text-fg-3" style={{ borderBottom: '1px solid var(--line)' }}>
        <span>Separator: {model.delimiter} · {rows.length.toLocaleString()} rows · click a cell to edit, Enter and Tab move</span>
        <span className="flex-1" />
        <button
          type="button"
          className="btn !h-7"
          onClick={() => {
            const next = [...rows];
            next.splice(selected === null ? next.length : selected + 1, 0, Array(width).fill(''));
            setStructural(true);
            emit(next, true);
          }}
        >
          <Plus className="w-3.5 h-3.5" /> Row
        </button>
        <button
          type="button"
          className="btn !h-7"
          disabled={selected === null}
          title="Click a row number first"
          onClick={() => {
            if (selected === null) return;
            const next = rows.filter((_, i) => i !== selected);
            setSelected(null);
            setEdited(new Set());
            setStructural(true);
            emit(next, true);
          }}
        >
          <Minus className="w-3.5 h-3.5" /> Row
        </button>
      </div>
      <div className="flex-1 min-h-0">
        <VirtualGrid
          editable
          columns={columns}
          rows={rows}
          // Numbered like the preview: the header is H, the first data row 1
          rowLabel={r => (r === 0 ? 'H' : r)}
          rowNumber={csvRowNumber}
          terms={terms}
          edited={structural ? new Set() : edited}
          selectedRow={selected}
          onSelectRow={r => setSelected(s => (s === r ? null : r))}
          onEdit={(r, c, value) => {
            const next = rows.map(row => [...row]);
            while (next[r].length <= c) next[r].push('');
            next[r][c] = value;
            setEdited(e => new Set(e).add(`${r},${c}`));
            emit(next, true);
          }}
        />
      </div>
    </div>
  );
};

// -- Excel --------------------------------------------------------------------------

export const WorkbookEditor: React.FC<EditorProps & { sheet?: number; onSheet?: (i: number) => void }> = ({
  model, onChange, terms, sheet: shownSheet, onSheet,
}) => {
  const sheets = model.sheets ?? [];
  // The sheet that the preview showed
  const [index, setOwnIndex] = useState(() => Math.min(shownSheet ?? 0, Math.max(0, sheets.length - 1)));
  const setIndex = (i: number) => {
    setOwnIndex(i);
    onSheet?.(i);
  };
  const [data, setData] = useState(() => sheets.map(s => s.rows.map(r => [...r])));
  const [changes, setChanges] = useState<Record<string, Record<string, string>>>({});
  const sheet = sheets[index];
  if (!sheet) return <div className="py-20 text-center text-fg-3">This workbook has no sheets.</div>;

  // Some empty space to the right and below, so that new cells can be filled in
  const cols = Math.min(60, Math.max(sheet.columns.length + 3, 8));
  const rowsCount = Math.max(data[index].length + 20, 40);
  const columns = Array.from({ length: cols }, (_, i) => {
    let n = i + 1, s = '';
    while (n) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); }
    return s;
  });
  const grid = Array.from({ length: rowsCount }, (_, r) => data[index][r] ?? []);
  const locked = new Set(sheet.formulas.map(([r, c]) => `${r},${c}`));
  const edited = new Set(Object.keys(changes[sheet.name] ?? {}));

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-4 h-11 shrink-0 text-[12px] text-fg-3" style={{ borderBottom: '1px solid var(--line)' }}>
        Click a cell to edit. Formula cells
        <Lock className="w-3 h-3" />
        are locked. Dates use the form 2026-12-24.
        {sheet.truncated && <span className="text-warn">This sheet is larger than the preview limit; only the loaded part can be edited here.</span>}
      </div>
      <div className="flex-1 min-h-0">
        <VirtualGrid
          key={index}
          editable
          columns={columns}
          rows={grid}
          terms={terms}
          edited={edited}
          locked={locked}
          onEdit={(r, c, value) => {
            const nextData = data.map(s => s.map(row => [...row]));
            while (nextData[index].length <= r) nextData[index].push([]);
            while (nextData[index][r].length <= c) nextData[index][r].push('');
            nextData[index][r][c] = value;
            setData(nextData);
            const next = { ...changes, [sheet.name]: { ...(changes[sheet.name] ?? {}), [`${r},${c}`]: value } };
            setChanges(next);
            onChange({ changes: next }, true);
          }}
        />
      </div>
      {sheets.length > 1 && (
        <div className="flex items-center gap-1 px-2 h-10 shrink-0 overflow-x-auto" style={{ borderTop: '1px solid var(--line)' }}>
          {sheets.map((s, i) => (
            <button
              key={`${s.name}-${i}`}
              type="button"
              onClick={() => setIndex(i)}
              className={`h-7 px-3 rounded-md text-[12px] whitespace-nowrap ${i === index ? 'bg-surface-2 text-fg shadow-[inset_0_-2px_0_var(--ok)]' : 'text-fg-3 hover:text-fg hover:bg-surface-2'}`}
            >
              {s.name}
              {changes[s.name] && Object.keys(changes[s.name]).length > 0 && <span className="ml-1.5 text-ok">●</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

// -- Word ---------------------------------------------------------------------------

const AutoTextarea: React.FC<{ value: string; onChange: (v: string) => void; className: string }> = ({ value, onChange, className }) => {
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el) {
      el.style.height = 'auto';
      el.style.height = `${el.scrollHeight}px`;
    }
  }, [value]);
  return (
    <textarea
      ref={ref}
      rows={1}
      value={value}
      spellCheck
      onChange={e => onChange(e.target.value)}
      className={`w-full resize-none overflow-hidden bg-transparent outline-none rounded-md px-2 py-1 -mx-2 hover:bg-[rgba(255,255,255,0.03)] focus:bg-[rgba(124,156,255,0.06)] select-text ${className}`}
    />
  );
};

export const DocumentEditor: React.FC<EditorProps> = ({ model, onChange, terms }) => {
  const paragraphs = model.paragraphs ?? [];
  const [values, setValues] = useState<Record<number, string>>({});
  const boxRef = useRef<HTMLDivElement>(null);

  // Hits per paragraph: the current one is scrolled to and outlined
  const termsKey = JSON.stringify(terms ?? []);
  const hits = useMemo(() => {
    if (!textTerms(terms ?? []).length) return [] as number[];
    const out: number[] = [];
    for (const p of paragraphs) {
      for (let k = textSpans(values[p.id] ?? p.text, terms ?? []).length; k > 0; k--) out.push(p.id);
    }
    return out;
  }, [values, termsKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const current = useHitReport(hits, id => {
    boxRef.current?.querySelector(`[data-para="${id}"]`)?.scrollIntoView({ block: 'center' });
  }, true);
  const currentId = hits.length ? hits[current] : null;
  const ring = (id: number) => (id === currentId ? { boxShadow: '0 0 0 2px rgba(250,204,21,0.75)', borderRadius: 6 } : undefined);

  return (
    <div ref={boxRef} className="h-full overflow-auto">
      <div className="max-w-[760px] mx-auto px-8 py-6 flex flex-col gap-0.5">
        <div className="mb-3 px-3 py-2 rounded-lg text-[12px] text-fg-2" style={{ background: 'var(--bg-elev)', boxShadow: 'inset 0 0 0 1px var(--line)' }}>
          Edit the text of a paragraph. Paragraphs that you do not change stay exactly as they are. A changed
          paragraph keeps its style, but mixed formatting inside it becomes one format. Paragraphs with
          pictures, links, fields, or tracked changes are locked.
        </div>
        {paragraphs.map(p => {
          const style = p.style.toLowerCase();
          const size = style === 'title' ? 'text-[22px] font-semibold' : /heading ?1/.test(style) ? 'text-[19px] font-semibold'
            : /heading ?[2-6]/.test(style) ? 'text-[16px] font-semibold' : 'text-[13.5px]';
          const value = values[p.id] ?? p.text;
          if (p.locked) {
            return (
              <div key={p.id} data-para={p.id} style={ring(p.id)} className={`flex items-start gap-2 px-0 py-1 text-fg-3 ${size}`} title="Locked: this paragraph has a picture, link, field, or tracked change">
                <Lock className="w-3 h-3 mt-1.5 shrink-0" />
                <span className="whitespace-pre-wrap">{p.text || '(picture or object)'}</span>
              </div>
            );
          }
          return (
            <div key={p.id} data-para={p.id} style={ring(p.id)} className={`flex items-start gap-2 ${p.table ? 'pl-4' : ''}`}>
              {p.table && <span className="mt-1.5 text-[10px] text-fg-3 uppercase tracking-wider w-8 shrink-0">cell</span>}
              <AutoTextarea
                value={value}
                className={`${size} leading-relaxed ${values[p.id] !== undefined && values[p.id] !== p.text ? 'text-ok' : 'text-fg'}`}
                onChange={v => {
                  const next = { ...values, [p.id]: v };
                  setValues(next);
                  const changes: Record<string, string> = {};
                  for (const para of paragraphs) {
                    const nv = next[para.id];
                    if (nv !== undefined && nv !== para.text) changes[String(para.id)] = nv;
                  }
                  onChange({ changes }, Object.keys(changes).length > 0);
                }}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
};
