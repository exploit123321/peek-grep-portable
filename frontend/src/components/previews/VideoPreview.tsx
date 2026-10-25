import React, { useEffect, useMemo, useState } from 'react';
import { Film, Layers } from 'lucide-react';
import { VideoMeta } from '../../api';
import { metaLine, SnapOverlay, useFitBox } from './MediaFrame';

// Videos from phones and Snapchat (MP4, MOV, WebM). WebView2 plays H.264 and VP9 itself; HEVC (the
// iPhone's "High Efficiency" format) only where Windows has its decoder. What cannot play says why.

const HEVC = new Set(['hvc1', 'hev1', 'dvh1', 'dvhe']);
const NEVER = new Set(['apch', 'apcn', 'apcs', 'apco', 'ap4h', 'ap4x', 'aprn', 'aprh', 'mjpa', 'jpeg', 's263', 'h263']);

function duration(seconds?: number | null): string | null {
  if (seconds === null || seconds === undefined) return null;
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rest = String(s % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${rest}` : `${m}:${rest}`;
}

/** Why this video cannot play here, or null when it should. */
function blocked(meta: VideoMeta | null | undefined, mime: string | null | undefined): string | null {
  if (!mime) return 'This kind of video file (like AVI, WMV, or MPEG) does not play in the preview.';
  const codec = meta?.codec ?? '';
  if (NEVER.has(codec)) return `${meta?.codec_name ?? codec} plays only in video apps, not in the preview.`;
  if (HEVC.has(codec)) {
    const probe = document.createElement('video');
    if (!probe.canPlayType('video/mp4; codecs="hvc1.1.6.L93.B0"')) {
      return 'This is HEVC (H.265), the iPhone\'s "High Efficiency" format. This PC cannot play it in the preview: '
        + 'installing "HEVC Video Extensions" from the Microsoft Store adds it (most new PCs have it).';
    }
  }
  return null;
}

interface VideoPreviewProps {
  rawUrl: string;
  filename: string;
  meta?: VideoMeta | null;
  mime?: string | null;
  overlayUrl?: string | null;
}

export const VideoPreview: React.FC<VideoPreviewProps> = ({ rawUrl, filename, meta, mime, overlayUrl }) => {
  const reason = useMemo(() => blocked(meta, mime), [meta, mime]);
  const [failed, setFailed] = useState<string | null>(null);
  const [tryAnyway, setTryAnyway] = useState(false);
  const [overlay, setOverlay] = useState(true);
  const [size, setSize] = useState<{ w: number; h: number } | null>(
    meta?.width && meta?.height ? { w: meta.width, h: meta.height } : null,
  );
  useEffect(() => {
    setFailed(null);
    setTryAnyway(false);
    setSize(meta?.width && meta?.height ? { w: meta.width, h: meta.height } : null);
  }, [rawUrl]); // eslint-disable-line react-hooks/exhaustive-deps
  const { ref, box } = useFitBox(size ? size.w / size.h : 16 / 9);

  const info = metaLine([
    duration(meta?.duration),
    meta?.width && meta?.height ? `${meta.width}×${meta.height}` : null,
    meta?.codec_name,
    meta && !meta.audio ? 'no sound' : null,
    meta?.camera,
    meta?.created,
  ]);
  const stop = failed ?? (tryAnyway ? null : reason);

  return (
    <div className="relative flex flex-col h-full" style={{ background: '#0b0b0e' }}>
      <div ref={ref} className="relative flex-1 min-h-0 flex items-center justify-center">
        {stop ? (
          <div className="flex flex-col items-center gap-3 max-w-[460px] px-6 text-center">
            <span className="flex items-center justify-center w-12 h-12 rounded-2xl text-fg-3" style={{ background: 'var(--surface-2)' }}>
              <Film className="w-6 h-6" />
            </span>
            <div className="text-[13px] text-fg-2 leading-relaxed">{stop}</div>
            <div className="text-[12px] text-fg-3">Open plays it in your video app.</div>
            {!failed && reason && mime && (
              <button type="button" className="btn !h-7" onClick={() => setTryAnyway(true)}>
                Try to play it anyway
              </button>
            )}
          </div>
        ) : (
          box && (
            <div className="relative fade-up" style={{ width: box.width, height: box.height, animationDuration: '320ms' }}>
              <video
                key={rawUrl}
                src={rawUrl}
                controls
                preload="metadata"
                className="block w-full h-full rounded-md bg-black"
                aria-label={filename}
                onLoadedMetadata={e => {
                  const v = e.currentTarget;
                  if (v.videoWidth && v.videoHeight) setSize({ w: v.videoWidth, h: v.videoHeight });
                  // Sound but no picture: the codec is missing
                  else if (meta?.codec) setFailed(`This PC cannot show the picture of this ${meta.codec_name ?? meta.codec} video in the preview.`);
                }}
                onError={() => setFailed('This video could not be played in the preview.')}
                style={{ boxShadow: '0 20px 60px -20px rgba(0,0,0,0.8)' }}
              />
              {overlayUrl && overlay && <SnapOverlay url={overlayUrl} />}
            </div>
          )
        )}
      </div>
      {(info || overlayUrl) && (
        <div className="flex items-center justify-center gap-2 h-9 shrink-0 px-3 text-[11.5px] text-fg-3 num" style={{ borderTop: '1px solid var(--line)' }}>
          <span className="truncate">{info}</span>
          {overlayUrl && (
            <button
              type="button"
              className={`btn !h-6 !px-2 text-[11.5px] ${overlay ? 'text-accent' : ''}`}
              onClick={() => setOverlay(o => !o)}
              title="The text and stickers of this Snapchat memory (its -overlay file)"
            >
              <Layers className="w-3.5 h-3.5" /> Snapchat overlay
            </button>
          )}
        </div>
      )}
    </div>
  );
};
