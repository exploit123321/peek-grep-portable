import React, { useEffect, useState } from 'react';
import { Layers, Minus, Plus, RotateCcw } from 'lucide-react';
import { ImageMeta } from '../../api';
import { CHECKERBOARD, metaLine, SnapOverlay, useFitBox } from './MediaFrame';

interface ImagePreviewProps {
  rawUrl: string;
  /** A JPEG made for the preview (HEIC and other photos the WebView cannot show) */
  displayUrl?: string | null;
  filename: string;
  imageMeta?: ImageMeta;
  /** Snapchat memory: its text and stickers */
  overlayUrl?: string | null;
}

export const ImagePreview: React.FC<ImagePreviewProps> = ({ rawUrl, displayUrl, filename, imageMeta, overlayUrl }) => {
  const [zoom, setZoom] = useState(1);
  const [overlay, setOverlay] = useState(true);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  useEffect(() => setNatural(null), [rawUrl]);
  const size = natural ?? (imageMeta ? { w: imageMeta.width, h: imageMeta.height } : null);
  const { ref, box } = useFitBox(size ? size.w / size.h : null);
  // Never larger than the photo itself (small images stay sharp)
  const shown = box && size && box.width > size.w ? { width: size.w, height: size.h } : box;

  return (
    <div className="relative flex flex-col h-full">
      <div ref={ref} className="flex-1 overflow-auto flex items-center justify-center" style={CHECKERBOARD}>
        <div
          className="relative fade-up"
          style={{
            ...(shown ? { width: shown.width, height: shown.height } : { maxWidth: '100%', maxHeight: '100%' }),
            transform: `scale(${zoom})`,
            transition: 'transform 260ms var(--ease-out)',
            animationDuration: '420ms',
          }}
        >
          <img
            src={displayUrl || rawUrl}
            alt={filename}
            draggable={false}
            onLoad={e => {
              const img = e.currentTarget;
              if (img.naturalWidth && img.naturalHeight) setNatural({ w: img.naturalWidth, h: img.naturalHeight });
            }}
            className="block w-full h-full object-contain rounded-md"
            style={{ boxShadow: '0 20px 60px -20px rgba(0,0,0,0.8)' }}
          />
          {overlayUrl && overlay && <SnapOverlay url={overlayUrl} />}
        </div>
      </div>
      <div
        className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-1 h-9 px-1.5 rounded-full max-w-[calc(100%-24px)]"
        style={{ background: 'rgba(24,24,31,0.9)', backdropFilter: 'blur(10px)', boxShadow: 'inset 0 0 0 1px var(--line-strong)' }}
      >
        <button type="button" className="icon-btn" onClick={() => setZoom(z => Math.max(0.25, z - 0.25))} title="Zoom out">
          <Minus className="w-3.5 h-3.5" />
        </button>
        <span className="w-12 text-center num text-[11.5px] text-fg-2">{Math.round(zoom * 100)}%</span>
        <button type="button" className="icon-btn" onClick={() => setZoom(z => Math.min(4, z + 0.25))} title="Zoom in">
          <Plus className="w-3.5 h-3.5" />
        </button>
        <button type="button" className="icon-btn" onClick={() => setZoom(1)} title="Reset">
          <RotateCcw className="w-3.5 h-3.5" />
        </button>
        {overlayUrl && (
          <button
            type="button"
            className={`icon-btn ${overlay ? 'text-accent' : ''}`}
            onClick={() => setOverlay(o => !o)}
            title="Snapchat overlay: the text and stickers of this memory (its -overlay file)"
          >
            <Layers className="w-3.5 h-3.5" />
          </button>
        )}
        {imageMeta && (
          <span className="pl-2 pr-2.5 text-[11.5px] text-fg-3 num truncate" style={{ borderLeft: '1px solid var(--line)' }}>
            {metaLine([`${imageMeta.width}×${imageMeta.height}`, imageMeta.format, imageMeta.camera, imageMeta.taken])}
          </span>
        )}
      </div>
    </div>
  );
};
