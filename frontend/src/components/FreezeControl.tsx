import React, { useEffect, useState } from 'react';
import { Snowflake, X } from 'lucide-react';
import { badParts, FileFreeze, Freeze } from '../utils/freeze';

// Frozen rows and columns for the file in Quick Look. Empty fields: the settings apply (shown in
// grey). Anything typed replaces both settings for this file; "0" freezes nothing here.

interface FreezeControlProps {
  global: Freeze;
  own: FileFreeze | null;
  onChange: (value: FileFreeze | null) => void;
}

export const FreezeControl: React.FC<FreezeControlProps> = ({ global, own, onChange }) => {
  const [rows, setRows] = useState(own?.rows ?? '');
  const [cols, setCols] = useState(own?.cols ?? '');
  useEffect(() => {
    setRows(own?.rows ?? '');
    setCols(own?.cols ?? '');
  }, [own]);

  const save = (r = rows, c = cols) => {
    const next = r.trim() || c.trim() ? { rows: r.trim(), cols: c.trim() } : null;
    if (JSON.stringify(next) !== JSON.stringify(own)) onChange(next);
  };
  const field = (
    kind: 'rows' | 'cols',
    value: string,
    set: (v: string) => void,
    width: number,
  ) => {
    const bad = badParts(value, kind);
    const inherited = kind === 'rows' ? global.rowsText : global.colsText;
    return (
      <input
        value={value}
        onChange={e => set(e.target.value)}
        onBlur={() => save()}
        onKeyDown={e => {
          e.stopPropagation();
          if (e.key === 'Enter') {
            e.preventDefault();
            save();
            (e.target as HTMLInputElement).blur();
          } else if (e.key === 'Escape') {
            e.preventDefault();
            setRows(own?.rows ?? '');
            setCols(own?.cols ?? '');
            (e.target as HTMLInputElement).blur();
          }
        }}
        placeholder={own ? 'none' : inherited || 'none'}
        spellCheck={false}
        title={
          bad
            ? `Cannot read: ${bad}`
            : kind === 'rows'
              ? 'Rows that stay at the top, for this file: 1, 1-3 or 1, 4, 6-8 (0: none). Empty: the settings'
              : 'Columns that stay at the left, for this file: A, A-B or 1, 3 (0: none). Empty: the settings'
        }
        className="h-6 px-1.5 rounded-md num text-[12px] text-fg outline-none placeholder:text-fg-3"
        style={{ width, background: 'var(--bg)', boxShadow: `inset 0 0 0 1px ${bad ? 'var(--danger, #f87171)' : 'var(--line-strong)'}` }}
      />
    );
  };

  return (
    <span
      className="flex items-center gap-1.5 h-8 pl-2 pr-1 rounded-lg text-[11px] text-fg-3"
      style={{ boxShadow: `inset 0 0 0 1px ${own ? 'var(--accent-line)' : 'var(--line)'}` }}
      title={own ? 'Frozen rows and columns of this file (the settings do not apply)' : 'Frozen rows and columns (from the settings)'}
    >
      <Snowflake className={`w-3.5 h-3.5 shrink-0 ${own ? 'text-accent' : ''}`} />
      Rows
      {field('rows', rows, setRows, 74)}
      Cols
      {field('cols', cols, setCols, 56)}
      {own ? (
        <button type="button" className="icon-btn !w-6 !h-6" onClick={() => onChange(null)} title="Use the settings again for this file">
          <X className="w-3.5 h-3.5" />
        </button>
      ) : (
        <span className="w-1" />
      )}
    </span>
  );
};
