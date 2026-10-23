// Frozen rows and columns of table views: from the settings (for every file), or set in Quick Look
// for one file. Anything set for a file replaces both settings for it ("0" freezes nothing there).

export interface Freeze {
  /** Row numbers as shown at the left (1 = first row) */
  rows: ReadonlySet<number>;
  /** Column numbers (1 = A, the first column) */
  cols: ReadonlySet<number>;
  /** As typed ("1-3, 7", "A-B") */
  rowsText: string;
  colsText: string;
}

export const NO_FREEZE: Freeze = { rows: new Set(), cols: new Set(), rowsText: '', colsText: '' };

const MAX_ROWS = 100;
const MAX_COLS = 50;
const ROW_PART = /^(\d+)(?:-(\d+))?$/;
const COL_PART = /^([A-Za-z]{1,3}|\d+)(?:-([A-Za-z]{1,3}|\d+))?$/;

const parts = (spec: string) => spec.replace(/–/g, '-').split(/[,;\s]+/).filter(Boolean);

function columnNumber(ref: string): number {
  if (/^\d+$/.test(ref)) return Number(ref);
  let n = 0;
  for (const ch of ref.toUpperCase()) n = n * 26 + ch.charCodeAt(0) - 64;
  return n;
}

function collect(spec: string, re: RegExp, toNumber: (s: string) => number, max: number): Set<number> {
  const out = new Set<number>();
  for (const part of parts(spec)) {
    const m = re.exec(part);
    if (!m) continue;
    const a = toNumber(m[1]), b = toNumber(m[2] ?? m[1]);
    for (let n = Math.max(1, Math.min(a, b)); n <= Math.max(a, b) && out.size < max; n++) out.add(n);
  }
  return out;
}

/** "1-3, 7" -> rows 1, 2, 3, 7 */
export const parseFrozenRows = (spec: string) => collect(spec, ROW_PART, Number, MAX_ROWS);

/** "A-B, E" or "1-2, 5" -> columns 1, 2, 5 */
export const parseFrozenColumns = (spec: string) => collect(spec, COL_PART, columnNumber, MAX_COLS);

/** The parts that cannot be read ("" when all can). */
export function badParts(spec: string, kind: 'rows' | 'cols'): string {
  const re = kind === 'rows' ? ROW_PART : COL_PART;
  return parts(spec).filter(p => !re.test(p)).join(', ');
}

export function parseFreeze(rows: string, cols: string): Freeze {
  return { rows: parseFrozenRows(rows), cols: parseFrozenColumns(cols), rowsText: rows, colsText: cols };
}

// -- one file -----------------------------------------------------------------------
// Kept in this browser profile (data\webview), at most MAX_FILES files, the newest kept.

export interface FileFreeze {
  rows: string;
  cols: string;
}

const KEY = 'pg-freeze-files';
const MAX_FILES = 300;

function readAll(): Record<string, FileFreeze> {
  try {
    const raw = window.localStorage.getItem(KEY);
    const data = raw ? JSON.parse(raw) : {};
    return data && typeof data === 'object' ? data : {};
  } catch {
    return {};
  }
}

export function fileFreeze(path: string): FileFreeze | null {
  const entry = readAll()[path.toLowerCase()];
  return entry && typeof entry.rows === 'string' && typeof entry.cols === 'string' ? entry : null;
}

/** null removes the file's own setting (the settings apply again). */
export function setFileFreeze(path: string, value: FileFreeze | null): void {
  try {
    const all = readAll();
    const key = path.toLowerCase();
    delete all[key];
    if (value) all[key] = value;
    const keys = Object.keys(all);
    for (const old of keys.slice(0, Math.max(0, keys.length - MAX_FILES))) delete all[old];
    window.localStorage.setItem(KEY, JSON.stringify(all));
  } catch {
    // No storage (private window, blocked): the setting lasts until Quick Look closes
  }
}
