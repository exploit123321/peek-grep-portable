import React from 'react';

// Numbered steps joined by a line that fills as you advance; a finished step gets a
// drawn check mark (matrix ref Y20, four-step stepper with check circles).

interface StepperProps {
  steps: string[];
  current: number; // index of the active step
  done: number;    // number of finished steps
}

export const Stepper: React.FC<StepperProps> = ({ steps, current, done }) => (
  <div className="flex items-start w-full max-w-[460px] mx-auto">
    {steps.map((label, i) => {
      const finished = i < done;
      const active = i === current && !finished;
      return (
        <React.Fragment key={label}>
          <div className="flex flex-col items-center gap-2 w-[84px] shrink-0">
            <span
              className={`relative flex items-center justify-center w-7 h-7 rounded-full text-[12px] font-semibold transition-all duration-300 ${active ? 'pulse-ring' : ''}`}
              style={{
                background: finished ? 'var(--ok)' : active ? 'var(--accent-soft)' : 'var(--surface-2)',
                color: finished ? '#08140e' : active ? 'var(--accent)' : 'var(--text-3)',
                boxShadow: finished ? 'none' : active ? 'inset 0 0 0 1.5px var(--accent)' : 'inset 0 0 0 1px var(--line-strong)',
              }}
            >
              {finished ? (
                <svg className="step-check" key={`c${i}`} width="13" height="13" viewBox="0 0 12 12" fill="none">
                  <path d="M2.4 6.3 5 8.7 9.7 3.6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              ) : (
                i + 1
              )}
            </span>
            <span className={`text-[11.5px] text-center leading-tight transition-colors duration-300 ${finished || active ? 'text-fg' : 'text-fg-3'}`}>
              {label}
            </span>
          </div>
          {i < steps.length - 1 && (
            <div className="relative flex-1 h-[2px] mt-[13px] rounded-full overflow-hidden" style={{ background: 'var(--line-strong)' }}>
              <div
                className="absolute inset-0 origin-left rounded-full"
                style={{
                  background: 'linear-gradient(90deg, var(--ok), var(--accent))',
                  transform: `scaleX(${i < done ? 1 : 0})`,
                  transition: 'transform 620ms var(--ease-out)',
                }}
              />
            </div>
          )}
        </React.Fragment>
      );
    })}
  </div>
);
