import React, { useEffect, useRef, useState } from 'react';
import { SlidersHorizontal, X } from 'lucide-react';
import { SegmentedControl } from './motion/SegmentedControl';
import { SearchOptions, SearchPreset } from '../utils/searchOptions';

// Search settings: turn the smart search off, choose where plain words search, change or turn
// off every sign and rule, and how results, pasted lists, and Quick Look behave.
// Saved in data\settings.json ("search").

interface SearchSettingsPanelProps {
  options: SearchOptions;
  defaults: SearchOptions;
  presets: SearchPreset[];
  onSave: (options: SearchOptions) => Promise<string | null>;
  onClose: () => void;
}

export const Switch: React.FC<{ on: boolean; onChange: (v: boolean) => void; label: string; hint?: React.ReactNode; disabled?: boolean }> = ({
  on, onChange, label, hint, disabled,
}) => (
  <button
    type="button"
    role="switch"
    aria-checked={on}
    disabled={disabled}
    onClick={() => onChange(!on)}
    className="flex items-center gap-3 w-full min-h-[38px] px-3 py-1.5 text-left disabled:opacity-40"
  >
    <span className="flex-1 min-w-0">
      <span className="block text-[13px] text-fg-2">{label}</span>
      {hint && <span className="block text-[11.5px] text-fg-3">{hint}</span>}
    </span>
    <span
      className="relative shrink-0 w-8 h-[18px] rounded-full transition-colors duration-200"
      style={{ background: on ? 'var(--accent-strong)' : 'var(--surface-3)', boxShadow: 'inset 0 0 0 1px var(--line-strong)' }}
    >
      <span
        className="absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white transition-transform duration-200"
        style={{ transform: `translateX(${on ? 16 : 2}px)` }}
      />
    </span>
  </button>
);

export const Row: React.FC<{ label: string; hint?: React.ReactNode; children: React.ReactNode; disabled?: boolean }> = ({ label, hint, children, disabled }) => (
  <div className={`flex flex-wrap items-center gap-x-3 gap-y-1.5 min-h-[40px] px-3 py-1.5 ${disabled ? 'opacity-40 pointer-events-none' : ''}`}>
    <span className="flex-1 min-w-[180px]">
      <span className="block text-[13px] text-fg-2">{label}</span>
      {hint && <span className="block text-[11.5px] text-fg-3">{hint}</span>}
    </span>
    {children}
  </div>
);

export const Section: React.FC<{ title: string; children: React.ReactNode; note?: string }> = ({ title, children, note }) => (
  <div className="mt-4">
    <div className="flex items-baseline gap-2 px-1 pb-1.5">
      <span className="label-caps">{title}</span>
      {note && <span className="text-[11px] text-fg-3">{note}</span>}
    </div>
    <div className="rounded-xl overflow-hidden divide-y divide-[var(--line)]" style={{ background: 'var(--surface)', boxShadow: 'inset 0 0 0 1px var(--line)' }}>
      {children}
    </div>
  </div>
);

const CharInput: React.FC<{ value: string; onChange: (v: string) => void; title: string }> = ({ value, onChange, title }) => (
  <input
    value={value}
    maxLength={1}
    onChange={e => onChange(e.target.value.trim().slice(-1))}
    placeholder="off"
    title={`${title}. Empty: off.`}
    spellCheck={false}
    className="w-11 h-7 rounded-md text-center font-mono text-[14px] text-accent outline-none placeholder:text-[10.5px] placeholder:text-fg-3 placeholder:font-sans"
    style={{ background: 'var(--bg)', boxShadow: 'inset 0 0 0 1px var(--line-strong)' }}
  />
);

const NumberInput: React.FC<{ value: number; onChange: (v: number) => void; min: number; max: number; unit?: string }> = ({ value, onChange, min, max, unit }) => (
  <span className="flex items-center gap-1.5">
    <input
      type="number"
      value={value}
      min={min}
      max={max}
      onChange={e => onChange(Number(e.target.value))}
      className="w-20 h-7 px-2 rounded-md num text-[12.5px] text-fg outline-none"
      style={{ background: 'var(--bg)', boxShadow: 'inset 0 0 0 1px var(--line-strong)' }}
    />
    {unit && <span className="text-[11.5px] text-fg-3">{unit}</span>}
  </span>
);

const same = (a: SearchOptions, b: SearchOptions) => JSON.stringify(a) === JSON.stringify(b);

export const SearchSettingsPanel: React.FC<SearchSettingsPanelProps> = ({ options, defaults, presets, onSave, onClose }) => {
  const [d, setD] = useState<SearchOptions>(options);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => boxRef.current?.focus(), []);

  const set = <K extends keyof SearchOptions>(key: K, value: SearchOptions[K]) => {
    setError(null);
    setD(o => ({ ...o, [key]: value }));
  };
  const off = !d.enabled;
  const not = d.not_char || '-';
  const example = [
    d.text_char ? `invoice${d.not_char ? `${d.not_char}old` : ''}${d.and_char ? `${d.and_char}.xlsx` : ''}${d.text_char}total` : '',
    d.group_open ? `${d.group_open}invoice${d.list_char} receipt${d.group_close}` : '',
    d.param_char ? `${d.param_char}size>10mb` : '',
    d.literal_char ? `${d.literal_char}e${not}mail` : '',
  ].filter(Boolean).join('     ');

  const save = async () => {
    setSaving(true);
    const err = await onSave(d);
    setSaving(false);
    if (err) setError(err);
    else onClose();
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
          save();
        }
      }}
    >
      <div className="absolute inset-0 fade-up" style={{ background: 'rgba(5,5,8,0.62)', backdropFilter: 'blur(6px)', animationDuration: '220ms' }} onClick={onClose} />
      <div
        ref={boxRef}
        tabIndex={-1}
        className="relative flex flex-col w-full max-w-[680px] max-h-full rounded-2xl overflow-hidden fade-up outline-none"
        style={{ background: 'var(--bg-elev)', boxShadow: 'inset 0 0 0 1px var(--line-strong), 0 40px 100px -30px rgba(0,0,0,0.9)', animationDuration: '320ms' }}
        role="dialog"
        aria-label="Search settings"
      >
        <div className="flex items-center gap-3 h-[58px] pl-4 pr-3 shrink-0" style={{ borderBottom: '1px solid var(--line)' }}>
          <span className="flex items-center justify-center w-8 h-8 rounded-lg text-accent bg-accent-soft">
            <SlidersHorizontal className="w-4 h-4" />
          </span>
          <div className="flex flex-col min-w-0 flex-1">
            <span className="text-[14px] font-semibold text-fg">Search settings</span>
            <span className="text-[11.5px] text-fg-3">How the search field is read. Saved in data\settings.json.</span>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} title="Close (Esc)">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3">
          <div className="label-caps px-1 pb-1.5">Start from</div>
          <div className="flex flex-wrap gap-1.5">
            {presets.map(p => {
              const active = same(p.options, d);
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => { setError(null); setD(p.options); }}
                  className={`h-8 px-3 rounded-lg text-[12.5px] transition-colors ${active ? 'text-fg bg-accent-soft' : 'text-fg-2 hover:text-fg bg-surface-2'}`}
                  style={{ boxShadow: `inset 0 0 0 1px ${active ? 'var(--accent-line)' : 'var(--line)'}` }}
                >
                  {p.label}
                </button>
              );
            })}
          </div>

          <Section title="Smart search">
            <Switch
              on={d.enabled}
              onChange={v => set('enabled', v)}
              label="Smart search"
              hint="Off: the search field is plain text. No sign has a meaning, nothing is a filter."
            />
            <Row label="Words search in" hint={d.enabled ? `Without the text sign${d.text_char ? ` (${d.text_char})` : ''}. Also used when smart search is off.` : 'What the plain text searches.'}>
              <SegmentedControl
                options={[
                  { id: 'names' as const, label: 'File names' },
                  { id: 'text' as const, label: 'Text' },
                  { id: 'both' as const, label: 'Names and text' },
                ]}
                value={d.default_scope}
                onChange={v => set('default_scope', v)}
                size="sm"
              />
            </Row>
          </Section>

          <Section title="Signs" note={off ? 'smart search is off' : 'empty: off'}>
            <Row label="Text inside files" hint="names:text" disabled={off}>
              <CharInput value={d.text_char} onChange={v => set('text_char', v)} title="Text sign" />
            </Row>
            <Row label="Every part must hit" hint="a+b" disabled={off}>
              <CharInput value={d.and_char} onChange={v => set('and_char', v)} title="And sign" />
            </Row>
            <Row label="Leave out" hint={d.dash_mode === 'anywhere' ? 'invoice-old (2024-05 stays text)' : 'invoice -old (only after a space)'} disabled={off}>
              <SegmentedControl
                options={[{ id: 'anywhere' as const, label: 'Anywhere' }, { id: 'word_start' as const, label: 'Word start' }]}
                value={d.dash_mode}
                onChange={v => set('dash_mode', v)}
                size="sm"
              />
              <CharInput value={d.not_char} onChange={v => set('not_char', v)} title="Not sign" />
            </Row>
            <Row label="The rest is literal" hint="/e-mail" disabled={off}>
              <CharInput value={d.literal_char} onChange={v => set('literal_char', v)} title="Literal sign" />
            </Row>
            <Row
              label="Filters: dates and size"
              hint={`invoice${d.param_char || ';'}dm from 01-03-2024${d.param_char || ';'}size>10mb`}
              disabled={off}
            >
              <SegmentedControl
                options={[
                  { id: 'dmy' as const, label: 'Day-month', hint: '01-03-2024 is 1 March 2024' },
                  { id: 'mdy' as const, label: 'Month-day', hint: '03-01-2024 is 1 March 2024' },
                  { id: 'ymd' as const, label: 'Year first', hint: '2024-03-01 is 1 March 2024' },
                ]}
                value={d.date_order}
                onChange={v => set('date_order', v)}
                size="sm"
              />
              <CharInput value={d.param_char} onChange={v => set('param_char', v)} title="Filter sign" />
            </Row>
            <Row label="Groups: one row per element" hint="[a, b]" disabled={off}>
              <CharInput value={d.group_open} onChange={v => set('group_open', v)} title="Group start" />
              <CharInput value={d.list_char} onChange={v => set('list_char', v)} title="Separator" />
              <CharInput value={d.group_close} onChange={v => set('group_close', v)} title="Group end" />
            </Row>
            {!off && example && (
              <div className="px-3 py-2 text-[11.5px] text-fg-3">
                Example: <span className="font-mono text-accent whitespace-pre">{example}</span>
              </div>
            )}
          </Section>

          <Section title="Rules">
            <Switch disabled={off} on={d.extensions} onChange={v => set('extensions', v)} label="“.xlsx” is a file type filter" hint="Off: it is part of the name" />
            <Switch disabled={off} on={d.exact_names} onChange={v => set('exact_names', v)} label="“invoice.xlsx” is the whole file name" hint="Off: names that contain invoice.xlsx" />
            <Switch disabled={off} on={d.wildcards} onChange={v => set('wildcards', v)} label="Wildcards * and ?" hint="tot*l, rec?ipt" />
            <Switch disabled={off} on={d.quotes} onChange={v => set('quotes', v)} label="Quotes make text literal" hint={'"e-mail"'} />
            <Switch disabled={off || !d.list_char} on={d.comma_joins} onChange={v => set('comma_joins', v)} label={`Outside a group, “${d.list_char || ','}” joins parts like “${d.and_char || '+'}”`} hint={`-notes${d.text_char || ':'}-draft${d.list_char || ','} memo`} />
            <Switch on={d.names_include_folders} onChange={v => set('names_include_folders', v)} label="Names also match folder names" hint="Folders below your working folders, not the working folder itself" />
            <Switch on={d.text_prefix} onChange={v => set('text_prefix', v)} label="Text words match word beginnings" hint="“memo” also finds “memos”. Off: whole words only" />
          </Section>

          <Section title="Results">
            <Row label="Order">
              <SegmentedControl
                options={[
                  { id: 'best' as const, label: 'Best match' },
                  { id: 'newest' as const, label: 'Newest' },
                  { id: 'oldest' as const, label: 'Oldest' },
                  { id: 'name' as const, label: 'Name' },
                  { id: 'size' as const, label: 'Size' },
                ]}
                value={d.sort}
                onChange={v => set('sort', v)}
                size="sm"
              />
            </Row>
            <Row label="Groups ([a, b])">
              <SegmentedControl
                options={[
                  { id: 'auto' as const, label: 'A single one opens', hint: 'One group opens by itself, several start closed' },
                  { id: 'all' as const, label: 'All open' },
                  { id: 'none' as const, label: 'All closed' },
                ]}
                value={d.groups_open}
                onChange={v => set('groups_open', v)}
                size="sm"
              />
            </Row>
            <Row label="Rows per page" hint="More load while you scroll">
              <NumberInput value={d.page_size} onChange={v => set('page_size', v)} min={20} max={500} />
            </Row>
            <Row label="Wait after typing" hint="Before the search starts">
              <NumberInput value={d.search_delay_ms} onChange={v => set('search_delay_ms', v)} min={0} max={2000} unit="ms" />
            </Row>
            <Switch on={d.show_snippets} onChange={v => set('show_snippets', v)} label="Show text snippets under the results" />
            <Switch on={d.show_chips} onChange={v => set('show_chips', v)} label="Show how the search was read" hint="The chips under the search field" />
          </Section>

          <Section title="Pasting cells from Excel" note={off ? 'smart search is off: pasted as text' : undefined}>
            <Row label="When you paste several cells" disabled={off}>
              <SegmentedControl
                options={[
                  { id: 'table' as const, label: 'Open the table' },
                  { id: 'groups' as const, label: 'Search at once' },
                  { id: 'text' as const, label: 'Paste as text' },
                ]}
                value={d.paste_list}
                onChange={v => set('paste_list', v)}
                size="sm"
              />
            </Row>
            <Row label="Values search in" disabled={off}>
              <SegmentedControl
                options={[{ id: 'names' as const, label: 'File names' }, { id: 'text' as const, label: 'Text' }]}
                value={d.list_where}
                onChange={v => set('list_where', v)}
                size="sm"
              />
            </Row>
            <Row label="Values are" disabled={off}>
              <SegmentedControl
                options={[{ id: 'groups' as const, label: 'Expandable rows' }, { id: 'together' as const, label: 'Together (all must hit)' }]}
                value={d.list_mode}
                onChange={v => set('list_mode', v)}
                size="sm"
              />
            </Row>
          </Section>

          <Section title="Quick Look">
            <Switch on={d.preview_highlight} onChange={v => set('preview_highlight', v)} label="Mark the search hits in the preview" />
            <Switch on={d.preview_jump} onChange={v => set('preview_jump', v)} label="Scroll to the first hit" />
            <Switch on={d.type_to_find} onChange={v => set('type_to_find', v)} label="Typing starts Find in the preview" hint="Off: only with the Find key" />
          </Section>
        </div>

        {error && (
          <div className="px-4 py-2 shrink-0 text-[12px] text-danger" style={{ borderTop: '1px solid var(--line)' }}>{error}</div>
        )}
        <div className="flex items-center gap-2 px-4 py-3 shrink-0" style={{ borderTop: '1px solid var(--line)' }}>
          <button
            type="button"
            className="mr-auto text-[12px] text-fg-3 hover:text-fg transition-colors disabled:opacity-40"
            disabled={same(d, defaults)}
            onClick={() => { setError(null); setD(defaults); }}
          >
            Reset to defaults
          </button>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn-primary" disabled={same(d, options) || saving} onClick={save}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
};
