import { Toaster } from 'sonner';

/**
 * One toaster for the whole app.
 *
 * Styled from the theme tokens rather than sonner's defaults, which assume a
 * light surface and coloured success/error variants. In a monochrome UI the
 * variants have to separate by weight, not hue: an error inverts to a white
 * card, everything else stays a dark one.
 */
const Toasts = () => (
  <Toaster
    theme="dark"
    position="bottom-right"
    // Long enough to read a filename, short enough not to sit over the table.
    duration={3500}
    gap={10}
    toastOptions={{
      classNames: {
        toast:
          'rounded-xl border border-border bg-card text-card-foreground shadow-lg',
        title: 'text-sm font-medium',
        description: 'text-xs text-muted-foreground',
        actionButton: 'rounded-md bg-primary px-2 py-1 text-primary-foreground',
        cancelButton: 'rounded-md bg-secondary px-2 py-1 text-secondary-foreground',
        error: 'border-foreground bg-foreground text-background',
        icon: 'text-muted-foreground',
      },
    }}
  />
);

export default Toasts;
