import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Keyboard, Plus, RotateCcw, X } from 'lucide-react';
import {
  ACTIONS,
  ActionId,
  bindingParts,
  bindingToGlobal,
  conflictsFor,
  DEFAULT_KEYMAP,
  eventToBinding,
  globalToParts,
  Keymap,
} from '../utils/keymap';

// Keyboard shortcuts: every key of the app, and the global key that shows the window.
// Saved in data\settings.json ("hotkey" and "shortcuts").

interface ShortcutsPanelProps {
  keymap: Keymap;
  hotkey: string;
  defaultHotkey: string;
  canSetHotkey: boolean;
  onSave: (keymap: Keymap, hotkey: string) => Promise<boolean>;
  onClose: () => void;
}

type Capture = { target: ActionId | 'global' } | null;

const Keys: React.FC<{ parts: string[] }> = ({ parts }) => (
  <span className="inline-flex items-center gap-1">
    {parts.map((p, i) => <span key={i} className="kbd">{p}</span>)}
  </span>
);

export const ShortcutsPanel: React.FC<ShortcutsPanelProps> = ({ keymap, hotkey, defaultHotkey, canSetHotkey, onSave, onClose }) => {
  const [draft, setDraft] = useState<Keymap>(keymap);
  const [globalKey, setGlobalKey] = useState(hotkey);
  const [capture, setCapture] = useState<Capture>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => boxRef.current?.focus(), []);

  // While a key is being recorded, every key press goes here (also Tab, Space, Enter)
  useEffect(() => {
    if (!capture) return;
    const onKey = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (e.key === 'Escape' && !e.ctrlKey && !e.altKey && !e.shiftKey) {
        setCapture(null);
        return;
      }
      const binding = eventToBinding(e);
      if (!binding) return; // a modifier alone: wait for the key
      if (capture.target === 'global') {
        const name = bindingToGlobal(binding);
        if (!name) {
          setError('The global key needs Ctrl, Alt, Shift, or Win plus a letter, a digit, Space, or an F key.');
          return;
        }
        setGlobalKey(name);
      } else {
        const id = capture.target;
        setDraft(d => ({ ...d, [id]: d[id].includes(binding) ? d[id] : [...d[id], binding].slice(-4) }));
      }
      setError(null);
      setCapture(null);
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [capture]);

  const sections = useMemo(() => {
    const out: { name: string; actions: typeof ACTIONS }[] = [];
    for (const a of ACTIONS) {
      let s = out.find(x => x.name === a.section);
      if (!s) out.push((s = { name: a.section, actions: [] }));
      s.actions.push(a);
    }
    return out;
  }, []);

  const changed = JSON.stringify(draft) !== JSON.stringify(keymap) || globalKey !== hotkey;

  const save = async () => {
    setSaving(true);
    const ok = await onSave(draft, globalKey);
    setSaving(false);
    if (ok) onClose();
  };

  return (
    <div
      className="fixed inset-0 z-[75] flex items-center justify-center p-6"
      onKeyDown={e => {
        e.stopPropagation();
        if (e.key === 'Escape' && !capture) {
          e.preventDefault();
          onClose();
        }
      }}
    >
      <div className="absolute inset-0 fade-up" style={{ background: 'rgba(5,5,8,0.62)', backdropFilter: 'blur(6px)', animationDuration: '220ms' }} onClick={onClose} />
      <div
        className="relative flex flex-col w-full max-w-[640px] max-h-full rounded-2xl overflow-hidden fade-up"
        style={{ background: 'var(--bg-elev)', boxShadow: 'inset 0 0 0 1px var(--line-strong), 0 40px 100px -30px rgba(0,0,0,0.9)', animationDuration: '320ms' }}
        role="dialog"
        aria-label="Keyboard shortcuts"
        tabIndex={-1}
        ref={boxRef}
      >
        <div className="flex items-center gap-3 h-[58px] pl-4 pr-3 shrink-0" style={{ borderBottom: '1px solid var(--line)' }}>
          <span className="flex items-center justify-center w-8 h-8 rounded-lg text-accent bg-accent-soft">
            <Keyboard className="w-4 h-4" />
          </span>
          <div className="flex flex-col min-w-0 flex-1">
            <span className="text-[14px] font-semibold text-fg">Keyboard shortcuts</span>
            <span className="text-[11.5px] text-fg-3">Click + and press the keys. Saved in data\settings.json.</span>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} title="Close (Esc)">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3">
          <div className="label-caps px-1 pb-1.5">Everywhere in Windows</div>
          <div className="flex items-center gap-3 min-h-[40px] px-3 py-1.5 rounded-xl" style={{ background: 'var(--surface)', boxShadow: 'inset 0 0 0 1px var(--line)' }}>
            <span className="flex-1 text-[13px] text-fg">Show or hide Peek &amp; Grep</span>
            {capture?.target === 'global' ? (
              <span className="text-[12px] text-accent">Press the keys… (Esc: cancel)</span>
            ) : (
              <button
                type="button"
                className="flex items-center gap-1.5 h-7 px-2 rounded-md hover:bg-surface-2 disabled:opacity-50"
                onClick={() => setCapture({ target: 'global' })}
                disabled={!canSetHotkey}
                title={canSetHotkey ? 'Change the key' : 'Change it in the desktop app'}
              >
                <Keys parts={globalToParts(globalKey)} />
              </button>
            )}
            <button
              type="button"
              className="icon-btn"
              style={{ visibility: globalKey !== defaultHotkey ? 'visible' : 'hidden' }}
              onClick={() => setGlobalKey(defaultHotkey)}
              title={`Back to ${globalToParts(defaultHotkey).join('+')}`}
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>
          </div>

          {sections.map(section => (
            <div key={section.name} className="mt-4">
              <div className="label-caps px-1 pb-1.5">{section.name}</div>
              <div className="rounded-xl overflow-hidden" style={{ background: 'var(--surface)', boxShadow: 'inset 0 0 0 1px var(--line)' }}>
                {section.actions.map((a, i) => {
                  const bindings = draft[a.id];
                  const isDefault = bindings.join('|') === DEFAULT_KEYMAP[a.id].join('|');
                  const clashes = bindings.flatMap(b => conflictsFor(draft, a.id, b).map(c => ({ b, c })));
                  const recording = capture?.target === a.id;
                  return (
                    <div key={a.id} className="px-3 py-1.5" style={{ borderTop: i ? '1px solid var(--line)' : undefined }}>
                      <div className="flex items-center gap-3 min-h-[30px]">
                        <span className="flex-1 text-[13px] text-fg-2">{a.label}</span>
                        <div className="flex flex-wrap items-center justify-end gap-1.5">
                          {bindings.map(b => (
                            <span key={b} className="group/key relative inline-flex items-center">
                              <Keys parts={bindingParts(b)} />
                              <button
                                type="button"
                                className="ml-0.5 w-4 h-4 inline-flex items-center justify-center rounded text-fg-3 opacity-0 group-hover/key:opacity-100 hover:text-danger"
                                onClick={() => setDraft(d => ({ ...d, [a.id]: d[a.id].filter(x => x !== b) }))}
                                title="Remove this key"
                              >
                                <X className="w-3 h-3" />
                              </button>
                            </span>
                          ))}
                          {!bindings.length && !recording && <span className="text-[12px] text-fg-3">No key</span>}
                          {recording ? (
                            <span className="text-[12px] text-accent">Press the keys…</span>
                          ) : (
                            <button type="button" className="icon-btn !w-6 !h-6" onClick={() => setCapture({ target: a.id })} title="Add a key">
                              <Plus className="w-3.5 h-3.5" />
                            </button>
                          )}
                          <button
                            type="button"
                            className="icon-btn !w-6 !h-6"
                            style={{ visibility: isDefault ? 'hidden' : 'visible' }}
                            onClick={() => setDraft(d => ({ ...d, [a.id]: DEFAULT_KEYMAP[a.id] }))}
                            title="Back to the default"
                          >
                            <RotateCcw className="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                      {clashes.length > 0 && (
                        <div className="flex items-center gap-1.5 pb-1 text-[11.5px] text-warn">
                          <AlertTriangle className="w-3.5 h-3.5" />
                          {clashes.map(({ b, c }) => `${bindingParts(b).join('+')} is also “${c.label}”`).join(' · ')}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        <div className="flex items-center gap-2 px-4 py-3 shrink-0" style={{ borderTop: '1px solid var(--line)' }}>
          {error ? (
            <span className="mr-auto text-[12px] text-danger">{error}</span>
          ) : (
            <button
              type="button"
              className="mr-auto text-[12px] text-fg-3 hover:text-fg transition-colors"
              onClick={() => {
                setDraft(DEFAULT_KEYMAP);
                setGlobalKey(defaultHotkey);
              }}
            >
              Reset all keys
            </button>
          )}
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn-primary" disabled={!changed || saving} onClick={save}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
};
