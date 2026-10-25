import React, { useMemo } from 'react';
import Prism from 'prismjs';

import 'prismjs/components/prism-python';
import 'prismjs/components/prism-json';
import 'prismjs/components/prism-bash';
import 'prismjs/components/prism-typescript';
import 'prismjs/components/prism-sql';
import 'prismjs/components/prism-markdown';
import 'prismjs/components/prism-yaml';
import 'prismjs/components/prism-toml';
import 'prismjs/components/prism-rust';
import 'prismjs/components/prism-go';

// Syntax highlighting is limited to the first 200 KB so that large files stay fast.
const HIGHLIGHT_LIMIT = 200 * 1024;
// Lines are drawn in blocks; the browser skips the blocks outside the view (very long files)
const LINES_PER_BLOCK = 400;

const escapeHtml = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/** Highlighted HTML split into lines: tags open at a line break are closed and opened again. */
export function splitHtmlLines(html: string): string[] {
  const lines: string[] = [];
  const open: string[] = [];
  let line = '';
  const re = /(<[^>]+>)|([^<]+)/g;
  for (let m = re.exec(html); m; m = re.exec(html)) {
    if (m[1]) {
      const tag = m[1];
      if (tag.startsWith('</')) open.pop();
      else if (!tag.endsWith('/>')) open.push(tag);
      line += tag;
      continue;
    }
    const parts = m[2].split('\n');
    for (let i = 0; i < parts.length; i++) {
      if (i > 0) {
        lines.push(line + '</span>'.repeat(open.length));
        line = open.join('');
      }
      line += parts[i];
    }
  }
  lines.push(line);
  return lines;
}

interface CodePreviewProps {
  content: string;
  language?: string;
  /** Long lines continue on the next row (the line number stays at its line) */
  wrap?: boolean;
}

export const CodePreview: React.FC<CodePreviewProps> = ({ content, language = 'plain', wrap = true }) => {
  const blocks = useMemo(() => {
    const grammar = Prism.languages[language];
    const head = content.slice(0, HIGHLIGHT_LIMIT);
    const tail = content.slice(HIGHLIGHT_LIMIT);
    const highlighted = grammar ? Prism.highlight(head, grammar, language) : escapeHtml(head);
    const lines = splitHtmlLines(highlighted + escapeHtml(tail));
    const out: string[] = [];
    for (let start = 0; start < lines.length; start += LINES_PER_BLOCK) {
      out.push(
        lines
          .slice(start, start + LINES_PER_BLOCK)
          // The number is drawn by CSS (data-n): it is not text, so Find and copying leave it out
          .map((l, k) => `<div class="code-line" data-n="${start + k + 1}">${l || ' '}</div>`)
          .join(''),
      );
    }
    return { blocks: out, digits: String(lines.length).length };
  }, [content, language]);

  return (
    <div className="h-full overflow-auto select-text" data-code-scroller>
      <pre
        className={`code-lines m-0 py-4 pr-6 font-mono text-[12px] leading-[1.65] language-${language} ${wrap ? 'code-wrap' : 'min-w-max'}`}
        style={{ ['--gutter' as string]: `${blocks.digits + 1}ch` }}
      >
        <code className={`language-${language}`}>
          {blocks.blocks.map((html, i) => (
            <div key={i} className="code-block" dangerouslySetInnerHTML={{ __html: html }} />
          ))}
        </code>
      </pre>
    </div>
  );
};

export const PlainPreview: React.FC<{ content: string; wrap?: boolean }> = ({ content, wrap }) => (
  <CodePreview content={content} language="plain" wrap={wrap} />
);

/** The number of the first line at the top of a code or text preview (for the editor to open there). */
export function topCodeLine(root: HTMLElement | null): number | null {
  const scroller = root?.querySelector<HTMLElement>('[data-code-scroller]');
  if (!scroller) return null;
  const top = scroller.getBoundingClientRect().top;
  for (const el of scroller.querySelectorAll<HTMLElement>('.code-line')) {
    const r = el.getBoundingClientRect();
    if (r.bottom > top + 2) return Number(el.dataset.n) || null;
  }
  return null;
}

/** Scroll a code or text preview so that this line is at the top. */
export function scrollToCodeLine(root: HTMLElement | null, line: number): boolean {
  const el = root?.querySelector<HTMLElement>(`[data-code-scroller] .code-line[data-n="${line}"]`);
  if (!el) return false;
  el.scrollIntoView({ block: 'start' });
  return true;
}
