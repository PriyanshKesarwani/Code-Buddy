import { useEffect, useRef } from 'react';
import { useWorkspace } from '../../context/WorkspaceContext';

const TONES = {
  text: 'text-gray-300',
  info: 'text-cyan-400',
  ok: 'text-emerald-300 font-semibold',
  err: 'text-rose-400 font-semibold',
  warn: 'text-amber-400',
  muted: 'text-gray-500',
};

export default function OutputTab() {
  const { outputLogs, stdin, setStdin, running } = useWorkspace();
  const endRef = useRef(null);
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }); }, [outputLogs]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
    <div className="min-h-0 flex-1 select-text space-y-1 overflow-y-auto p-3 text-xs">
      {outputLogs.length === 0 && (
        <div className="text-gray-500">Nothing has run yet. Press Run in the editor (Ctrl+Enter) to execute your code.</div>
      )}
      {outputLogs.map((l) => (
        <div key={l.id} className={`whitespace-pre-wrap ${TONES[l.tone] || TONES.text}`}>{l.text}</div>
      ))}
      {running && <div className="animate-pulse text-gray-500">Running…</div>}
      <div ref={endRef} />
    </div>
    <div className="flex flex-none items-start gap-2 border-t border-gray-900 bg-[#070c18] px-3 py-1.5 text-xs">
      <label htmlFor="stdin-input" className="mt-0.5 font-bold text-cyan-400">stdin</label>
      <textarea
        id="stdin-input"
        rows={1}
        value={stdin}
        onChange={(e) => setStdin(e.target.value)}
        spellCheck={false}
        placeholder="Input for programs that read it (input(), scanf, Scanner…), one value per line"
        className="max-h-20 min-h-5 flex-1 resize-y bg-transparent font-mono text-xs text-gray-100 outline-none placeholder:text-gray-600"
      />
    </div>
    </div>
  );
}
