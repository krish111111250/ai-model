import { useEffect, useRef, useState } from 'react';
import { ChevronDown, FileText, Loader2, Mic, Send } from 'lucide-react';
import InitBanner from '@/components/InitBanner';
import { api } from '@/services/api';

/**
 * Right side: banner slot, document selector, transcript, composer.
 *
 * The three rows are fixed-height except the transcript, which takes the rest
 * and scrolls on its own. Making the page scroll instead would carry the
 * composer off the bottom of the screen as a conversation grows.
 */
const ChatArea = ({
  headerInset = false,
  sessionId,
  documents,
  selectedDocumentId,
  onSelectDocument,
}) => {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const bottom = useRef(null);

  const selectedDocument = documents.find(
    (doc) => doc.document_id === selectedDocumentId
  );

  // A new session id means the "New chat" button was pressed, so the
  // transcript on screen belongs to the previous conversation.
  useEffect(() => {
    setMessages([]);
  }, [sessionId]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, sending]);

  const send = async () => {
    const query = input.trim();

    if (!query || sending || !selectedDocumentId) return;

    setMessages((previous) => [...previous, { role: 'user', content: query }]);
    setInput('');
    setSending(true);

    try {
      const response = await api.sendChatMessage({
        query,
        sessionId,
        documentId: selectedDocumentId,
        documentMode: 'single',
      });

      setMessages((previous) => [
        ...previous,
        {
          role: 'assistant',
          content: response.answer,
          // Only a grounded answer has citations; a refusal deliberately
          // carries none, and showing pages next to "not in the document"
          // would suggest the opposite.
          grounded: response.grounded,
          sources: response.sources || [],
          sourceLabels: response.source_labels || [],
          retrievers: response.retrievers || [],
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
    }
  };

  const handleKeyDown = (event) => {
    // Enter sends, Shift+Enter breaks the line - what every chat input does.
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  };

  return (
    <section className="flex min-w-0 flex-1 flex-col">
      <InitBanner />

      {/* headerInset clears the layout's sidebar toggle once the sidebar is
          collapsed and the toggle sits over this header instead. */}
      <header
        className={`flex items-center gap-3 border-b border-border py-3 pr-4 transition-[padding] duration-300 ease-in-out ${
          headerInset ? 'md:pl-14' : ''
        } pl-4`}
      >
        <div className="relative flex min-w-0 items-center gap-2 rounded-lg border border-border bg-secondary px-3 py-1.5 text-sm text-secondary-foreground">
          <FileText className="size-4 shrink-0 text-muted-foreground" />

          {/* A native select rather than a custom popover: it is keyboard
              accessible and correct on touch devices for free. */}
          <select
            value={selectedDocumentId}
            onChange={(event) => onSelectDocument?.(event.target.value)}
            disabled={documents.length === 0}
            className="min-w-0 max-w-[16rem] appearance-none truncate bg-transparent pr-5 text-sm text-secondary-foreground outline-none disabled:text-muted-foreground"
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

        <p className="ml-auto hidden text-xs text-muted-foreground sm:block">
          Answers come only from the selected document
        </p>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6">
        <div className="mx-auto flex max-w-3xl flex-col gap-4">
          {messages.length === 0 && !sending && (
            <div className="pt-16 text-center">
              <p className="text-sm text-muted-foreground">
                {selectedDocument
                  ? `Ask anything about ${selectedDocument.file_name}`
                  : 'Upload a PDF to get started'}
              </p>
            </div>
          )}

          {messages.map((message, index) => {
            const mine = message.role === 'user';
            const citations = message.sourceLabels?.length
              ? message.sourceLabels
              : (message.sources || [])
                  .filter((source) => source.page_number)
                  .map((source) => `${source.file_name} - Page ${source.page_number}`);

            return (
              <div
                key={index}
                className={`flex ${mine ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                    mine
                      ? 'bg-primary text-primary-foreground'
                      : message.failed
                        ? 'border border-border bg-destructive text-destructive-foreground'
                        : 'border border-border bg-card text-card-foreground'
                  }`}
                >
                  <p className="whitespace-pre-wrap">{message.content}</p>

                  {citations.length > 0 && (
                    <div className="mt-2.5 flex flex-wrap gap-1.5 border-t border-border pt-2">
                      {[...new Set(citations)].map((label) => (
                        <span
                          key={label}
                          className="rounded-md bg-secondary px-1.5 py-0.5 text-[11px] text-muted-foreground"
                        >
                          {label}
                        </span>
                      ))}
                    </div>
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

      <footer className="border-t border-border px-4 py-3">
        <form
          className="mx-auto flex max-w-3xl items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            send();
          }}
        >
          <div className="flex min-w-0 flex-1 items-end gap-2 rounded-xl border border-input bg-card px-3 py-2 focus-within:border-ring">
            <textarea
              rows={1}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleKeyDown}
              disabled={!selectedDocumentId}
              placeholder={
                selectedDocumentId
                  ? 'Ask about this document...'
                  : 'Upload a PDF first'
              }
              className="max-h-40 min-w-0 flex-1 resize-none bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
            />

            <button
              type="button"
              aria-label="Dictate"
              className="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
            >
              <Mic className="size-4" />
            </button>
          </div>

          <button
            type="submit"
            aria-label="Send"
            disabled={!input.trim() || sending || !selectedDocumentId}
            className="shrink-0 rounded-xl bg-primary p-2.5 text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {sending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Send className="size-4" />
            )}
          </button>
        </form>

        <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-muted-foreground">
          Your documents stay on this machine.
        </p>
      </footer>
    </section>
  );
};

export default ChatArea;
