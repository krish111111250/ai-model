import { useCallback, useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { clearAccount, useAccount } from '@/hooks/useAccount';
import { cloud } from '@/services/api';

// Active is a filled pill rather than a coloured underline: the theme has one
// accent and the header already uses it for hover, so reusing it here keeps
// the bar monochrome.
const navClass = ({ isActive }) =>
  [
    'rounded-md px-3 py-1.5 text-sm transition-colors',
    isActive
      ? 'bg-accent text-foreground'
      : 'text-muted-foreground hover:bg-accent hover:text-foreground',
  ].join(' ');

/**
 * The shell both dashboard pages render inside: header, navigation, and the
 * account state that has to outlive a page switch.
 *
 * The workspace (documents, playground) and the account pages (usage,
 * billing, keys) are separate routes instead of one long scroll. Key data
 * lives here rather than in the settings page because Stripe returns the
 * browser to /dashboard, not to /dashboard/settings - the plan refresh has to
 * run from something that is mounted whichever page is showing. Pages read it
 * through the outlet context.
 */
const DashboardLayout = () => {
  const navigate = useNavigate();

  // Same hook the document manager uses, so the header and the document
  // list can never be scoped to different accounts.
  const { account } = useAccount();

  const [summary, setSummary] = useState(null);

  // Bumped to make ApiKeyManager refetch. A counter rather than an imperative
  // handle on the child: the child already refetches when its deps change.
  const [refreshKey, setRefreshKey] = useState(0);
  const [syncing, setSyncing] = useState('');

  // Identical arguments must give an identical function, or ApiKeyManager's
  // effect would see a new dependency on every render and refetch forever.
  const handleKeyData = useCallback((data) => {
    setSummary({
      keys: data.keys || [],
      plan: data.plan || 'free',
      // An older engine will not send these. Undefined means "the server did
      // not say", which the card reports as all-time rather than guessing.
      quota:
        data.quota_used === undefined
          ? null
          : {
              used: data.quota_used,
              limit: data.quota_limit,
              unlimited: Boolean(data.unlimited),
            },
    });
  }, []);

  // Coming back from Stripe, the plan may not have changed yet: the webhook
  // that grants it is a separate request from Stripe's servers, and it can
  // land after the browser does. Showing "Free plan" to someone who just paid
  // is the worst possible moment to be a second out of date.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const checkout = params.get('checkout');
    const portal = params.get('portal');

    if (!checkout && !portal) return;

    // Stripe sends everyone to /dashboard, which is now the workspace. Put
    // them back on the page they left from, and let the navigation drop the
    // query string: a reload mid-wait should not start the whole dance again.
    navigate('/dashboard/settings', { replace: true });

    if (checkout === 'cancelled') return;

    let cancelled = false;

    const sync = async () => {
      setSyncing(
        checkout === 'success'
          ? 'Confirming your subscription...'
          : 'Checking for billing changes...'
      );

      // Checkout has a target to wait for - the plan turning paid - so poll
      // until it does. Returning from the portal has no single expected
      // outcome (a cancellation, a new card, or nothing at all), so one
      // delayed read is all that can be justified.
      const attempts = checkout === 'success' ? 5 : 1;

      for (let attempt = 0; attempt < attempts; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 1500));

        if (cancelled) return;

        try {
          const data = await cloud.getKeys();

          if (cancelled) return;

          handleKeyData(data);

          if (checkout !== 'success' || data.unlimited) break;
        } catch {
          // The interceptor handles an expired session; anything else is
          // covered by the next attempt or by the manual reload.
        }
      }

      if (cancelled) return;

      // Let the key table pick up the same change.
      setRefreshKey((value) => value + 1);
      setSyncing('');
    };

    sync();

    return () => {
      cancelled = true;
    };
  }, [handleKeyData, navigate]);

  const signOut = () => {
    cloud.logout();
    clearAccount();
    navigate('/login', { replace: true });
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-10 border-b border-border bg-background/80 backdrop-blur">
        {/* Wraps instead of overflowing: on a narrow screen the page links
            drop onto a second line rather than pushing Logout off the edge. */}
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-6 py-3.5">
          <Link to="/" className="text-sm font-semibold tracking-tight">
            Krish AI
          </Link>

          <nav className="flex items-center gap-1">
            {/* `end` or the workspace link would stay lit on the settings
                page, which is nested under its path. */}
            <NavLink to="/dashboard" end className={navClass}>
              Dashboard
            </NavLink>

            <NavLink to="/dashboard/settings" className={navClass}>
              Settings
            </NavLink>
          </nav>

          <nav className="ml-auto flex items-center gap-1">
            <a
              href="http://localhost:8000/docs"
              target="_blank"
              rel="noreferrer"
              className="rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              Docs
            </a>

            {account && (
              <span className="hidden px-3 text-sm text-muted-foreground sm:inline">
                {account.email}
              </span>
            )}

            <button
              type="button"
              onClick={signOut}
              className="rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              Logout
            </button>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-10">
        {/* Says why the page is about to change by itself. Above the outlet so
            it is visible on whichever page the redirect landed on. */}
        {syncing && (
          <p className="mb-6 inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-xs text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" />
            {syncing}
          </p>
        )}

        <Outlet context={{ summary, handleKeyData, refreshKey }} />
      </main>
    </div>
  );
};

export default DashboardLayout;
