import React, { useEffect, useState } from 'react';
import { ArrowRight, ShieldCheck } from 'lucide-react';
import { api, FolderDetails, IndexerStatus } from '../api';
import { CrypticText } from './motion/CrypticText';
import { FolderManager } from './FolderManager';
import { IndexingRows } from './IndexingRows';
import { Stepper } from './Stepper';
import { useToast } from './Toasts';

// First run: choose working folders -> build the index -> search
// (matrix refs M2 setup then reveal, D2/Y20 stepper, E19 working rows).

interface OnboardingProps {
  details: FolderDetails | null;
  status: IndexerStatus | null;
  startAtIndexing: boolean;
  onSaved: () => void;
  onFinish: () => void;
}

export const Onboarding: React.FC<OnboardingProps> = ({ details, status, startAtIndexing, onSaved, onFinish }) => {
  const toast = useToast();
  const [step, setStep] = useState(startAtIndexing ? 1 : 0);
  const [draft, setDraft] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (details?.setup_done && details.folders.length && !draft.length) {
      setDraft(details.folders.map(f => f.path));
    }
  }, [details]); // eslint-disable-line react-hooks/exhaustive-deps

  const ready = status?.phase === 'ready';
  const start = async () => {
    setSaving(true);
    try {
      await api.saveFolders(draft);
      onSaved();
      setStep(1);
    } catch (e) {
      toast((e as Error).message, 'error');
    } finally {
      setSaving(false);
    }
  };

  const titles = ['Choose your working folders', 'Building your index'];

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="flex flex-col gap-5 w-full max-w-[600px] mx-auto px-6 pt-3 pb-6">
          <Stepper steps={['Choose folders', 'Build index', 'Search']} current={step} done={step + (step === 1 && ready ? 1 : 0)} />

          <div className="flex flex-col gap-1.5 text-center" key={step}>
            <h1 className="font-display text-[22px] font-semibold tracking-[-0.02em] text-fg">
              <CrypticText text={titles[step]} />
            </h1>
            <p className="text-[13px] leading-relaxed text-fg-2 max-w-[460px] mx-auto fade-up" style={{ ['--d' as string]: '120ms' }}>
              {step === 0
                ? 'Peek & Grep reads only the folders that you allow. Nothing is scanned until you start.'
                : 'Names are ready in seconds. Text inside documents follows in the background. You can search now.'}
            </p>
          </div>

          {step === 0 ? (
            <>
              <FolderManager
                mode="draft"
                selected={draft}
                suggestions={details?.suggestions ?? []}
                canPick={details?.can_pick ?? false}
                onAdd={paths =>
                  setDraft(d => {
                    const keep = d.filter(x => !paths.some(p => x.toLowerCase().startsWith(p.toLowerCase().replace(/\\?$/, '\\'))));
                    return [...keep, ...paths.filter(p => !keep.some(k => k.toLowerCase() === p.toLowerCase()))];
                  })
                }
                onRemove={path => setDraft(d => d.filter(x => x.toLowerCase() !== path.toLowerCase()))}
              />
              <div className="flex items-start gap-2.5 px-3.5 py-3 rounded-xl text-[12px] leading-relaxed text-fg-2" style={{ background: 'var(--bg-elev)', boxShadow: 'inset 0 0 0 1px var(--line)' }}>
                <ShieldCheck className="w-4 h-4 mt-0.5 shrink-0 text-ok" />
                <span>
                  Files outside these folders are never read, previewed, or opened. The index stays in the
                  <span className="font-mono text-fg"> data </span>
                  folder next to the app. You can change the list at any time.
                </span>
              </div>
            </>
          ) : (
            <IndexingRows status={status} />
          )}
        </div>
      </div>

      {/* Actions stay visible at the bottom of the window */}
      <div className="shrink-0" style={{ borderTop: '1px solid var(--line)', background: 'rgba(11,11,14,0.85)' }}>
        <div className="flex items-center justify-between w-full max-w-[600px] mx-auto h-14 px-6">
          {step === 0 ? (
            <>
              <span className="text-[12.5px] text-fg-3">
                {draft.length === 0 ? 'Select at least one folder' : `${draft.length} folder${draft.length > 1 ? 's' : ''} selected`}
              </span>
              <button type="button" className="btn-primary h-9 px-4" disabled={!draft.length || saving} onClick={start}>
                {saving ? 'Saving…' : 'Start indexing'}
                <ArrowRight className="w-4 h-4" />
              </button>
            </>
          ) : (
            <>
              <button type="button" className="btn" onClick={() => setStep(0)}>
                Change folders
              </button>
              <button type="button" className={`btn-primary h-9 px-4 ${ready ? 'pulse-ring' : ''}`} onClick={onFinish}>
                {ready ? 'Start searching' : 'Search now'}
                <ArrowRight className="w-4 h-4" />
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
