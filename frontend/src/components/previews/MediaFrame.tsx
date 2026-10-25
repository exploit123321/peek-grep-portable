import React, { useLayoutEffect, useRef, useState } from 'react';

// The box that a photo or video takes in the preview: as large as fits, in its own proportions.
// Sized here (not by the browser) so a Snapchat overlay can lie exactly on top.

export function useFitBox(aspect: number | null, padding = 32) {
  const ref = useRef<HTMLDivElement>(null);
  const [area, setArea] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setArea({ width: el.clientWidth, height: el.clientHeight });
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    measure();
    return () => ro.disconnect();
  }, []);
  const maxW = Math.max(0, area.width - padding * 2);
  const maxH = Math.max(0, area.height - padding * 2);
  let box: { width: number; height: number } | null = null;
  if (aspect && maxW && maxH) {
    box = maxW / maxH > aspect ? { width: maxH * aspect, height: maxH } : { width: maxW, height: maxW / aspect };
  }
  return { ref, box };
}

/** The overlay of a Snapchat memory (text, stickers, drawings), over the whole photo or video. */
export const SnapOverlay: React.FC<{ url: string }> = ({ url }) => (
  <img src={url} alt="" draggable={false} className="absolute inset-0 w-full h-full object-fill pointer-events-none select-none" />
);

export const CHECKERBOARD: React.CSSProperties = {
  backgroundColor: '#0d0d11',
  backgroundImage:
    'linear-gradient(45deg, #15151b 25%, transparent 25%), linear-gradient(-45deg, #15151b 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #15151b 75%), linear-gradient(-45deg, transparent 75%, #15151b 75%)',
  backgroundSize: '18px 18px',
  backgroundPosition: '0 0, 0 9px, 9px -9px, -9px 0px',
};

/** "Apple iPhone 15 Pro · 2024-05-01 14:03" and the like, without the empty parts. */
export const metaLine = (parts: (string | null | undefined | false)[]) => parts.filter(Boolean).join(' · ');
