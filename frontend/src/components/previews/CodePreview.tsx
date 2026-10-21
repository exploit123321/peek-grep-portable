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

const escapeHtml = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

interface CodePreviewProps {
  content: string;
  language?: string;
}

export const CodePreview: React.FC<CodePreviewProps> = ({ content, language = 'plain' }) => {
  const { html, gutter } = useMemo(() => {
    const grammar = Prism.languages[language];
    const head = content.slice(0, HIGHLIGHT_LIMIT);
    const tail = content.slice(HIGHLIGHT_LIMIT);
    const highlighted = grammar ? Prism.highlight(head, grammar, language) : escapeHtml(head);
    const count = content.split('\n').length;
    return {
      html: highlighted + escapeHtml(tail),
      gutter: Array.from({ length: count }, (_, i) => i + 1).join('\n'),
    };
  }, [content, language]);

  return (
    <div className="h-full overflow-auto select-text">
      <div className="flex min-w-max px-1 py-4 font-mono text-[12px] leading-[1.65]">
        <pre className="select-none text-right pr-4 mr-4 text-fg-3 opacity-60" style={{ borderRight: '1px solid var(--line)' }}>
          {gutter}
        </pre>
        <pre className={`m-0 pr-6 language-${language}`}>
          <code className={`language-${language}`} dangerouslySetInnerHTML={{ __html: html }} />
        </pre>
      </div>
    </div>
  );
};

export const PlainPreview: React.FC<{ content: string }> = ({ content }) => <CodePreview content={content} language="plain" />;
