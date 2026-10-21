import React from 'react';

// The box fills and the check mark draws itself (matrix ref R28 Animated Checkboxes).

interface AnimatedCheckboxProps {
  checked: boolean;
  size?: number;
}

export const AnimatedCheckbox: React.FC<AnimatedCheckboxProps> = ({ checked, size = 16 }) => (
  <span
    className="check-box inline-flex items-center justify-center shrink-0 rounded-[5px]"
    data-checked={checked}
    style={{
      width: size,
      height: size,
      background: checked ? 'var(--accent-strong)' : 'transparent',
      boxShadow: checked ? 'inset 0 0 0 1px rgba(255,255,255,0.18)' : 'inset 0 0 0 1.5px var(--text-3)',
      transform: checked ? 'scale(1)' : 'scale(0.94)',
    }}
    aria-hidden
  >
    <svg width={size - 4} height={size - 4} viewBox="0 0 12 12" fill="none">
      <path d="M2.5 6.3 5 8.6 9.6 3.6" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  </span>
);
