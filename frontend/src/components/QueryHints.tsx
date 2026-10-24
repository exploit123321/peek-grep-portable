import React, { useEffect, useRef, useState } from 'react';
import { HelpCircle } from 'lucide-react';
import { ExplainChip } from '../api';
import { SearchOptions } from '../utils/searchOptions';

// What the smart search understood (chips under the search field) and a short syntax guide.

const CHIP_STYLE: Record<string, { label: string; color: string; bg: string }> = {
  ext: { label: 'only', color: '#6ee7a8', bg: 'rgba(34,197,94,0.11)' },
  name: { label: 'name has', color: 'var(--accent)', bg: 'var(--accent-soft)' },
  exact: { label: 'name is', color: 'var(--accent)', bg: 'var(--accent-soft)' },
  any: { label: 'name or text', color: 'var(--text)', bg: 'var(--surface-2)' },
  text: { label: 'text has', color: '#7dd3fc', bg: 'rgba(56,189,248,0.11)' },
  groups: { label: '', color: '#fcd34d', bg: 'rgba(251,191,36,0.11)' },
  param: { label: '', color: '#d8b4fe', bg: 'rgba(192,132,252,0.12)' },
  'param-error': { label: 'not understood', color: '#fda4af', bg: 'rgba(240,97,109,0.11)' },
  not: { label: 'without', color: '#fda4af', bg: 'rgba(240,97,109,0.11)' },
};

/** True when the chips say more than the plain words that were typed. */
export function chipsWorthShowing(chips: ExplainChip[], o: SearchOptions): boolean {
  if (!chips.length || !o.enabled) return false;
  const plain = { names: 'name', text: 'text', both: 'any' }[o.default_scope];
  return !(chips.length === 1 && chips[0].kind === plain && !chips[0].literal);
}

export const QueryChips: React.FC<{ chips: ExplainChip[] }> = ({ chips }) => (
  <div className="flex flex-wrap items-center gap-1.5 min-w-0 fade-up" style={{ animationDuration: '260ms' }}>
    {chips.map((c, i) => {
      const negative = c.kind.startsWith('not-') && c.kind !== 'param-error';
      const base = negative ? c.kind.slice(4) : c.kind;
      const style = negative ? CHIP_STYLE.not : CHIP_STYLE[base] ?? CHIP_STYLE.name;
      let prefix = style.label;
      if (negative) prefix = base === 'ext' ? 'not' : base === 'exact' ? 'name is not' : base === 'name' ? 'name without' : base === 'text' ? 'text without' : 'without';
      // Several words are one phrase (next to each other): shown in quotes
      const phrase = c.literal || (/\S\s+\S/.test(c.text) && !base.startsWith('param'));
      const text = c.kind === 'groups' ? `${c.text} groups` : phrase ? `“${c.text}”` : c.text;
      return (
        <span
          key={i}
          className="inline-flex items-center gap-1 h-[22px] px-2 rounded-md text-[11.5px] whitespace-nowrap max-w-[260px]"
          style={{ background: style.bg, color: style.color }}
          title={c.literal ? 'Literal text (after / or in quotes)' : undefined}
        >
          {prefix && <span className="opacity-70">{prefix}</span>}
          <span className="font-medium truncate">{text}</span>
        </span>
      );
    })}
  </div>
);

/** Where words without the text sign search, in words. */
export function scopeWords(o: SearchOptions): string {
  return o.default_scope === 'names' ? 'file names' : o.default_scope === 'text' ? 'the text inside files' : 'file names and text';
}

/** Examples for the help, written with the signs from the settings. */
function syntaxRows(o: SearchOptions): [string, string][] {
  const { text_char: T, and_char: A, not_char: N, literal_char: L, param_char: P } = o;
  const near = (x: string) => (o.dash_mode === 'anywhere' ? `invoice${N}${x}` : `invoice ${N}${x}`);
  const rows: [string, string][] = [['invoice', `${scopeWords(o)} with “invoice”`]];
  if (o.exact_names && o.default_scope !== 'text') rows.push(['invoice.xlsx', 'exactly this file name']);
  if (o.extensions) rows.push(['.xlsx', 'only .xlsx files']);
  if (A && o.extensions) rows.push([`invoice${A}.xlsx`, '“invoice”, only .xlsx files']);
  if (N && o.extensions) rows.push([near('.xlsx'), '“invoice”, but no .xlsx files']);
  if (N) rows.push([near('old'), '“invoice”, without “old”']);
  if (T) {
    rows.push([`${T}total`, '“total” in the text of any file']);
    if (o.extensions) rows.push([`.xlsx${T}total`, '“total” in the text of .xlsx files']);
    rows.push([`invoice${T}total`, '“total” in the text of files named “invoice”']);
  }
  if (T) rows.push([`${T}annual review`, 'these words next to each other (a phrase)']);
  if (A) rows.push([`${T}total${A}memo`, 'both words, anywhere in the text']);
  if (o.group_open) rows.push([`${o.group_open}invoice${o.list_char} receipt${o.group_close}`, 'one expandable row per value']);
  if (o.wildcards) rows.push(['tot*l  rec?ipt', 'wildcards: * any characters, ? one']);
  if (L) rows.push([`${L}e${N || '-'}mail`, `${L} makes the rest literal`]);
  if (o.quotes) rows.push([`"e${N || '-'}mail"`, 'quotes: literal text']);
  if (P) {
    const day = (d: number, m: number) => (o.date_order === 'mdy' ? `${m}/${d}/2024` : o.date_order === 'ymd' ? `2024-0${m}-${String(d).padStart(2, '0')}` : `${String(d).padStart(2, '0')}-0${m}-2024`);
    rows.push([`invoice${P}dm from ${day(1, 3)} to ${day(31, 3)}`, 'modified in March 2024 (both days count)']);
    rows.push([`${P}dc to ${day(15, 6)}`, 'created on 15 June 2024 or before']);
    rows.push([`${P}da 7d`, 'accessed in the last 7 days (also 2w, 3m, 1y)']);
    rows.push([`${P}size>10mb`, 'bigger than 10 MB (b, kb, mb, gb, tb)']);
    rows.push([`${P}size from 1mb to 50mb`, 'sizes in a range (also: small, large, huge)']);
    rows.push([`${P}cd folder1${A || '+'}folder 2`, 'only files in these folders (any depth)']);
    rows.push([`${P}-cd old`, 'leave out files in folders named “old”']);
    if (T && o.extensions) rows.push([`.xlsx${P}size>150mb${T}product`, 'filters can come before the text search too']);
  }
  return rows;
}

interface SyntaxHelpProps {
  options: SearchOptions;
  onInsert: (text: string) => void;
  onToggleSmart: () => void;
  onOpenSettings: () => void;
  listKey?: string;
}

export const SyntaxHelp: React.FC<SyntaxHelpProps> = ({ options: o, onInsert, onToggleSmart, onOpenSettings, listKey }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener('mousedown', close);
    return () => window.removeEventListener('mousedown', close);
  }, [open]);
  return (
    <div className="relative shrink-0" ref={ref}>
      <button type="button" className="icon-btn" onClick={() => setOpen(v => !v)} title="Search syntax">
        <HelpCircle className="w-4 h-4" />
      </button>
      {open && (
        <div
          className="absolute right-0 top-10 z-40 w-[420px] max-h-[calc(100vh-150px)] overflow-y-auto p-1.5 rounded-xl fade-up"
          style={{
            background: 'rgba(24,24,31,0.98)',
            backdropFilter: 'blur(14px)',
            boxShadow: 'inset 0 0 0 1px var(--line-strong), 0 18px 40px -12px rgba(0,0,0,0.75)',
            animationDuration: '240ms',
          }}
        >
          {o.enabled ? (
            <>
              <div className="label-caps px-2.5 pt-1.5 pb-1">Smart search · click to try</div>
              {syntaxRows(o).map(([example, meaning]) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => {
                    onInsert(example.split('  ')[0]);
                    setOpen(false);
                  }}
                  className="flex items-center gap-3 w-full min-h-[30px] px-2.5 py-1 rounded-md text-left hover:bg-surface-2 transition-colors"
                >
                  <span className="w-[150px] shrink-0 font-mono text-[12px] text-accent break-all">{example}</span>
                  <span className="text-[12px] text-fg-2">{meaning}</span>
                </button>
              ))}
              <div className="px-2.5 pt-1.5 pb-1 text-[11.5px] text-fg-3 leading-relaxed" style={{ borderTop: '1px solid var(--line)', marginTop: 4 }}>
                Words search {scopeWords(o)}{o.text_char && o.default_scope !== 'text' ? `; after “${o.text_char}” the text inside files` : ''}.
                Not case-sensitive.{o.group_open ? ` Paste cells from Excel to search a list${listKey ? ` (or ${listKey})` : ''}.` : ''}
              </div>
            </>
          ) : (
            <div className="px-2.5 py-2 text-[12.5px] text-fg-2 leading-relaxed">
              Smart search is off: the search field is plain text and searches {scopeWords(o)}. No sign has a meaning.
            </div>
          )}
          <div className="flex items-center gap-2 px-2.5 pt-1.5 pb-1">
            <button type="button" className="btn !h-7" onClick={() => { onToggleSmart(); setOpen(false); }}>
              {o.enabled ? 'Turn smart search off' : 'Turn smart search on'}
            </button>
            <button type="button" className="btn !h-7" onClick={() => { onOpenSettings(); setOpen(false); }}>
              Search settings…
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
