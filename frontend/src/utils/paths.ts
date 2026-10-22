// Path helpers for display: folder names, relative breadcrumbs, and match highlighting.

import { HighlightTerm, nameTerms, pickRegexes } from './query';

const SEP = '\\';

export function baseName(path: string): string {
  const trimmed = path.replace(/[\\/]+$/, '');
  const parts = trimmed.split(/[\\/]/);
  const last = parts[parts.length - 1];
  return last || trimmed;
}

export function folderLabel(folder: string): string {
  // "D:\" -> "D: drive", "D:\work\docs" -> "docs"
  if (/^[A-Za-z]:[\\/]?$/.test(folder)) return `${folder.slice(0, 2).toUpperCase()} drive`;
  return baseName(folder);
}

function startsWithFolder(path: string, folder: string): boolean {
  const p = path.toLowerCase();
  let f = folder.toLowerCase();
  if (p === f) return true;
  if (!f.endsWith(SEP)) f += SEP;
  return p.startsWith(f);
}

export function rootFor(path: string, folders: string[]): string | null {
  let best: string | null = null;
  for (const f of folders) {
    if (startsWithFolder(path, f) && (!best || f.length > best.length)) best = f;
  }
  return best;
}

/** Breadcrumb parts for the folder that holds a file: [root label, sub, sub]. */
export function folderCrumbs(path: string, folders: string[]): string[] {
  const dir = path.slice(0, Math.max(0, path.lastIndexOf(SEP)));
  const root = rootFor(path, folders);
  if (!root) return dir.split(SEP).filter(Boolean);
  const rest = dir.slice(root.replace(/[\\/]+$/, '').length).split(SEP).filter(Boolean);
  return [folderLabel(root), ...rest];
}

/** Keep the first and last crumbs when the trail is long. */
export function compactCrumbs(crumbs: string[], max = 4): string[] {
  if (crumbs.length <= max) return crumbs;
  return [crumbs[0], '…', ...crumbs.slice(crumbs.length - (max - 2))];
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/** Filename with the name terms of the search wrapped in <mark> (HTML-escaped). */
export function highlightName(name: string, terms: HighlightTerm[]): string {
  const regexes = pickRegexes(nameTerms(terms), 'name', re => {
    re.lastIndex = 0;
    return re.test(name);
  });
  if (!regexes.length) return escapeHtml(name);
  const marks = new Array<boolean>(name.length).fill(false);
  for (const re of regexes) {
    re.lastIndex = 0;
    for (let m = re.exec(name); m; m = re.exec(name)) {
      if (!m[0].length) {
        re.lastIndex++;
        continue;
      }
      for (let i = m.index; i < m.index + m[0].length; i++) marks[i] = true;
    }
  }
  let out = '';
  let open = false;
  for (let i = 0; i < name.length; i++) {
    if (marks[i] !== open) {
      out += marks[i] ? '<mark>' : '</mark>';
      open = marks[i];
    }
    out += escapeHtml(name[i]);
  }
  return out + (open ? '</mark>' : '');
}
