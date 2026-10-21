import React from 'react';
import { AlertTriangle, Check, Folder } from 'lucide-react';
import { IndexerStatus } from '../api';
import { RollingNumber } from './motion/RollingNumber';
import { folderLabel } from '../utils/paths';

// One row per folder: "queued" -> "scanning" with a spinner and a rolling count -> a check
// with the final count (matrix refs E19 working rows with checks, X04 searching rows).

export const IndexingRows: React.FC<{ status: IndexerStatus | null }> = ({ status }) => {
  const folders = status?.folders ?? [];
  const content = status?.content ?? { indexed: 0, pending: 0 };
  const totalContent = content.indexed + content.pending;
  const pct = totalContent ? Math.round((content.indexed / totalContent) * 100) : 0;
  const scanning = status?.phase === 'scanning';

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col rounded-xl overflow-hidden panel">
        {folders.map((f, i) => {
          const busy = f.state === 'scanning' || f.state === 'queued';
          const failed = f.state === 'missing' || f.state === 'error' || !f.exists;
          return (
            <div
              key={f.path}
              className="flex items-center gap-3 h-[52px] px-3.5 fade-up"
              style={{ ['--d' as string]: `${i * 70}ms`, borderTop: i ? '1px solid var(--line)' : undefined }}
            >
              <span className="flex items-center justify-center w-8 h-8 rounded-lg shrink-0" style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}>
                <Folder className="w-4 h-4" />
              </span>
              <div className="flex flex-col min-w-0 flex-1">
                <span className="truncate text-[13px] font-medium text-fg">{folderLabel(f.path)}</span>
                <span className="truncate font-mono text-[11px] text-fg-3">{f.path}</span>
              </div>
              <div className="flex items-center gap-2.5 shrink-0 text-[12px]">
                {f.files > 0 && <RollingNumber value={f.files} className="font-mono text-fg-2" />}
                {failed ? (
                  <span className="flex items-center gap-1.5 text-warn">
                    <AlertTriangle className="w-3.5 h-3.5" /> {f.exists ? 'Cannot read' : 'Not found'}
                  </span>
                ) : busy ? (
                  <span className="flex items-center gap-1.5 text-fg-3 w-[86px] justify-end">
                    {f.state === 'queued' ? 'waiting' : 'scanning'}
                    <span className="w-3.5 h-3.5 rounded-full spin" style={{ border: '1.5px solid var(--line-strong)', borderTopColor: 'var(--accent)' }} />
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5 text-fg-2 w-[86px] justify-end">
                    files
                    <span className="flex items-center justify-center w-[18px] h-[18px] rounded-full pop-in" style={{ background: 'var(--ok)', color: '#08140e' }}>
                      <Check className="w-3 h-3" strokeWidth={3} />
                    </span>
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex flex-col gap-2 px-1">
        <div className="flex items-center justify-between text-[12px]">
          <span className="text-fg-2">
            {scanning ? 'Reading names first. Text comes next.' : content.pending ? 'Reading text inside files' : 'Text index is complete'}
          </span>
          <span className="font-mono text-fg-3">
            <RollingNumber value={content.indexed} /> / <RollingNumber value={totalContent} />
          </span>
        </div>
        <div className="relative h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--surface-2)' }}>
          <div
            className="absolute inset-y-0 left-0 rounded-full"
            style={{
              width: `${scanning && !totalContent ? 0 : pct}%`,
              background: 'linear-gradient(90deg, var(--accent-strong), var(--accent))',
              transition: 'width 700ms var(--ease-out)',
            }}
          />
          {scanning && <div className="absolute inset-0 loading-line opacity-60" />}
        </div>
      </div>
    </div>
  );
};
