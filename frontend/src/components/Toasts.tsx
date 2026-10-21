import React, { createContext, useCallback, useContext, useRef, useState } from 'react';
import { AlertCircle, Check, Info } from 'lucide-react';

// Small status cards at the bottom of the window (matrix row R2: popovers and toasts).

type Tone = 'ok' | 'info' | 'error';

interface Toast {
  id: number;
  text: string;
  tone: Tone;
  leaving: boolean;
}

const ToastContext = createContext<(text: string, tone?: Tone) => void>(() => {});

export const useToast = () => useContext(ToastContext);

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const push = useCallback((text: string, tone: Tone = 'ok') => {
    const id = nextId.current++;
    setToasts(list => [...list.slice(-2), { id, text, tone, leaving: false }]);
    window.setTimeout(() => setToasts(list => list.map(t => (t.id === id ? { ...t, leaving: true } : t))), 2200);
    window.setTimeout(() => setToasts(list => list.filter(t => t.id !== id)), 2500);
  }, []);

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-11 left-0 right-0 z-[80] flex flex-col items-center gap-2">
        {toasts.map(t => {
          const Icon = t.tone === 'error' ? AlertCircle : t.tone === 'info' ? Info : Check;
          const color = t.tone === 'error' ? 'var(--danger)' : t.tone === 'info' ? 'var(--accent)' : 'var(--ok)';
          return (
            <div
              key={t.id}
              className="flex items-center gap-2 h-9 pl-2.5 pr-3.5 rounded-full text-[12.5px] text-fg"
              style={{
                background: 'rgba(28,28,36,0.92)',
                backdropFilter: 'blur(12px)',
                boxShadow: 'inset 0 0 0 1px var(--line-strong), 0 12px 30px -10px rgba(0,0,0,0.7)',
                animation: t.leaving ? 'none' : 'fade-up 380ms var(--ease-out) both',
                opacity: t.leaving ? 0 : 1,
                transform: t.leaving ? 'translateY(6px) scale(0.98)' : undefined,
                transition: 'opacity 260ms var(--ease-out), transform 260ms var(--ease-out)',
              }}
            >
              <span
                className="flex items-center justify-center w-5 h-5 rounded-full pop-in"
                style={{ background: `color-mix(in srgb, ${color} 20%, transparent)`, color }}
              >
                <Icon className="w-3 h-3" />
              </span>
              {t.text}
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
};
