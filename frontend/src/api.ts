// Typed calls to the local backend and to the desktop window bridge (pywebview).

import type { HighlightTerm } from './utils/query';
import type { SearchOptions, SearchPreset } from './utils/searchOptions';

export type Category = 'all' | 'code' | 'docs' | 'data' | 'media';
export type Delimiter = 'auto' | 'comma' | 'semicolon' | 'tab' | 'colon' | 'pipe' | 'space';

export interface SearchItem {
  path: string;
  filename: string;
  extension: string;
  size_bytes: number;
  mtime: number;
  is_text: boolean;
  snippet?: string | null;
  match_type: string;
  category: string;
}

export interface ExplainChip {
  kind: 'ext' | 'not-ext' | 'name' | 'not-name' | 'exact' | 'not-exact' | 'text' | 'not-text' | 'any' | 'not-any' | 'groups' | 'param' | 'param-error';
  text: string;
  literal: boolean;
}

export interface SearchGroup {
  label: string;
  total: number;
  offset: number;
  has_more: boolean;
  results: SearchItem[];
  highlight: HighlightTerm[];
}

export interface SearchResponse {
  query: string;
  total: number;
  took_ms: number;
  results: SearchItem[];
  offset: number;
  has_more: boolean;
  grouped: boolean;
  groups: SearchGroup[];
  highlight: HighlightTerm[];
  explain: ExplainChip[];
}

export interface AppSettings {
  hotkey: string;
  default_hotkey: string;
  shortcuts: Record<string, string[]>;
  can_set_hotkey: boolean;
  search: SearchOptions;
  search_defaults: SearchOptions;
  search_presets: SearchPreset[];
  app: AppOptions;
  autostart_available: boolean;
  backups: BackupOptions;
  big_files: BigFileRule[];
}

/** Large files: a file type (".csv"), a part of the name ("big"), or one file (full path). */
export interface BigFileRule {
  kind: 'type' | 'name' | 'file';
  value: string;
}

/** Backups when the editor saves: one per editing session (gap_minutes), a few kept per file. */
export interface BackupOptions {
  enabled: boolean;
  per_file: number;
  gap_minutes: number;
}

export interface BackupsInfo {
  count: number;
  bytes: number;
  folder: string;
}

export interface SaveResult {
  success: boolean;
  mtime_ns: string;
  /** The backup this save made, or null */
  backup: string | null;
  /** A recent backup kept instead of making a new one */
  backup_kept: string | null;
  indexed: boolean;
}

export interface AppOptions {
  start_with_windows: boolean;
  start_hidden: boolean;
  open_on_mouse_monitor: boolean;
  release_window_on_hide: boolean;
  /** Table rows kept at the top, like "1" or "1-3, 7" (empty: none) */
  freeze_rows: string;
  /** Table columns kept at the left, like "A" or "A-B, E" (empty: none) */
  freeze_columns: string;
}

export interface SearchParams {
  q: string;
  type: Category;
  folder?: string | null;
  offset?: number;
  limit?: number;
  group?: number | null;
}

export type FolderState = 'idle' | 'queued' | 'scanning' | 'done' | 'stopped' | 'missing' | 'error';

export interface FolderStatus {
  path: string;
  state: FolderState;
  files: number;
  exists: boolean;
}

export interface IndexerStatus {
  phase: 'setup' | 'scanning' | 'reading' | 'ready';
  is_crawling: boolean;
  total_indexed: number;
  current_folder?: string | null;
  current_path?: string | null;
  files_per_sec: number;
  errors_encountered: number;
  folders: FolderStatus[];
  content: { indexed: number; pending: number; current_file?: string | null };
  watcher_active: boolean;
}

export interface FolderDetails {
  setup_done: boolean;
  folders: FolderStatus[];
  suggestions: { label: string; path: string }[];
  drives: string[];
  data_dir: string;
  can_pick: boolean;
}

export interface FolderCheck {
  ok: boolean;
  path: string;
  error?: string | null;
  warning?: string | null;
  covered_by?: string | null;
  contains?: string[];
}

export interface AppStatus {
  version: string;
  indexed_files: number;
  content_indexed: number;
  setup_done: boolean;
  folders: string[];
  data_dir: string;
}

interface PyWebviewApi {
  hide_window?: () => Promise<void>;
  show_window?: () => Promise<void>;
  minimize?: () => Promise<void>;
  resize_window?: (w: number, h: number) => Promise<void>;
  toggle_maximize?: () => Promise<boolean>;
  get_window_size?: () => Promise<{ width: number; height: number; is_maximized: boolean }>;
  pick_folders?: () => Promise<string[]>;
  open_data_folder?: () => Promise<void>;
  quit_app?: () => Promise<void>;
}

export function desktop(): PyWebviewApi | null {
  const api = (window as unknown as { pywebview?: { api?: PyWebviewApi } }).pywebview?.api;
  return api ?? null;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === 'string') message = body.detail;
      else if (body.detail?.errors?.[0]?.error) message = body.detail.errors[0].error;
    } catch {
      /* keep the HTTP message */
    }
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

function post<T>(url: string, body?: unknown, method = 'POST'): Promise<T> {
  return request<T>(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export const api = {
  status: () => request<AppStatus>('/api/status'),
  indexer: () => request<IndexerStatus>('/api/indexer/status'),
  folders: () => request<FolderDetails>('/api/folders'),
  checkFolder: (path: string, current: string[]) => post<FolderCheck>('/api/folders/check', { path, current }),
  saveFolders: (folders: string[]) =>
    post<{ success: boolean; added: string[]; removed: string[]; purged_files: number; folders: string[] }>(
      '/api/folders',
      { folders },
      'PUT',
    ),
  reindex: (folder?: string) => post<{ queued: string[] }>('/api/reindex', folder ? { folder } : {}),
  search: (params: SearchParams, signal?: AbortSignal) => {
    const qs = new URLSearchParams({
      q: params.q,
      type_filter: params.type,
      limit: String(params.limit ?? 60),
      offset: String(params.offset ?? 0),
    });
    if (params.folder) qs.set('folder', params.folder);
    if (params.group !== undefined && params.group !== null) qs.set('group', String(params.group));
    return request<SearchResponse>(`/api/search?${qs.toString()}`, { signal });
  },
  settings: () => request<AppSettings>('/api/settings'),
  saveShortcuts: (body: { hotkey?: string; shortcuts?: Record<string, string[]> }) =>
    post<AppSettings>('/api/settings/shortcuts', body, 'PUT'),
  saveSearchSettings: (options: Partial<SearchOptions>) => post<AppSettings>('/api/settings/search', options, 'PUT'),
  saveAppSettings: (options: Partial<AppOptions>) => post<AppSettings>('/api/settings/app', options, 'PUT'),
  saveBackupSettings: (options: Partial<BackupOptions>) => post<AppSettings>('/api/settings/backups', options, 'PUT'),
  saveBigFiles: (rules: BigFileRule[]) => post<AppSettings>('/api/settings/big_files', { rules }, 'PUT'),
  backups: () => request<BackupsInfo>('/api/edit/backups'),
  deleteBackups: () => post<BackupsInfo>('/api/edit/backups', undefined, 'DELETE'),
  openBackups: () => post<BackupsInfo>('/api/edit/backups/open'),
  preview: (path: string, signal?: AbortSignal, delimiter: Delimiter = 'auto', quick = false) =>
    request<PreviewPayload>(`/api/preview?path=${encodeURIComponent(path)}&delimiter=${delimiter}${quick ? '&quick=true' : ''}`, { signal }),
  open: (path: string) => post<{ message: string }>('/api/actions/open', { path }),
  reveal: (path: string) => post<{ message: string }>('/api/actions/reveal', { path }),
  editLoad: (path: string) => request<EditModel>(`/api/edit?path=${encodeURIComponent(path)}`),
  editSave: (path: string, mtime_ns: string, payload: Record<string, unknown>) =>
    post<SaveResult>('/api/edit/save', { path, mtime_ns, payload }),

  async pickFolders(): Promise<string[] | null> {
    const d = desktop();
    if (d?.pick_folders) return (await d.pick_folders()) ?? [];
    try {
      const res = await post<{ paths: string[] }>('/api/folders/pick');
      return res.paths;
    } catch {
      return null; // no native dialog (browser preview): the user types the path
    }
  },
  async hideWindow() {
    const d = desktop();
    if (d?.hide_window) return d.hide_window();
    await post('/api/actions/hide-window');
  },
  async toggleMaximize(): Promise<boolean> {
    const d = desktop();
    if (d?.toggle_maximize) return d.toggle_maximize();
    return false;
  },
  async resizeWindow(w: number, h: number) {
    const d = desktop();
    if (d?.resize_window) return d.resize_window(w, h);
  },
  async openDataFolder() {
    const d = desktop();
    if (d?.open_data_folder) return d.open_data_folder();
    await post('/api/actions/open-data-folder');
  },
  async quit() {
    const d = desktop();
    if (d?.quit_app) return d.quit_app();
  },
};

export interface PreviewPayload {
  path: string;
  filename: string;
  extension: string;
  size_bytes: number;
  mtime: number;
  preview_type: 'code' | 'markdown' | 'table' | 'image' | 'plain' | 'binary' | 'pdf' | 'epub' | 'document' | 'workbook' | 'slides';
  content?: string;
  language?: string;
  truncated?: boolean;
  table_data?: {
    columns: string[];
    rows: string[][];
    total_rows: number;
    total_columns: number;
    delimiter: Exclude<Delimiter, 'auto'>;
    detected: boolean;
  };
  image_meta?: { width: number; height: number; format: string; mode: string; aspect_ratio: string };
  epub_data?: {
    title?: string | null;
    author?: string | null;
    language?: string | null;
    cover_data_url?: string | null;
    chapters: { title?: string | null; content: string }[];
    total_chapters: number;
  };
  editable?: EditKind | null;
  document_html?: string | null;
  sheets?: SheetData[] | null;
  slides?: SlideData[] | null;
  raw_url?: string;
}

export interface SheetData {
  name: string;
  columns: string[];
  rows: string[][];
  total_rows: number;
  total_columns: number;
  truncated: boolean;
  partial?: boolean;
}

export interface SlideData {
  number: number;
  title: string;
  paragraphs: { text: string; level: number }[];
  images: number;
}

export type EditKind = 'text' | 'csv' | 'workbook' | 'document';

export interface EditModel {
  kind: EditKind;
  mtime_ns: string;
  text?: string;
  encoding?: string;
  newline?: string;
  rows?: string[][];
  delimiter?: Exclude<Delimiter, 'auto'>;
  sheets?: (SheetData & { formulas: [number, number][] })[];
  paragraphs?: { id: number; text: string; style: string; table: boolean; locked: boolean }[];
}
