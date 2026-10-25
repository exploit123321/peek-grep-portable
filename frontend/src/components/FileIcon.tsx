import React from 'react';
import { BookOpen, File, FileCode2, FileSpreadsheet, FileText, Film, Image as ImageIcon, NotebookText, Presentation, Sheet } from 'lucide-react';
import { FileKind, KIND_COLORS } from '../utils/formatters';

const ICONS: Record<FileKind, React.ComponentType<{ className?: string; style?: React.CSSProperties }>> = {
  code: FileCode2,
  markdown: NotebookText,
  data: Sheet,
  media: ImageIcon,
  video: Film,
  pdf: FileText,
  epub: BookOpen,
  word: FileText,
  excel: FileSpreadsheet,
  powerpoint: Presentation,
  text: FileText,
  other: File,
};

interface FileIconProps {
  kind: FileKind;
  size?: 'sm' | 'md' | 'lg';
}

export const FileIcon: React.FC<FileIconProps> = ({ kind, size = 'md' }) => {
  const Icon = ICONS[kind];
  const colors = KIND_COLORS[kind];
  const box = size === 'lg' ? 'w-10 h-10 rounded-xl' : size === 'sm' ? 'w-6 h-6 rounded-md' : 'w-8 h-8 rounded-lg';
  const icon = size === 'lg' ? 'w-5 h-5' : size === 'sm' ? 'w-3.5 h-3.5' : 'w-4 h-4';
  return (
    <span
      className={`inline-flex items-center justify-center shrink-0 ${box}`}
      style={{ background: colors.bg, color: colors.fg, boxShadow: 'inset 0 0 0 1px rgba(255,255,255,0.05)' }}
    >
      <Icon className={icon} />
    </span>
  );
};
