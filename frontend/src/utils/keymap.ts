// Configurable keyboard shortcuts. Defaults live here; data\settings.json keeps only the
// actions the user changed ("shortcuts": {action: ["Ctrl+K", ...]}).

import type { KeyboardEvent as ReactKeyboardEvent } from 'react';

export type ActionId =
  | 'focus_search' | 'clear' | 'list_editor' | 'shortcuts' | 'folders' | 'toggle_smart' | 'search_settings'
  | 'category_1' | 'category_2' | 'category_3' | 'category_4' | 'category_5'
  | 'move_down' | 'move_up' | 'preview' | 'open' | 'reveal' | 'copy_path'
  | 'expand' | 'collapse' | 'expand_all'
  | 'find_in_preview' | 'next_hit' | 'prev_hit' | 'close_preview' | 'edit_file' | 'save_edit'
  | 'zoom_in' | 'zoom_out' | 'zoom_reset' | 'wrap_lines';

/** Where a key works: the result list, Quick Look, or both. */
export type KeyContext = 'results' | 'preview' | 'both';

export interface ActionDef {
  id: ActionId;
  label: string;
  section: string;
  context: KeyContext;
  defaults: string[];
}

export const ACTIONS: ActionDef[] = [
  { id: 'focus_search', label: 'Go to the search field', section: 'Search', context: 'results', defaults: ['Ctrl+K', 'Ctrl+F'] },
  { id: 'clear', label: 'Clear the search, leave the folder, hide', section: 'Search', context: 'results', defaults: ['Escape'] },
  { id: 'list_editor', label: 'Search a list (paste from Excel)', section: 'Search', context: 'results', defaults: ['Ctrl+L'] },
  { id: 'toggle_smart', label: 'Smart search on or off', section: 'Search', context: 'results', defaults: ['Alt+S'] },
  { id: 'category_1', label: 'Type: All', section: 'Search', context: 'results', defaults: ['Ctrl+1'] },
  { id: 'category_2', label: 'Type: Code', section: 'Search', context: 'results', defaults: ['Ctrl+2'] },
  { id: 'category_3', label: 'Type: Docs', section: 'Search', context: 'results', defaults: ['Ctrl+3'] },
  { id: 'category_4', label: 'Type: Data', section: 'Search', context: 'results', defaults: ['Ctrl+4'] },
  { id: 'category_5', label: 'Type: Media', section: 'Search', context: 'results', defaults: ['Ctrl+5'] },

  { id: 'move_down', label: 'Next result', section: 'Results', context: 'both', defaults: ['ArrowDown'] },
  { id: 'move_up', label: 'Previous result', section: 'Results', context: 'both', defaults: ['ArrowUp'] },
  { id: 'preview', label: 'Quick Look', section: 'Results', context: 'both', defaults: ['Space'] },
  { id: 'open', label: 'Open the file (or a group)', section: 'Results', context: 'both', defaults: ['Enter'] },
  { id: 'reveal', label: 'Show in Explorer', section: 'Results', context: 'both', defaults: ['Ctrl+Enter'] },
  { id: 'copy_path', label: 'Copy path', section: 'Results', context: 'both', defaults: ['Ctrl+C'] },
  { id: 'expand', label: 'Open a group', section: 'Results', context: 'results', defaults: ['ArrowRight'] },
  { id: 'collapse', label: 'Close a group', section: 'Results', context: 'results', defaults: ['ArrowLeft'] },
  { id: 'expand_all', label: 'Open or close all groups', section: 'Results', context: 'results', defaults: ['Ctrl+E'] },

  { id: 'find_in_preview', label: 'Find in the preview', section: 'Quick Look', context: 'preview', defaults: ['Ctrl+F'] },
  { id: 'next_hit', label: 'Next hit', section: 'Quick Look', context: 'preview', defaults: ['F3'] },
  { id: 'prev_hit', label: 'Previous hit', section: 'Quick Look', context: 'preview', defaults: ['Shift+F3'] },
  { id: 'close_preview', label: 'Close Quick Look', section: 'Quick Look', context: 'preview', defaults: ['Escape'] },
  { id: 'edit_file', label: 'Edit the file', section: 'Quick Look', context: 'preview', defaults: ['Ctrl+E'] },
  { id: 'save_edit', label: 'Save the edit', section: 'Quick Look', context: 'preview', defaults: ['Ctrl+S'] },
  { id: 'zoom_in', label: 'Zoom in (also Ctrl + mouse wheel)', section: 'Quick Look', context: 'preview', defaults: ['Ctrl+=', 'Ctrl++', 'Ctrl+Shift++'] },
  { id: 'zoom_out', label: 'Zoom out', section: 'Quick Look', context: 'preview', defaults: ['Ctrl+-'] },
  { id: 'zoom_reset', label: 'Zoom to 100%', section: 'Quick Look', context: 'preview', defaults: ['Ctrl+0'] },
  { id: 'wrap_lines', label: 'Wrap long lines on or off (text and code)', section: 'Quick Look', context: 'preview', defaults: ['Alt+Z'] },

  { id: 'shortcuts', label: 'Keyboard shortcuts', section: 'Window', context: 'results', defaults: ['Ctrl+,'] },
  { id: 'search_settings', label: 'Search settings', section: 'Window', context: 'results', defaults: ['Ctrl+.'] },
  { id: 'folders', label: 'Working folders', section: 'Window', context: 'results', defaults: [] },
];

export type Keymap = Record<ActionId, string[]>;

export const DEFAULT_KEYMAP: Keymap = Object.fromEntries(ACTIONS.map(a => [a.id, a.defaults])) as Keymap;

export function buildKeymap(overrides: Record<string, string[]> | null | undefined): Keymap {
  const map = { ...DEFAULT_KEYMAP };
  for (const a of ACTIONS) {
    const o = overrides?.[a.id];
    if (Array.isArray(o)) map[a.id] = o;
  }
  return map;
}

/** Only the actions that differ from the defaults (what settings.json keeps). */
export function keymapOverrides(map: Keymap): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const a of ACTIONS) {
    if (map[a.id].join('|') !== a.defaults.join('|')) out[a.id] = map[a.id];
  }
  return out;
}

const MODIFIER_KEYS = new Set(['Control', 'Shift', 'Alt', 'Meta', 'AltGraph', 'CapsLock', 'OS']);

/** "Ctrl+Shift+K" for a key press (letters and digits by position, so other layouts work). */
export function eventToBinding(e: KeyboardEvent | ReactKeyboardEvent): string | null {
  if (MODIFIER_KEYS.has(e.key) || e.key === 'Dead' || e.key === 'Unidentified') return null;
  const mods: string[] = [];
  if (e.ctrlKey) mods.push('Ctrl');
  if (e.altKey) mods.push('Alt');
  if (e.shiftKey) mods.push('Shift');
  if (e.metaKey) mods.push('Meta');
  let key = e.key;
  const withCommand = e.ctrlKey || e.altKey || e.metaKey;
  if (key === ' ') key = 'Space';
  else if (/^Key[A-Z]$/.test(e.code) && (withCommand || !/^[a-z]$/i.test(key))) key = e.code.slice(3);
  else if (/^Digit[0-9]$/.test(e.code) && withCommand) key = e.code.slice(5);
  else if (key === 'Esc') key = 'Escape';
  else if (key.length === 1) key = key.toUpperCase();
  return [...mods, key].join('+');
}

export function matches(e: KeyboardEvent | ReactKeyboardEvent, bindings: string[] | undefined): boolean {
  if (!bindings?.length) return false;
  const b = eventToBinding(e);
  return b !== null && bindings.includes(b);
}

/** A key that types text (no Ctrl/Alt/Meta): it must not fire while the user types in a field. */
export function isTypingKey(binding: string): boolean {
  const parts = binding.split('+');
  const key = parts[parts.length - 1] || '+';
  const mods = parts.slice(0, -1);
  if (mods.some(m => m === 'Ctrl' || m === 'Alt' || m === 'Meta')) return false;
  return key.length === 1 || key === 'Space' || key === 'Backspace' || key === 'Delete' ||
    key === 'ArrowLeft' || key === 'ArrowRight' || key === 'Home' || key === 'End';
}

const KEY_LABELS: Record<string, string> = {
  ArrowDown: '↓', ArrowUp: '↑', ArrowLeft: '←', ArrowRight: '→', Enter: '↵', Escape: 'Esc',
  Backspace: '⌫', Delete: 'Del', PageUp: 'PgUp', PageDown: 'PgDn', Meta: 'Win',
};

/** Parts for <kbd> chips: "Ctrl+ArrowDown" -> ["Ctrl", "↓"]. */
export function bindingParts(binding: string): string[] {
  const parts = binding.endsWith('++') ? [...binding.slice(0, -2).split('+'), '+'] : binding.split('+');
  return parts.filter(Boolean).map(p => KEY_LABELS[p] ?? p);
}

export function contextsOverlap(a: KeyContext, b: KeyContext): boolean {
  return a === 'both' || b === 'both' || a === b;
}

/** Other actions that use the same key in the same place. */
export function conflictsFor(map: Keymap, id: ActionId, binding: string): ActionDef[] {
  const me = ACTIONS.find(a => a.id === id)!;
  return ACTIONS.filter(a => a.id !== id && contextsOverlap(a.context, me.context) && map[a.id].includes(binding));
}

// -- global key (the "keyboard" package names: "alt+space", "ctrl+shift+f") --------------

const GLOBAL_NAMES: Record<string, string> = {
  Space: 'space', Enter: 'enter', Escape: 'esc', Tab: 'tab', Backspace: 'backspace', Delete: 'delete',
  Insert: 'insert', Home: 'home', End: 'end', ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right',
};

export function bindingToGlobal(binding: string): string | null {
  const parts = binding.split('+');
  const key = parts[parts.length - 1];
  const mods = parts.slice(0, -1).map(m => (m === 'Meta' ? 'windows' : m.toLowerCase()));
  let name = GLOBAL_NAMES[key];
  if (!name && /^[A-Z0-9]$/.test(key)) name = key.toLowerCase();
  if (!name && /^F([1-9]|1[0-9]|2[0-4])$/.test(key)) name = key.toLowerCase();
  if (!name) return null;
  if (!mods.length && !/^f\d+$/.test(name)) return null;
  return [...mods, name].join('+');
}

export function globalToParts(hotkey: string): string[] {
  return hotkey.split('+').map(p => {
    if (p === 'windows') return 'Win';
    if (p === 'esc') return 'Esc';
    if (p.length === 1) return p.toUpperCase();
    return p.charAt(0).toUpperCase() + p.slice(1);
  });
}
