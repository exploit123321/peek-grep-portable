import React, { useMemo } from 'react';
import { marked } from 'marked';
import { sanitizeHtml } from '../../utils/sanitize';
import { CodePreview } from './CodePreview';

marked.setOptions({ gfm: true, breaks: true });

export const MarkdownPreview: React.FC<{ content: string; raw: boolean }> = ({ content, raw }) => {
  const html = useMemo(() => sanitizeHtml(marked.parse(content) as string), [content]);
  if (raw) return <CodePreview content={content} language="markdown" />;
  return (
    <div className="h-full overflow-auto">
      <div className="markdown-body max-w-[760px] mx-auto px-8 py-7 text-[13.5px]" dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  );
};
