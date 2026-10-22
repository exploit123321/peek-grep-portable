import React, { useEffect, useRef, useState } from 'react';
import { FolderOpen, Keyboard, Settings, SlidersHorizontal, Trash2, X } from 'lucide-react';
import { api, AppOptions, AppSettings, BackupOptions, BackupsInfo } from '../api';
import { SegmentedControl } from './motion/SegmentedControl';
import { NumberInput, Row, Section, Switch } from './SearchSettingsPanel';

// App settings: start with Windows, how the window opens, backups when the editor saves, and
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

interface AppSettingsPanelProps {
  settings: AppSettings;
  onChange: (values: Partial<AppOptions>) => Promise<string | null>;
  onBackupsChange: (values: Partial<BackupOptions>) => Promise<string | null>;
  onOpenSearchSettings: () => void;
  onOpenShortcuts: () => void;
  onClose: () => void;
}

export const AppSettingsPanel: React.FC<AppSettingsPanelProps> = ({ settings, onChange, onBackupsChange, onOpenSearchSettings, onOpenShortcuts, onClose }) => {
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
