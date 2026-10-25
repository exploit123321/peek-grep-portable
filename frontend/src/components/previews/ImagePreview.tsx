import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Layers, Minus, Plus, RotateCcw } from 'lucide-react';
import { ImageMeta } from '../../api';
import { CHECKERBOARD, metaLine, SnapOverlay, useFitBox } from './MediaFrame';

const MIN_ZOOM = 0.25;
const MAX_ZOOM = 8;
const clamp = (z: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z));

/** A zoom step from Quick Look (its keys): +1 in, -1 out, 0 back to fit; n changes each time. */
export interface ZoomCommand {
  dir: 1 | -1 | 0;
  n: number;
}

interface ImagePreviewProps {
  rawUrl: string;
  /** A JPEG made for the preview (HEIC and other photos the WebView cannot show) */
  displayUrl?: string | null;
  filename: string;
  imageMeta?: ImageMeta;
  /** Snapchat memory: its text and stickers */
  overlayUrl?: string | null;
  zoomCommand?: ZoomCommand | null;
}

// The mouse wheel zooms toward the pointer, dragging moves a zoomed photo, a double click
// switches between the whole photo and 2.5 times.
export const ImagePreview: React.FC<ImagePreviewProps> = ({ rawUrl, displayUrl, filename, imageMeta, overlayUrl, zoomCommand }) => {
  const [view, setView] = useState({ zoom: 1, x: 0, y: 0 });
  const viewRef = useRef(view);
  viewRef.current = view;
  const [overlay, setOverlay] = useState(true);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const drag = useRef<{ x: number; y: number; ox: number; oy: number; id: number } | null>(null);
  useEffect(() => {
    setNatural(null);
    setView({ zoom: 1, x: 0, y: 0 });
  }, [rawUrl]);
  const size = natural ?? (imageMeta ? { w: imageMeta.width, h: imageMeta.height } : null);
  const { ref, box } = useFitBox(size ? size.w / size.h : null);
  // Never larger than the photo itself at 100% (small images stay sharp)
  const shown = box && size && box.width > size.w ? { width: size.w, height: size.h } : box;

  /** Zoom to z keeping the point under (sx, sy) (relative to the middle of the view) in place. */
  const zoomAt = (z: number, sx = 0, sy = 0) => {
    const v = viewRef.current;
    const zoom = clamp(z);
    if (zoom <= 1) {
      setView({ zoom, x: 0, y: 0 });
      return;
    }
    const k = zoom / v.zoom;
    setView({ zoom, x: sx - (sx - v.x) * k, y: sy - (sy - v.y) * k });
  };
  const fromCenter = (e: { clientX: number; clientY: number }) => {
    const r = ref.current!.getBoundingClientRect();
    return [e.clientX - (r.left + r.width / 2), e.clientY - (r.top + r.height / 2)] as const;
  };

  // Native listener: React's wheel events cannot stop the page from scrolling or zooming
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const [sx, sy] = fromCenter(e);
      zoomAt(viewRef.current.zoom * Math.pow(1.0015, -e.deltaY), sx, sy);
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!zoomCommand) return;
    if (zoomCommand.dir === 0) setView({ zoom: 1, x: 0, y: 0 });
    else zoomAt(viewRef.current.zoom * (zoomCommand.dir > 0 ? 1.25 : 0.8));
  }, [zoomCommand]); // eslint-disable-line react-hooks/exhaustive-deps

  const zoomed = view.zoom > 1;
  return (
    <div className="relative flex flex-col h-full">
      <div
        ref={ref}
        className="flex-1 overflow-hidden flex items-center justify-center select-none"
        style={{ ...CHECKERBOARD, cursor: drag.current ? 'grabbing' : zoomed ? 'grab' : 'zoom-in' }}
        onDoubleClick={e => {
          const [sx, sy] = fromCenter(e);
          if (zoomed) setView({ zoom: 1, x: 0, y: 0 });
          else zoomAt(2.5, sx, sy);
        }}
        onPointerDown={e => {
          if (e.button !== 0 || !zoomed) return;
          e.currentTarget.setPointerCapture(e.pointerId);
          drag.current = { x: e.clientX, y: e.clientY, ox: view.x, oy: view.y, id: e.pointerId };
        }}
        onPointerMove={e => {
          const d = drag.current;
          if (!d || d.id !== e.pointerId) return;
          setView(v => ({ ...v, x: d.ox + e.clientX - d.x, y: d.oy + e.clientY - d.y }));
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
      >
        <div
          className="relative fade-up"
          style={{
            ...(shown ? { width: shown.width, height: shown.height } : { maxWidth: '100%', maxHeight: '100%' }),
            transform: `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`,
            transition: drag.current ? 'none' : 'transform 120ms var(--ease-out)',
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
        <button type="button" className="icon-btn" onClick={() => zoomAt(view.zoom * 0.8)} title="Zoom out (mouse wheel)">
          <Minus className="w-3.5 h-3.5" />
        </button>
        <span className="w-12 text-center num text-[11.5px] text-fg-2">{Math.round(view.zoom * 100)}%</span>
        <button type="button" className="icon-btn" onClick={() => zoomAt(view.zoom * 1.25)} title="Zoom in (mouse wheel, double click)">
          <Plus className="w-3.5 h-3.5" />
        </button>
        <button type="button" className="icon-btn" onClick={() => setView({ zoom: 1, x: 0, y: 0 })} title="The whole photo">
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
