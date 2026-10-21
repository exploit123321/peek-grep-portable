import React, { useLayoutEffect, useRef, useState } from 'react';

// A pill slides to the active option. A second, dark copy of the labels is clipped to the
// pill, so letters invert while the pill passes over them (matrix ref R05 Exclusion Tabs).
// A soft light follows the pointer across the bar (matrix ref R38 Flashlight Tabs).

export interface SegmentOption<T extends string> {
  id: T;
  label: string;
  icon?: React.ComponentType<{ className?: string }>;
  hint?: string;
}

interface SegmentedControlProps<T extends string> {
  options: SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  size?: 'sm' | 'md';
  className?: string;
}

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  size = 'md',
  className,
}: SegmentedControlProps<T>) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const [rect, setRect] = useState({ left: 0, width: 0, ready: false });
  const [glow, setGlow] = useState<{ x: number; y: number; on: boolean }>({ x: 0, y: 0, on: false });

  const activeIndex = Math.max(0, options.findIndex(o => o.id === value));

  useLayoutEffect(() => {
    const measure = () => {
      const el = itemRefs.current[activeIndex];
      const wrap = wrapRef.current;
      if (!el || !wrap) return;
      setRect({ left: el.offsetLeft, width: el.offsetWidth, ready: true });
    };
    measure();
    const ro = new ResizeObserver(measure);
    if (wrapRef.current) ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, [activeIndex, options.length]);

  const h = size === 'sm' ? 'h-7 text-[12px]' : 'h-8 text-[12.5px]';
  const pad = size === 'sm' ? 'px-2.5' : 'px-3';
  const wrapWidth = wrapRef.current?.offsetWidth ?? 0;
  const clipRight = Math.max(0, wrapWidth - rect.left - rect.width);
  const transition = rect.ready ? '320ms var(--ease-spring)' : '0ms';

  const renderLabels = (dark: boolean) =>
    options.map((opt, i) => {
      const Icon = opt.icon;
      return (
        <button
          key={opt.id}
          ref={dark ? undefined : el => (itemRefs.current[i] = el)}
          type="button"
          tabIndex={dark ? -1 : 0}
          aria-hidden={dark || undefined}
          aria-pressed={!dark ? opt.id === value : undefined}
          title={opt.hint}
          onClick={() => onChange(opt.id)}
          className={`relative z-[1] inline-flex items-center gap-1.5 ${h} ${pad} rounded-full font-medium whitespace-nowrap transition-colors duration-150 ${
            dark ? 'text-[#0d0e14]' : 'text-fg-3 hover:text-fg'
          }`}
        >
          {Icon && <Icon className="w-3.5 h-3.5" />}
          {opt.label}
        </button>
      );
    });

  return (
    <div
      ref={wrapRef}
      className={`relative inline-flex items-center p-0.5 rounded-full select-none ${className ?? ''}`}
      style={{ background: 'var(--bg-elev)', boxShadow: 'inset 0 0 0 1px var(--line)' }}
      onPointerMove={e => {
        const box = e.currentTarget.getBoundingClientRect();
        setGlow({ x: e.clientX - box.left, y: e.clientY - box.top, on: true });
      }}
      onPointerLeave={() => setGlow(g => ({ ...g, on: false }))}
    >
      {/* Flashlight */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 rounded-full transition-opacity duration-300"
        style={{
          opacity: glow.on ? 1 : 0,
          background: `radial-gradient(70px circle at ${glow.x}px ${glow.y}px, rgba(255,255,255,0.09), transparent 70%)`,
        }}
      />
      {/* Pill */}
      <span
        aria-hidden
        className="absolute top-0.5 bottom-0.5 rounded-full"
        style={{
          left: rect.left,
          width: rect.width,
          background: 'linear-gradient(180deg, #f4f5fb, #d9dcea)',
          boxShadow: '0 1px 0 rgba(255,255,255,0.6) inset, 0 4px 14px -6px rgba(124,156,255,0.55)',
          transition: `left ${transition}, width ${transition}`,
          opacity: rect.ready ? 1 : 0,
        }}
      />
      {/* Light labels (interactive) */}
      <div className="relative z-[1] inline-flex items-center">{renderLabels(false)}</div>
      {/* Pill face with dark labels: it covers the light labels only where the pill is */}
      <div
        aria-hidden
        className="absolute inset-0 p-0.5 inline-flex items-center pointer-events-none z-[2]"
        style={{
          background: 'linear-gradient(180deg, #f4f5fb, #d9dcea)',
          clipPath: `inset(2px ${clipRight}px 2px ${rect.left}px round 999px)`,
          transition: `clip-path ${transition}`,
          opacity: rect.ready ? 1 : 0,
        }}
      >
        {renderLabels(true)}
      </div>
    </div>
  );
}
