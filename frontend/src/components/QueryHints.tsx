import React, { useEffect, useRef, useState } from 'react';
import { HelpCircle } from 'lucide-react';
import { ExplainChip } from '../api';

// What the smart search understood (chips under the search field) and a short syntax guide.

const CHIP_STYLE: Record<string, { label: string; color: string; bg: string }> = {
  ext: { label: 'only', color: '#6ee7a8', bg: 'rgba(34,197,94,0.11)' },
  name: { label: 'name has', color: 'var(--accent)', bg: 'var(--accent-soft)' },
  exact: { label: 'name is', color: 'var(--accent)', bg: 'var(--accent-soft)' },
  text: { label: 'text has', color: '#7dd3fc', bg: 'rgba(56,189,248,0.11)' },
  groups: { label: '', color: '#fcd34d', bg: 'rgba(251,191,36,0.11)' },
  not: { label: 'without', color: '#fda4af', bg: 'rgba(240,97,109,0.11)' },
};

/** True when the chips say more than a plain file name search. */
export function chipsWorthShowing(chips: ExplainChip[]): boolean {
  if (!chips.length) return false;
  return !(chips.length === 1 && chips[0].kind === 'name' && !chips[0].literal);
}

export const QueryChips: React.FC<{ chips: ExplainChip[] }> = ({ chips }) => (
  <div className="flex flex-wrap items-center gap-1.5 min-w-0 fade-up" style={{ animationDuration: '260ms' }}>
    {chips.map((c, i) => {
      const negative = c.kind.startsWith('not-');
      const base = negative ? c.kind.slice(4) : c.kind;
      const style = negative ? CHIP_STYLE.not : CHIP_STYLE[base] ?? CHIP_STYLE.name;
      let prefix = style.label;
      if (negative) prefix = base === 'ext' ? 'not' : base === 'exact' ? 'name is not' : base === 'name' ? 'name without' : 'text without';
      const text = c.kind === 'groups' ? `${c.text} groups` : c.literal ? `“${c.text}”` : c.text;
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

const SYNTAX: [string, string][] = [
  ['invoice', 'file names with “invoice” (invoice1.xlsx…)'],
  ['invoice.xlsx', 'exactly this file name'],
  ['invoice+.xlsx', 'names with “invoice”, only .xlsx files'],
  ['invoice-.xlsx', 'names with “invoice”, but no .xlsx'],
  ['invoice-old', 'names with “invoice”, without “old”'],
  [':total', '“total” in the text of any file'],
  ['.xlsx:total', '“total” in the text of .xlsx files'],
  ['invoice-old+.xlsx+.pdf:total', '“total” in .xlsx and .pdf files named “invoice”, not “old”'],
  [':total+memo', 'texts with both words (:total-draft: without “draft”)'],
  ['[invoice, receipt]', 'one expandable row per value (also :[a, b])'],
  ['tot*l  rec?ipt', 'wildcards: * any characters, ? one'],
  ['/e-mail', '/ or "quotes": literal, here a real “-”'],
];

export const SyntaxHelp: React.FC<{ onInsert: (text: string) => void; listKey?: string }> = ({ onInsert, listKey }) => {
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
          className="absolute right-0 top-10 z-40 w-[420px] p-1.5 rounded-xl fade-up"
          style={{
            background: 'rgba(24,24,31,0.98)',
            backdropFilter: 'blur(14px)',
            boxShadow: 'inset 0 0 0 1px var(--line-strong), 0 18px 40px -12px rgba(0,0,0,0.75)',
            animationDuration: '240ms',
          }}
        >
          <div className="label-caps px-2.5 pt-1.5 pb-1">Smart search · click to try</div>
          {SYNTAX.map(([example, meaning]) => (
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
            Without “:” only file names are searched; after “:” the text inside the files. Not case-sensitive. Paste cells from Excel to search a list{listKey ? ` (or ${listKey})` : ''}.
          </div>
        </div>
      )}
    </div>
  );
};
