import React, { useEffect, useRef, useState } from 'react';
import { prefersReducedMotion } from './useReducedMotion';

// Text decodes from random glyphs, left to right (matrix ref R24 Cryptic List).

const GLYPHS = '!<>-_\\/[]{}=+*^?#%&$';

interface CrypticTextProps {
  text: string;
  duration?: number;
  className?: string;
}

export const CrypticText: React.FC<CrypticTextProps> = ({ text, duration = 700, className }) => {
  const [shown, setShown] = useState(text);
  const frame = useRef(0);

  useEffect(() => {
    if (prefersReducedMotion()) {
      setShown(text);
      return;
    }
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const settled = Math.floor(t * text.length);
      let out = '';
      for (let i = 0; i < text.length; i++) {
        const ch = text[i];
        if (i < settled || ch === ' ') out += ch;
        else out += GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
      }
      setShown(out);
      if (t < 1) frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame.current);
  }, [text, duration]);

  return (
    <span className={className} aria-label={text}>
      {shown}
    </span>
  );
};
