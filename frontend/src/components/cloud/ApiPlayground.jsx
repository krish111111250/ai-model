import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ChevronDown,
  Code2,
  Copy,
  CornerDownLeft,
  FileText,
  Loader2,
  Send,
  Sparkles,
} from 'lucide-react';
import { toast } from 'sonner';
import JsonBlock from '@/components/ui/JsonBlock';
import { api } from '@/services/api';

/**
 * Ask questions against the indexed documents, from inside the dashboard.
 *
 * This is the same path a customer's own integration takes - the local
 * gateway retrieves, the engine generates - so what it answers here is what
 * their API call will answer. The request body is shown alongside for that
 * reason: the point of a playground is to learn the call, not just to chat.
 */
const ApiPlayground = ({ documents = [] }) => {
  const bottom = useRef(null);
  const input = useRef(null);

  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState('');
  const [sending, setSending] = useState(false);
  const [documentId, setDocumentId] = useState('');
  const [showRequest, setShowRequest] = useState(false);

  // A session of its own, so trying things here does not land in the
  // conversation list of the chat app.
  const sessionId = useMemo(() => `playground_${Date.now()}`, []);

  // Shown in the request block, so it matches wherever the gateway actually is.
  const gatewayUrl =
    import.meta.env.VITE_KRISH_GATEWAY_URL || 'http://localhost:8001';

  // Keep a valid selection: the gateway cannot answer in single-document
  // mode without one, and a stale id would point at a deleted document.
  useEffect(() => {
    setDocumentId((current) => {
      if (current && documents.some((doc) => doc.document_id === current)) {
        return current;
      }

      return documents[0]?.document_id || '';
    });
  }, [documents]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, sending]);

  const requestBody = useMemo(
    () =>
      JSON.stringify(
        {
          query: question.trim() || 'your question',
          session_id: sessionId,
          document_mode: 'single',
          document_id: documentId || 'doc_...',
        },
        null,
        2
      ),
    [question, sessionId, documentId]
  );

  const send = async () => {
    const query = question.trim();

    if (!query || sending || !documentId) return;

    setMessages((previous) => [...previous, { role: 'user', content: query }]);
    setQuestion('');
    setSending(true);

    try {
      const response = await api.sendChatMessage({
        query,
        sessionId,
        documentId,
        documentMode: 'single',
      });

      setMessages((previous) => [
        ...previous,
        {
          role: 'assistant',
          content: response.answer,
          // Only a grounded answer carries citations; a refusal deliberately
          // has none, and pages beside "not in the document" would say the
          // opposite of what happened.
          grounded: response.grounded,
          labels: response.source_labels || [],
          retrievers: response.retrievers || [],
          chunks: response.chunks_used,
        },
      ]);
    } catch (problem) {
      setMessages((previous) => [
        ...previous,
        {
          role: 'assistant',
          failed: true,
          content: problem.message || 'The request failed.',
        },
      ]);
    } finally {
      setSending(false);
      input.current?.focus();
    }
  };

  const copyAnswer = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success('Answer copied');
    } catch {
      toast.error('Could not copy', {
        description: 'Select the text and copy it manually.',
      });
    }
  };

  const handleKeyDown = (event) => {
    // Enter sends, Shift+Enter breaks the line - what every chat input does.
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  };

  const selected = documents.find((doc) => doc.document_id === documentId);

  return (
    <section>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold tracking-tight">Playground</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Ask a question the way your integration would. Same retrieval, same
            answer.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowRequest((shown) => !shown)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-secondary px-3 py-2 text-xs font-medium text-secondary-foreground transition-colors hover:bg-accent"
          >
            <Code2 className="size-3.5" />
            {showRequest ? 'Hide request' : 'Show request'}
          </button>

          <div className="relative flex items-center gap-2 rounded-lg border border-border bg-secondary px-3 py-2 text-sm text-secondary-foreground">
            <FileText className="size-4 shrink-0 text-muted-foreground" />

            {/* A native select: keyboard accessible and correct on touch
                without building a popover. */}
            <select
              value={documentId}
              onChange={(event) => setDocumentId(event.target.value)}
              disabled={documents.length === 0}
              className="min-w-0 max-w-[12rem] appearance-none truncate bg-transparent pr-5 text-sm outline-none disabled:text-muted-foreground"
            >
              {documents.length === 0 ? (
                <option value="">No document indexed</option>
              ) : (
                documents.map((doc) => (
                  <option
                    key={doc.document_id}
                    value={doc.document_id}
                    className="bg-popover text-popover-foreground"
                  >
                    {doc.file_name}
                  </option>
                ))
              )}
            </select>

            <ChevronDown className="pointer-events-none absolute right-2 size-4 text-muted-foreground" />
          </div>
        </div>
      </div>

      {showRequest && (
        <div className="mt-4">
          <JsonBlock
            prefix={`POST ${gatewayUrl}/chat
Content-Type: application/json`}
            code={requestBody}
            onCopied={() => toast.success('Request copied')}
          />
        </div>
      )}

      <div className="mt-5 flex h-[26rem] flex-col rounded-xl border border-border">
        {/* The transcript scrolls; the composer below stays put. Letting the
            page scroll instead would carry the input off the screen. */}
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {messages.length === 0 && !sending && (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <Sparkles className="size-5 text-muted-foreground" />
              <p className="mt-3 text-sm text-muted-foreground">
                {selected
                  ? `Ask something about ${selected.file_name}`
                  : 'Upload a document above to try a question'}
              </p>
            </div>
          )}

          <div className="mx-auto flex max-w-2xl flex-col gap-3">
            {messages.map((message, index) => {
              const mine = message.role === 'user';

              return (
                <div
                  key={index}
                  className={`group flex ${mine ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`relative max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                      mine
                        ? 'bg-primary text-primary-foreground'
                        : message.failed
                          ? 'border border-border bg-destructive text-destructive-foreground'
                          : 'border border-border bg-card text-card-foreground'
                    }`}
                  >
                    {/* Only on answers: there is no use in copying back a
                        question the user just typed. Hidden until the row is
                        hovered or the button takes focus, so it does not sit
                        over the text. */}
                    {!mine && !message.failed && (
                      <button
                        type="button"
                        onClick={() => copyAnswer(message.content)}
                        aria-label="Copy answer"
                        className="absolute -right-1 -top-1 rounded-md border border-border bg-card p-1.5 text-muted-foreground opacity-0 transition-opacity hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
                      >
                        <Copy className="size-3" />
                      </button>
                    )}

                    <p className="whitespace-pre-wrap">{message.content}</p>

                    {message.labels?.length > 0 && (
                      <div className="mt-2.5 flex flex-wrap gap-1.5 border-t border-border pt-2">
                        {[...new Set(message.labels)].map((label) => (
                          <span
                            key={label}
                            className="rounded-md bg-secondary px-1.5 py-0.5 text-[11px] text-muted-foreground"
                          >
                            {label}
                          </span>
                        ))}
                      </div>
                    )}

                    {/* What the retrieval actually did, which is the part a
                        developer is here to inspect. */}
                    {!mine && !message.failed && message.chunks !== undefined && (
                      <p className="mt-2 text-[11px] text-muted-foreground">
                        {message.chunks} chunks
                        {message.retrievers?.length
                          ? ` · ${message.retrievers.join(' + ')}`
                          : ''}
                        {message.grounded ? '' : ' · not in the document'}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}

            {sending && (
              <div className="flex justify-start">
                <div className="flex items-center gap-2 rounded-2xl border border-border bg-card px-4 py-2.5 text-sm text-muted-foreground">
                  <Loader2 className="size-3.5 animate-spin" />
                  Reading the document...
                </div>
              </div>
            )}

            <div ref={bottom} />
          </div>
        </div>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            send();
          }}
          className="border-t border-border p-3"
        >
          <div className="mx-auto flex max-w-2xl items-end gap-2">
            <div className="flex min-w-0 flex-1 items-end gap-2 rounded-xl border border-input bg-card px-3 py-2 focus-within:border-ring">
              <textarea
                ref={input}
                rows={1}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={handleKeyDown}
                disabled={!documentId}
                placeholder={
                  documentId ? 'Ask about this document...' : 'No document indexed'
                }
                className="max-h-32 min-w-0 flex-1 resize-none bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
              />

              <span className="hidden shrink-0 items-center gap-1 text-[11px] text-muted-foreground sm:flex">
                <CornerDownLeft className="size-3" />
                send
              </span>
            </div>

            <button
              type="submit"
              aria-label="Send"
              disabled={!question.trim() || sending || !documentId}
              className="shrink-0 rounded-xl bg-primary p-2.5 text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {sending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Send className="size-4" />
              )}
            </button>
          </div>
        </form>
      </div>

      <p className="mt-3 text-xs text-muted-foreground">
        The document never leaves this machine. Only the question and the
        matching chunks reach the engine.
      </p>
    </section>
  );
};

export default ApiPlayground;
