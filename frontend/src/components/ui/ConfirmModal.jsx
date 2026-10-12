import { useRef } from 'react';
import { Loader2 } from 'lucide-react';
import ModalShell from './ModalShell';

/**
 * Yes/no dialog. The cancel button takes focus on open, not confirm: for a
 * destructive action the safe choice should be the one a stray Enter hits.
 */
const ConfirmModal = ({
  isOpen,
  title,
  description,
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  onConfirm,
  onCancel,
  busy = false,
}) => {
  const cancelButton = useRef(null);

  return (
    <ModalShell
      isOpen={isOpen}
      title={title}
      description={description}
      onCancel={busy ? undefined : onCancel}
      initialFocusRef={cancelButton}
    >
      <div className="mt-6 flex justify-end gap-2">
        <button
          ref={cancelButton}
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="rounded-lg border border-border bg-secondary px-4 py-2 text-sm font-medium text-secondary-foreground transition-colors hover:bg-accent disabled:opacity-50"
        >
          {cancelText}
        </button>

        <button
          type="button"
          onClick={onConfirm}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-60"
        >
          {busy && <Loader2 className="size-4 animate-spin" />}
          {confirmText}
        </button>
      </div>
    </ModalShell>
  );
};

export default ConfirmModal;
