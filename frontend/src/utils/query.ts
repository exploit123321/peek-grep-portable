// Search terms on the client: highlight patterns (from the server's parsed query), the
// "find in preview" text, and pasted lists turned into a search. The characters of the syntax
// come from the search settings.

import { DEFAULT_SEARCH_OPTIONS, SearchOptions } from './searchOptions';

export type PieceKind = 'text' | 'any' | 'one';

export interface HighlightTerm {
  text: string;
  literal: boolean;
  exact?: boolean;
  pieces: [PieceKind, string][];
  field: 'name' | 'text' | 'any';
}

export function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** A term from plain text: "*" and "?" are wildcards unless the term is literal. */
export function makeTerm(text: string, literal = false, field: HighlightTerm['field'] = 'any', wildcards = true): HighlightTerm {
  const pieces: [PieceKind, string][] = [];
  if (literal || !wildcards) {
    if (text) pieces.push(['text', text]);
  } else {
    let buf = '';
    for (const ch of text) {
      if (ch === '*' || ch === '?') {
        if (buf) pieces.push(['text', buf]);
        buf = '';
        if (ch === '?') pieces.push(['one', '']);
        else if (pieces[pieces.length - 1]?.[0] !== 'any') pieces.push(['any', '']);
      } else buf += ch;
    }
    if (buf) pieces.push(['text', buf]);
  }
  return { text, literal, pieces, field };
}

// One character of a word in file text (the index splits words at spaces and punctuation)
const WORD_CHAR = '[^\\s.,;:!?()[\\]{}"\'/\\\\|<>=+*&^%$#@~`-]';

function piecesSource(pieces: [PieceKind, string][], target: 'name' | 'text'): string {
  // Names: leading and trailing * mark nothing. Text: * and ? stay inside a word.
  let list = pieces;
  if (target === 'name') {
    while (list.length && list[0][0] === 'any') list = list.slice(1);
    while (list.length && list[list.length - 1][0] === 'any') list = list.slice(0, -1);
  }
  return list
    .map(([kind, text]) => {
      if (kind === 'text') return escapeRegExp(text).replace(/\s+/g, '\\s+');
      if (kind === 'one') return target === 'name' ? '.' : WORD_CHAR;
      return target === 'name' ? '.*?' : `${WORD_CHAR}*`;
    })
    .join('');
}

/** Regexes for one term, best first: the whole term, then (for plain text) its single words. */
export function termRegexes(term: HighlightTerm, target: 'name' | 'text'): RegExp[] {
  const whole = piecesSource(term.pieces, target);
  const out: RegExp[] = [];
  if (whole) out.push(new RegExp(whole, 'gi'));
  if (!term.literal) {
    const words = term.text.trim().split(/\s+/).filter(w => w.replace(/[*?]/g, '').length > 1);
    if (words.length > 1) {
      for (const w of words) {
        const src = piecesSource(makeTerm(w).pieces, target);
        if (src) out.push(new RegExp(src, 'gi'));
      }
    }
  }
  return out;
}

/**
 * The regexes to mark, given a test "does this text have a hit": per term the whole term,
 * or its words when the whole term has no hit.
 */
export function pickRegexes(terms: HighlightTerm[], target: 'name' | 'text', has: (re: RegExp) => boolean): RegExp[] {
  const out: RegExp[] = [];
  for (const term of terms) {
    const [whole, ...words] = termRegexes(term, target);
    if (!whole) continue;
    if (has(whole) || !words.length) out.push(whole);
    else out.push(...words);
  }
  return out;
}

export function textTerms(terms: HighlightTerm[]): HighlightTerm[] {
  return terms.filter(t => t.field !== 'name');
}

export function nameTerms(terms: HighlightTerm[]): HighlightTerm[] {
  return terms.filter(t => t.field !== 'text');
}

/** "Find in preview" text: the "and" sign finds several terms, the literal sign or quotes make it literal. */
export function parseFindText(text: string, o: SearchOptions = DEFAULT_SEARCH_OPTIONS): HighlightTerm[] {
  const t = text.trim();
  if (!t) return [];
  if (!o.enabled) return [makeTerm(t, true, 'text')];
  if (o.literal_char && t.startsWith(o.literal_char)) return t.length > 1 ? [makeTerm(t.slice(1), true, 'text')] : [];
  if (o.quotes && t.length > 1 && t.startsWith('"')) return [makeTerm(t.slice(1).replace(/"$/, ''), true, 'text')];
  const parts = o.and_char ? t.split(o.and_char) : [t];
  return parts
    .map(part => part.trim())
    .filter(Boolean)
    .map(part => makeTerm(part, false, 'text', o.wildcards));
}

// -- pasted lists --------------------------------------------------------------

/** Rows and cells of copied spreadsheet text (tab between cells, quotes around cells with breaks). */
export function parseClipboardGrid(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let i = 0;
  let quoted = false;
  const src = text.replace(/\r\n?/g, '\n');
  while (i < src.length) {
    const ch = src[i];
    if (quoted) {
      if (ch === '"') {
        if (src[i + 1] === '"') { cell += '"'; i += 2; continue; }
        quoted = false; i++; continue;
      }
      cell += ch; i++; continue;
    }
    if (ch === '"' && cell === '') { quoted = true; i++; continue; }
    if (ch === '\t') { row.push(cell); cell = ''; i++; continue; }
    if (ch === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; i++; continue; }
    cell += ch; i++;
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
  // Drop empty rows at the end (Excel adds a line break after the last row)
  while (rows.length && rows[rows.length - 1].every(c => !c.trim())) rows.pop();
  return rows;
}

/** True when pasted text is a list (several lines or cells), not one value. */
export function isListPaste(text: string): boolean {
  const trimmed = text.replace(/[\r\n]+$/, '');
  return /[\n\t]/.test(trimmed);
}

export type ListMode = 'groups' | 'together';
export type ListWhere = 'names' | 'text';

function needsQuotes(value: string, o: SearchOptions): boolean {
  const signs = [o.text_char, o.and_char, o.group_open, o.group_close, o.list_char, o.param_char, o.quotes ? '"' : '']
    .filter(Boolean);
  if (o.wildcards) signs.push('*', '?');
  if (signs.some(c => value.includes(c))) return true;
  if (o.literal_char && value.startsWith(o.literal_char)) return true;
  if (o.extensions && value.startsWith('.')) return true;
  if (o.not_char && value.includes(o.not_char)) {
    if (value.startsWith(o.not_char)) return true;
    // A "not" sign that would start a part (a dash between two digits stays text)
    const n = o.not_char.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = o.dash_mode === 'word_start' ? new RegExp(`\\s${n}\\S`) : new RegExp(`(^|[^0-9])${n}|${n}([^0-9]|$)`);
    if (re.test(value)) return true;
  }
  return false;
}

/** One value as search text: quoted (literal) when it holds characters of the search syntax. */
export function quoteValue(value: string, o: SearchOptions = DEFAULT_SEARCH_OPTIONS): string {
  const v = value.trim();
  if (!o.enabled || !o.quotes || !needsQuotes(v, o)) return v;
  return `"${v.replace(/"/g, '""')}"`;
}

/**
 * A list as a search: [a, b] (one group per value) or a+b (every value must hit), in file names
 * or (after ":") in the text. filter: file names or types first, like ".xlsx" or "invoice-old".
 */
export function listToQuery(values: string[], mode: ListMode, where: ListWhere, filter = '',
                            o: SearchOptions = DEFAULT_SEARCH_OPTIONS): string {
  const parts = values.map(v => v.trim()).filter(Boolean).map(v => quoteValue(v, o));
  const trailing = [o.and_char, o.text_char, o.list_char].filter(Boolean).map(c => `\\${c}`).join('');
  const f = filter.trim().replace(new RegExp(`[${trailing}\\s]+$`), '');
  const list = mode === 'groups' && o.group_open
    ? `${o.group_open}${parts.join(`${o.list_char} `)}${o.group_close}`
    : parts.join(o.and_char || ' ');
  if (where === 'text' && o.text_char) return `${f}${o.text_char}${list}`;
  if (!parts.length) return f;
  return f ? `${f}${o.and_char || ' '}${list}` : list;
}
