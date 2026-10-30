import { useEffect, useRef } from 'react';
import { MODES } from '../../constants';
import { useWorkspace } from '../../context/WorkspaceContext';
import MessageBubble from './MessageBubble';

export default function MessageList() {
  const { messages, mode, meta } = useWorkspace();
  const endRef = useRef(null);
  const current = MODES.find((m) => m.id === mode);

  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }); }, [messages]);

  return (
    <div className="min-h-0 flex-1 select-text space-y-4 overflow-y-auto p-4 text-xs leading-relaxed">
      {meta.llmProvider === 'mock' && (
        <div role="status" className="rounded-lg border border-amber-700 bg-amber-950/40 p-2.5 text-amber-300">
          <p className="font-semibold">Demo mode: no AI model connected</p>
          <p className="mt-0.5 text-[11px] opacity-90">
            Replies are placeholders. In <code>backend/.env</code> set <code>LLM_PROVIDER=google</code> and your
            <code> LLM_API_KEY</code>, then restart the backend. The Run button works without it.
          </p>
        </div>
      )}
      {messages.length === 0 && (
        <div className="rounded-lg border border-gray-800 bg-ds-card p-3">
          <p className="mb-1 font-bold text-cyan-400">{current.icon} {current.label}</p>
          <p className="text-gray-400">{current.hint}</p>
          <p className="mt-2 text-gray-500">Drag any divider to resize the panels. Double-click it to reset.</p>
        </div>
      )}
      {messages.map((m) => <MessageBubble key={m.id} message={m} />)}
      <div ref={endRef} />
    </div>
  );
}
