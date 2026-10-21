import React, { useEffect, useRef, useState } from 'react';

// Hold the button (mouse or Enter/Space) to confirm a destructive action (matrix ref R12 Hold Enter to confirm).

interface HoldButtonProps {
  onConfirm: () => void;
  children: React.ReactNode;
  holdMs?: number;
  tone?: 'danger' | 'accent';
  className?: string;
  title?: string;
  disabled?: boolean;
  /** Called when the button is released before the hold completes */
  onShortPress?: () => void;
}

export const HoldButton: React.FC<HoldButtonProps> = ({
  onConfirm,
  children,
  holdMs = 900,
  tone = 'danger',
  className,
  title,
  disabled,
  onShortPress,
}) => {
  const [holding, setHolding] = useState(false);
  const [done, setDone] = useState(false);
  const timer = useRef<number | null>(null);

  const stop = (released = false) => {
    if (timer.current) {
      window.clearTimeout(timer.current);
      if (released) onShortPress?.();
    }
    timer.current = null;
    setHolding(false);
  };

  const start = () => {
    if (disabled || timer.current) return;
    setHolding(true);
    timer.current = window.setTimeout(() => {
      timer.current = null;
      setHolding(false);
      setDone(true);
      window.setTimeout(() => setDone(false), 500);
      onConfirm();
    }, holdMs);
  };

  useEffect(() => () => stop(), []);

  const color = tone === 'danger' ? 'var(--danger)' : 'var(--accent)';
  const fillBg = tone === 'danger' ? 'rgba(240,97,109,0.22)' : 'var(--accent-soft)';

  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      className={`relative overflow-hidden btn whitespace-nowrap shrink-0 ${className ?? ''}`}
      style={{ color: holding || done ? color : undefined }}
      onPointerDown={e => {
        e.currentTarget.setPointerCapture(e.pointerId);
        start();
      }}
      onPointerUp={() => stop(true)}
      onPointerCancel={() => stop()}
      onPointerLeave={() => stop()}
      onKeyDown={e => {
        if ((e.key === 'Enter' || e.key === ' ') && !e.repeat) {
          e.preventDefault();
          start();
        }
      }}
      onKeyUp={e => {
        if (e.key === 'Enter' || e.key === ' ') stop(true);
      }}
    >
      <span
        aria-hidden
        className="absolute inset-0 origin-left"
        style={{
          background: fillBg,
          transform: `scaleX(${holding || done ? 1 : 0})`,
          transition: holding ? `transform ${holdMs}ms linear` : 'transform 220ms var(--ease-out)',
        }}
      />
      <span className="relative inline-flex items-center gap-1.5">{children}</span>
    </button>
  );
};
