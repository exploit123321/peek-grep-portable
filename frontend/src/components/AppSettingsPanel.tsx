import React, { useEffect, useRef, useState } from 'react';
import { FolderOpen, Keyboard, Plus, Settings, SlidersHorizontal, Trash2, X } from 'lucide-react';
import { api, AppOptions, AppSettings, BackupOptions, BackupsInfo, BigFileRule } from '../api';
import { SegmentedControl } from './motion/SegmentedControl';
import { NumberInput, Row, Section, Switch } from './SearchSettingsPanel';

// App settings: start with Windows, how the window opens, frozen table rows, backups when the editor saves, and
// links to the other settings. Each change is saved at once (data\settings.json; the startup
// entry is in the Windows registry).

const BACKUP_GAPS = [
  { id: '0', label: 'Every save' },
  { id: '10', label: '10 min' },
  { id: '60', label: '1 hour' },
  { id: '1440', label: '1 day' },
] as const;

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** Row numbers for frozen rows; saved on Enter or when the field loses focus. */
const FreezeInput: React.FC<{ value: string; onSave: (v: string) => void }> = ({ value, onSave }) => {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const save = () => {
    if (draft.trim() !== value) onSave(draft.trim());
  };
  return (
    <input
      value={draft}
      onChange={e => setDraft(e.target.value)}
      onBlur={save}
      onKeyDown={e => {
        if (e.key === 'Enter') { e.preventDefault(); save(); }
      }}
      placeholder="none"
      spellCheck={false}
      className="w-32 h-7 px-2 rounded-md num text-[12.5px] text-fg outline-none placeholder:text-fg-3"
      style={{ background: 'var(--bg)', boxShadow: 'inset 0 0 0 1px var(--line-strong)' }}
    />
  );
};

const RULE_KINDS = [
  { id: 'type' as const, label: 'File type', placeholder: '.xlsx' },
  { id: 'name' as const, label: 'Name has', placeholder: 'big' },
  { id: 'file' as const, label: 'File', placeholder: 'D:\\Data\\export.csv' },
];

/** One Large files rule (saved on Enter or when the field loses focus); the last row adds a new one. */
const BigFileRow: React.FC<{ rule: BigFileRule; isNew?: boolean; onSave: (r: BigFileRule) => void; onRemove?: () => void }> = ({
  rule, isNew, onSave, onRemove,
}) => {
  const [kind, setKind] = useState(rule.kind);
  const [value, setValue] = useState(rule.value);
  const save = (k = kind) => {
    const v = value.trim();
    if (v && (v !== rule.value || k !== rule.kind)) onSave({ kind: k, value: v });
  };
  return (
    <div className="flex items-center gap-2 min-h-[40px] px-3 py-1.5">
      <SegmentedControl
        options={RULE_KINDS.map(({ id, label }) => ({ id, label }))}
        value={kind}
        onChange={k => {
          setKind(k);
          if (!isNew) save(k);
        }}
        size="sm"
      />
      <input
        value={value}
        onChange={e => setValue(e.target.value)}
        // The add row saves on Enter or +, so the kind can still be picked after typing
        onBlur={() => !isNew && save()}
        onKeyDown={e => {
          if (e.key === 'Enter') { e.preventDefault(); save(); }
        }}
        placeholder={isNew ? `Add: ${RULE_KINDS.find(k => k.id === kind)!.placeholder}` : ''}
        spellCheck={false}
        className="flex-1 min-w-0 h-7 px-2 rounded-md num text-[12.5px] text-fg outline-none placeholder:text-fg-3"
        style={{ background: 'var(--bg)', boxShadow: 'inset 0 0 0 1px var(--line-strong)' }}
      />
      {isNew ? (
        <button type="button" className="icon-btn" title="Add" disabled={!value.trim()} onClick={() => save()}>
          <Plus className="w-4 h-4" />
        </button>
      ) : (
        <button type="button" className="icon-btn" title="Remove" onClick={onRemove}>
          <Trash2 className="w-4 h-4" />
        </button>
      )}
    </div>
  );
};

interface AppSettingsPanelProps {
  settings: AppSettings;
  onChange: (values: Partial<AppOptions>) => Promise<string | null>;
  onBackupsChange: (values: Partial<BackupOptions>) => Promise<string | null>;
  onBigFilesChange: (rules: BigFileRule[]) => Promise<string | null>;
  onOpenSearchSettings: () => void;
  onOpenShortcuts: () => void;
  onClose: () => void;
}

export const AppSettingsPanel: React.FC<AppSettingsPanelProps> = ({ settings, onChange, onBackupsChange, onBigFilesChange, onOpenSearchSettings, onOpenShortcuts, onClose }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => boxRef.current?.focus(), []);
  const o = settings.app;
  const b = settings.backups;
  const [info, setInfo] = useState<BackupsInfo | null>(null);
  useEffect(() => {
    api.backups().then(setInfo).catch(() => setInfo(null));
  }, []);

  const change = async (values: Partial<AppOptions>) => {
    setBusy(true);
    setError(await onChange(values));
    setBusy(false);
  };

  const changeBackups = async (values: Partial<BackupOptions>) => {
    setBusy(true);
    setError(await onBackupsChange(values));
    setBusy(false);
  };

  const changeBigFiles = async (rules: BigFileRule[]) => {
    setBusy(true);
    setError(await onBigFilesChange(rules));
    setBusy(false);
    // The edited row is drawn again: keep the focus in the panel, so Esc still closes it
    requestAnimationFrame(() => {
      if (!boxRef.current?.contains(document.activeElement)) boxRef.current?.focus();
    });
  };

  const backupAction = async (action: () => Promise<BackupsInfo>) => {
    try {
      setInfo(await action());
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[75] flex items-center justify-center p-6"
      onKeyDown={e => {
        e.stopPropagation();
        if (e.key === 'Escape') {
          e.preventDefault();
          onClose();
        }
      }}
    >
      <div className="absolute inset-0 fade-up" style={{ background: 'rgba(5,5,8,0.62)', backdropFilter: 'blur(6px)', animationDuration: '220ms' }} onClick={onClose} />
      <div
        ref={boxRef}
        tabIndex={-1}
        className="relative flex flex-col w-full max-w-[560px] max-h-full rounded-2xl overflow-hidden fade-up outline-none"
        style={{ background: 'var(--bg-elev)', boxShadow: 'inset 0 0 0 1px var(--line-strong), 0 40px 100px -30px rgba(0,0,0,0.9)', animationDuration: '320ms' }}
        role="dialog"
        aria-label="Settings"
      >
        <div className="flex items-center gap-3 h-[58px] pl-4 pr-3 shrink-0" style={{ borderBottom: '1px solid var(--line)' }}>
          <span className="flex items-center justify-center w-8 h-8 rounded-lg text-accent bg-accent-soft">
            <Settings className="w-4 h-4" />
          </span>
          <div className="flex flex-col min-w-0 flex-1">
            <span className="text-[14px] font-semibold text-fg">Settings</span>
            <span className="text-[11.5px] text-fg-3">Saved at once in data\settings.json.</span>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} title="Close (Esc)">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className={`flex-1 min-h-0 overflow-y-auto px-4 pb-4 ${busy ? 'opacity-70 pointer-events-none' : ''}`}>
          <Section title="Windows start">
            <Switch
              on={o.start_with_windows}
              onChange={v => change({ start_with_windows: v })}
              disabled={!settings.autostart_available}
              label="Start with Windows"
              hint={settings.autostart_available
                ? 'Starts when you sign in. One entry for your user in the registry (Run); turning it off removes it.'
                : 'Only in the desktop app.'}
            />
            <Row label="When Windows starts it" disabled={!o.start_with_windows}>
              <SegmentedControl
                options={[
                  { id: 'tray' as const, label: 'Stay in the tray', hint: 'Ready for the show/hide key' },
                  { id: 'window' as const, label: 'Open the window' },
                ]}
                value={o.start_hidden ? 'tray' : 'window'}
                onChange={v => change({ start_hidden: v === 'tray' })}
                size="sm"
              />
            </Row>
          </Section>

          <Section title="Window">
            <Switch
              on={o.open_on_mouse_monitor}
              onChange={v => change({ open_on_mouse_monitor: v })}
              label="Open on the screen with the mouse pointer"
              hint="Off: where it was last (a screen that is off or unplugged is never used)"
            />
            <Switch
              on={o.release_window_on_hide}
              onChange={v => change({ release_window_on_hide: v })}
              label="Free memory in the tray"
              hint="About 110 MB instead of 300 MB while hidden; the window opens again at once"
            />
          </Section>

          <Section title="Tables">
            <Row
              label="Freeze rows"
              hint={<>These rows stay at the top in Excel and CSV views, under the column names. For example <span className="font-mono">1</span>, <span className="font-mono">1-3</span> or <span className="font-mono">1, 4, 6-8</span>. Empty: none.</>}
            >
              <FreezeInput value={o.freeze_rows} onSave={v => change({ freeze_rows: v })} />
            </Row>
            <Row
              label="Freeze columns"
              hint={<>These columns stay at the left, next to the row numbers. Letters or numbers: <span className="font-mono">A</span>, <span className="font-mono">A-B</span> or <span className="font-mono">1, 3</span>. A file can have its own in Quick Look.</>}
            >
              <FreezeInput value={o.freeze_columns} onSave={v => change({ freeze_columns: v })} />
            </Row>
          </Section>

          <Section title="Large files" note="text search reads up to 200 MB">
            <div className="px-3 py-2 text-[11.5px] text-fg-3">
              Other files: up to 10 MB (Office files 100 MB). A rule for a file type, a part of the name
              (<span className="font-mono">big</span> also matches bigdata.xlsx) or one file (its full path).
            </div>
            {settings.big_files.map((rule, i) => (
              <BigFileRow
                key={`${i}-${rule.kind}-${rule.value}`}
                rule={rule}
                onSave={r => changeBigFiles(settings.big_files.map((x, k) => (k === i ? r : x)))}
                onRemove={() => changeBigFiles(settings.big_files.filter((_, k) => k !== i))}
              />
            ))}
            <BigFileRow key={`new-${settings.big_files.length}`} rule={{ kind: 'name', value: '' }} isNew onSave={r => changeBigFiles([...settings.big_files, r])} />
          </Section>

          <Section title="Backups when you save an edit">
            <Switch
              on={b.enabled}
              onChange={v => changeBackups({ enabled: v })}
              label="Back up a file before saving it"
              hint="The version from before your edits goes to data\backups"
            />
            <Row
              label="New backup"
              hint="More saves within this time make none (a file changed by another program is always backed up)"
              disabled={!b.enabled}
            >
              <SegmentedControl
                options={[...BACKUP_GAPS]}
                value={String(b.gap_minutes) as (typeof BACKUP_GAPS)[number]['id']}
                onChange={v => changeBackups({ gap_minutes: Number(v) })}
                size="sm"
              />
            </Row>
            <Row label="Keep per file" hint="The oldest go" disabled={!b.enabled}>
              <NumberInput
                value={b.per_file}
                onChange={v => Number.isInteger(v) && v >= 1 && v <= 50 && changeBackups({ per_file: v })}
                min={1}
                max={50}
              />
            </Row>
            <Row label={info ? `${info.count} ${info.count === 1 ? 'backup' : 'backups'}${info.count ? `, ${formatBytes(info.bytes)}` : ''}` : 'Backups'}>
              <button type="button" className="btn !h-7" onClick={() => backupAction(api.openBackups)} title={info?.folder}>
                <FolderOpen className="w-3.5 h-3.5" /> Open folder
              </button>
              <button
                type="button"
                className="btn !h-7"
                disabled={!info?.count}
                onClick={() => {
                  if (window.confirm(`Delete all ${info?.count} backups? Your files stay as they are.`)) backupAction(api.deleteBackups);
                }}
              >
                <Trash2 className="w-3.5 h-3.5" /> Delete all
              </button>
            </Row>
          </Section>

          <Section title="More">
            <button type="button" className="flex items-center gap-3 w-full min-h-[40px] px-3 text-left text-[13px] text-fg-2 hover:text-fg hover:bg-surface-2 transition-colors" onClick={onOpenSearchSettings}>
              <SlidersHorizontal className="w-4 h-4 text-fg-3" /> Search settings…
            </button>
            <button type="button" className="flex items-center gap-3 w-full min-h-[40px] px-3 text-left text-[13px] text-fg-2 hover:text-fg hover:bg-surface-2 transition-colors" onClick={onOpenShortcuts}>
              <Keyboard className="w-4 h-4 text-fg-3" /> Keyboard shortcuts…
            </button>
          </Section>
          {error && <div className="mt-3 px-1 text-[12px] text-danger">{error}</div>}
        </div>
      </div>
    </div>
  );
};
