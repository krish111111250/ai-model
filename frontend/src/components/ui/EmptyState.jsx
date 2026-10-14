/**
 * What a section looks like before it has anything in it.
 *
 * A row of grey text in an otherwise empty table reads as a failure to load.
 * This says what the thing is for and offers the one action that fills it,
 * which is the difference between a new account looking broken and looking
 * ready.
 */
const EmptyState = ({ icon: Icon, title, description, action, hint }) => (
  <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border px-6 py-14 text-center">
    {Icon && (
      <div className="flex size-11 items-center justify-center rounded-full border border-border bg-card">
        <Icon className="size-5 text-muted-foreground" />
      </div>
    )}

    <p className="mt-4 text-sm font-medium text-foreground">{title}</p>

    {description && (
      <p className="mt-1.5 max-w-sm text-xs leading-relaxed text-muted-foreground">
        {description}
      </p>
    )}

    {action && <div className="mt-5">{action}</div>}

    {hint && (
      <p className="mt-4 max-w-sm text-[11px] leading-relaxed text-muted-foreground">
        {hint}
      </p>
    )}
  </div>
);

export default EmptyState;
