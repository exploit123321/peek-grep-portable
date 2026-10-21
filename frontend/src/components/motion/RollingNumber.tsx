import React from 'react';

// Digits roll on a vertical strip when the value changes (matrix ref R29 Countdown).

interface RollingNumberProps {
  value: number;
  className?: string;
}

const DIGITS = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'];

export const RollingNumber: React.FC<RollingNumberProps> = ({ value, className }) => {
  const text = Math.max(0, Math.round(value)).toLocaleString('en-US');
  const chars = text.split('');
  return (
    <span className={`inline-flex tabular-nums ${className ?? ''}`} aria-label={text}>
      {chars.map((ch, i) => {
        // Key from the right so that units stay in place when the number grows
        const key = chars.length - i;
        if (!/\d/.test(ch)) {
          return (
            <span key={`s${key}`} aria-hidden>
              {ch}
            </span>
          );
        }
        const d = Number(ch);
        return (
          <span key={`d${key}`} className="roll-digit" aria-hidden>
            <span className="roll-strip" style={{ transform: `translateY(-${d}em)` }}>
              {DIGITS.map(n => (
                <span key={n}>{n}</span>
              ))}
            </span>
          </span>
        );
      })}
    </span>
  );
};
