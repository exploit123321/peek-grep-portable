export function formatBytes(bytes: number, decimals = 1): string {
  if (!bytes) return '0 B';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(sizes.length - 1, Math.floor(Math.log(bytes) / Math.log(k)));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
}

export function formatRelativeTime(mtimeSeconds: number): string {
  const now = Date.now() / 1000;
  const diff = Math.max(0, now - mtimeSeconds);

  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;

  const date = new Date(mtimeSeconds * 1000);
  const sameYear = date.getFullYear() === new Date().getFullYear();
  return date.toLocaleDateString(undefined, sameYear ? { month: 'short', day: 'numeric' } : { year: 'numeric', month: 'short', day: 'numeric' });
}

export function formatDate(mtimeSeconds: number): string {
  return new Date(mtimeSeconds * 1000).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

export function formatCount(n: number): string {
  return n.toLocaleString('en-US');
}

/** Kind of file for icons and colors. */
export type FileKind = 'code' | 'markdown' | 'data' | 'media' | 'pdf' | 'epub' | 'word' | 'excel' | 'powerpoint' | 'text' | 'other';

const TEXT_EXT = new Set(['.txt', '.log', '.rtf', '.ini', '.cfg', '.conf', '.env', '.odt']);
const WORD_EXT = new Set(['.doc', '.docx', '.docm']);
const EXCEL_EXT = new Set(['.xls', '.xlsx', '.xlsm']);
const POWERPOINT_EXT = new Set(['.ppt', '.pptx', '.pptm']);

export function fileKind(category: string, extension: string): FileKind {
  const ext = extension.toLowerCase();
  if (WORD_EXT.has(ext)) return 'word';
  if (EXCEL_EXT.has(ext)) return 'excel';
  if (POWERPOINT_EXT.has(ext)) return 'powerpoint';
  if (ext === '.pdf' || category === 'pdf') return 'pdf';
  if (ext === '.epub' || category === 'epub') return 'epub';
  if (category === 'code') return 'code';
  if (category === 'markdown') return 'markdown';
  if (category === 'data') return 'data';
  if (category === 'media') return 'media';
  if (TEXT_EXT.has(ext)) return 'text';
  return 'other';
}

export const KIND_COLORS: Record<FileKind, { fg: string; bg: string }> = {
  code: { fg: '#a5b4ff', bg: 'rgba(124,156,255,0.12)' },
  markdown: { fg: '#7dd3fc', bg: 'rgba(56,189,248,0.11)' },
  data: { fg: '#6ee7b7', bg: 'rgba(52,211,153,0.11)' },
  media: { fg: '#fcd34d', bg: 'rgba(251,191,36,0.11)' },
  pdf: { fg: '#fda4af', bg: 'rgba(251,113,133,0.11)' },
  epub: { fg: '#d8b4fe', bg: 'rgba(192,132,252,0.11)' },
  word: { fg: '#93b4ff', bg: 'rgba(59,130,246,0.14)' },
  excel: { fg: '#6ee7a8', bg: 'rgba(34,197,94,0.13)' },
  powerpoint: { fg: '#fdba74', bg: 'rgba(249,115,22,0.13)' },
  text: { fg: '#c8c8d4', bg: 'rgba(255,255,255,0.06)' },
  other: { fg: '#9a9aab', bg: 'rgba(255,255,255,0.05)' },
};
