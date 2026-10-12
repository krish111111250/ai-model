import { useEffect, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import ModalShell from './ModalShell';

/**
 * Asks for one value. The input is focused and its text selected on open, so
 * a default can be accepted with Enter or replaced by typing.
 */
const PromptModal = ({
  isOpen,
  title,
  description,
  placeholder = '',
  defaultValue = '',
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  onConfirm,
  onCancel,
  busy = false,
}) => {
  const input = useRef(null);
  const [value, setValue] = useState(defaultValue);
  const [wasOpen, setWasOpen] = useState(isOpen);

  // Reset on each open, or the previous answer is still sitting there the
  // next time the dialog appears. Adjusted during render rather than in an
  // effect: React re-runs this pass immediately without painting the stale
  // value first, which an effect cannot promise.
  if (isOpen !== wasOpen) {
    setWasOpen(isOpen);

    if (isOpen) setValue(defaultValue);
  }

  useEffect(() => {
    if (isOpen) input.current?.select();
  }, [isOpen]);

  const submit = (event) => {
    event.preventDefault();

    if (busy) return;

    onConfirm?.(value.trim());
  };

  return (
    <ModalShell
      isOpen={isOpen}
      title={title}
      description={description}
      onCancel={busy ? undefined : onCancel}
      initialFocusRef={input}
    >
      <form onSubmit={submit}>
        <input
          ref={input}
          type="text"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder={placeholder}
          disabled={busy}
          className="mt-5 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-ring disabled:opacity-60"
        />

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded-lg border border-border bg-secondary px-4 py-2 text-sm font-medium text-secondary-foreground transition-colors hover:bg-accent disabled:opacity-50"
          >
            {cancelText}
          </button>

          <button
            type="submit"
            disabled={busy}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            {busy && <Loader2 className="size-4 animate-spin" />}
            {confirmText}
          </button>
        </div>
      </form>
    </ModalShell>
  );
};

export default PromptModal;
