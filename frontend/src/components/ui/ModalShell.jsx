import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

const FOCUSABLE =
  'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

/**
 * The parts every dialog needs and nobody enjoys writing twice.
 *
 * Rendered through a portal to document.body rather than in place: the
 * sidebar that opens one of these sits inside an overflow-y-auto column, and
 * a dialog rendered there is clipped by its scroll container.
 */
const ModalShell = ({
  isOpen,
  title,
  description,
  onCancel,
  initialFocusRef,
  children,
}) => {
  const dialog = useRef(null);
  const returnFocusTo = useRef(null);

  useEffect(() => {
    if (!isOpen) return undefined;

    // Remember who opened this, so closing puts focus back where the user
    // left it instead of at the top of the document.
    returnFocusTo.current = document.activeElement;

    const target = initialFocusRef?.current || dialog.current;
    target?.focus();

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCancel?.();
        return;
      }

      if (event.key !== 'Tab') return;

      // Keep Tab inside the dialog: without this, focus walks off into the
      // page behind the backdrop, which a keyboard user cannot see.
      const focusable = dialog.current?.querySelectorAll(FOCUSABLE) || [];

      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown);

    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
      returnFocusTo.current?.focus?.();
    };
  }, [isOpen, initialFocusRef, onCancel]);

  if (!isOpen) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 px-4"
      onMouseDown={(event) => {
        // Only a click that starts on the backdrop closes it, so a drag that
        // ends outside the card does not dismiss what you were typing.
        if (event.target === event.currentTarget) onCancel?.();
      }}
    >
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        tabIndex={-1}
        className="w-full max-w-sm rounded-xl border border-border bg-card p-6 outline-none"
      >
        <h2 id="modal-title" className="text-base font-semibold tracking-tight">
          {title}
        </h2>

        {description && (
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            {description}
          </p>
        )}

        {children}
      </div>
    </div>,
    document.body
  );
};

export default ModalShell;
