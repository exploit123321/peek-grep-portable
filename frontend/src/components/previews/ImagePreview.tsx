import React, { useState } from 'react';
import { Minus, Plus, RotateCcw } from 'lucide-react';

interface ImageMeta {
  width: number;
  height: number;
  format: string;
  mode: string;
  aspect_ratio: string;
}

export const ImagePreview: React.FC<{ rawUrl: string; filename: string; imageMeta?: ImageMeta }> = ({ rawUrl, filename, imageMeta }) => {
  const [zoom, setZoom] = useState(1);
  return (
    <div className="relative flex flex-col h-full">
      <div
        className="flex-1 overflow-auto flex items-center justify-center p-8"
        style={{
          backgroundColor: '#0d0d11',
          backgroundImage:
            'linear-gradient(45deg, #15151b 25%, transparent 25%), linear-gradient(-45deg, #15151b 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #15151b 75%), linear-gradient(-45deg, transparent 75%, #15151b 75%)',
          backgroundSize: '18px 18px',
          backgroundPosition: '0 0, 0 9px, 9px -9px, -9px 0px',
        }}
      >
        <img
          src={rawUrl}
          alt={filename}
          draggable={false}
          className="max-h-full max-w-full object-contain rounded-md fade-up"
          style={{
            transform: `scale(${zoom})`,
            transition: 'transform 260ms var(--ease-out)',
            boxShadow: '0 20px 60px -20px rgba(0,0,0,0.8)',
            animationDuration: '420ms',
          }}
        />
      </div>
      <div
        className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-1 h-9 px-1.5 rounded-full"
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
        {imageMeta && (
          <span className="pl-2 pr-2.5 text-[11.5px] text-fg-3 num" style={{ borderLeft: '1px solid var(--line)' }}>
            {imageMeta.width}×{imageMeta.height} · {imageMeta.format}
          </span>
        )}
      </div>
    </div>
  );
};
