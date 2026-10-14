import { useEffect, useState } from 'react';
import { Check, CreditCard, ExternalLink, Loader2, Sparkles } from 'lucide-react';
import { cloud } from '@/services/api';

// What the Pro tier actually buys, in this architecture. Deliberately not
// "priority indexing": indexing runs on the customer's own machine, so there
// is no queue here for the cloud to move anyone up.
const PRO_FEATURES = [
  'Unlimited requests per month',
  'Multiple API keys per account',
  'Per-key rate limiting',
  'Usage history per key',
];

/** "resets 1 Nov" - the engine's counter rolls on the UTC month boundary. */
const nextReset = () => {
  const now = new Date();
  const next = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 1));

  return next.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
};

/**
 * Current plan, usage against it, and the way to change it.
 *
 * Usage comes from the same /v1/keys response the stat cards read, so the
 * number here and the number above cannot disagree.
 */
const BillingManager = ({ plan = 'free', quota }) => {
  const [starting, setStarting] = useState(false);
  const [opening, setOpening] = useState(false);
  const [notice, setNotice] = useState('');

  // Null until the server has answered, so the button does not flicker
  // between states on first paint.
  const [billingLive, setBillingLive] = useState(null);

  useEffect(() => {
    const load = async () => {
      const config = await cloud.billingConfig();

      setBillingLive(Boolean(config.enabled));
    };

    load();
  }, []);

  const unlimited = Boolean(quota?.unlimited) || quota?.limit === null;
  const used = quota?.used ?? 0;
  const limit = quota?.limit ?? null;

  // Capped at 100% so a metered account that went over - an admin exemption
  // removed mid-month, say - does not render a bar past its own track.
  const percent = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  const isPro = plan === 'pro';

  // An account can be unlimited without being on Pro: admin emails are
  // exempt by address, not by plan. Offering such an account an upgrade that
  // buys it nothing is the kind of contradiction people stop trusting a
  // billing page over.
  const exempt = unlimited && !isPro;

  // Only offer a checkout that can actually complete. With no Stripe keys on
  // the server the button would reach the endpoint and come back "billing is
  // not configured", which is a worse answer than not asking.
  const showUpgrade = !isPro && !unlimited && billingLive === true;
  const billingOffline = billingLive === false && !isPro && !unlimited;

  const manage = async () => {
    if (opening) return;

    setOpening(true);
    setNotice('');

    try {
      const session = await cloud.createPortalSession();

      if (session?.url) {
        // Leaves for Stripe. Whatever they change there comes back to us as a
        // webhook, not as a return value.
        window.location.assign(session.url);
        return;
      }

      setNotice('The portal returned no URL.');
    } catch (problem) {
      setNotice(problem.message || 'Could not open the billing portal.');
      console.warn('[billing] portal unavailable:', problem);
    } finally {
      setOpening(false);
    }
  };

  const upgrade = async () => {
    if (starting) return;

    setStarting(true);
    setNotice('');

    try {
      const session = await cloud.createCheckoutSession('pro');

      // Once the backend exists it returns a Stripe Checkout URL and the
      // browser leaves for it.
      if (session?.url) {
        window.location.assign(session.url);
        return;
      }

      setNotice('Checkout returned no URL.');
    } catch (problem) {
      setNotice(problem.message || 'Could not start checkout.');
      console.warn('[billing] checkout unavailable:', problem);
    } finally {
      setStarting(false);
    }
  };

  return (
    <section>
      <div>
        <h2 className="text-base font-semibold tracking-tight">Billing</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Your plan and what you have used this month.
        </p>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        {/* Current plan and usage */}
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Current plan
              </p>
              <p className="mt-1.5 text-lg font-semibold tracking-tight">
                {isPro ? 'Pro' : 'Free'}
              </p>
            </div>

            <span className="rounded-md bg-secondary px-2 py-1 text-[11px] text-muted-foreground">
              {isPro ? '$20 / month' : exempt ? 'Unlimited' : 'No card required'}
            </span>
          </div>

          <div className="mt-6">
            <div className="flex items-baseline justify-between gap-2">
              <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Requests this month
              </p>
              <p className="text-sm font-medium">
                {used.toLocaleString()}
                <span className="text-muted-foreground">
                  {unlimited ? ' / ∞' : ` / ${limit ?? '--'}`}
                </span>
              </p>
            </div>

            {unlimited ? (
              <p className="mt-3 text-xs text-muted-foreground">
                {exempt
                  ? 'No monthly limit on this account - it is exempt from metering.'
                  : 'No monthly limit on this account.'}
              </p>
            ) : (
              <>
                {/* A track and a fill, rather than a <progress> element: it
                    takes the theme's colours without fighting the browser's
                    own styling of it. */}
                <div
                  className="mt-3 h-2 w-full overflow-hidden rounded-full bg-secondary"
                  role="progressbar"
                  aria-valuenow={percent}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label="Monthly request usage"
                >
                  <div
                    className="h-full rounded-full bg-foreground transition-[width] duration-500"
                    style={{ width: `${percent}%` }}
                  />
                </div>

                <p className="mt-2 text-xs text-muted-foreground">
                  {percent}% used ·{' '}
                  {limit && used >= limit
                    ? 'requests are being refused'
                    : `resets ${nextReset()}`}
                </p>
              </>
            )}
          </div>
        </div>

        {/* The upgrade, or confirmation they already have it */}
        <div
          className={`flex flex-col rounded-xl border p-5 ${
            showUpgrade
              ? 'border-foreground bg-foreground text-background'
              : 'border-border bg-card'
          }`}
        >
          <div className="flex items-center gap-2">
            <Sparkles className="size-4" />
            <p className="text-sm font-semibold">Pro</p>

            {isPro && (
              <span className="ml-auto rounded-md bg-secondary px-2 py-0.5 text-[11px] text-muted-foreground">
                current plan
              </span>
            )}
          </div>

          <div className="mt-4 flex items-baseline gap-1">
            <span className="text-3xl font-semibold tracking-tight">$20</span>
            <span className={`text-sm ${showUpgrade ? 'opacity-70' : 'text-muted-foreground'}`}>
              /month
            </span>
          </div>

          <ul className="mt-5 flex-1 space-y-2">
            {PRO_FEATURES.map((feature) => (
              <li key={feature} className="flex items-center gap-2 text-sm">
                <Check className={`size-4 shrink-0 ${showUpgrade ? '' : 'text-muted-foreground'}`} />
                {feature}
              </li>
            ))}
          </ul>

          {isPro ? (
            <button
              type="button"
              onClick={manage}
              disabled={opening}
              className="mt-6 inline-flex items-center justify-center gap-2 rounded-lg border border-border bg-secondary px-4 py-2.5 text-sm font-medium text-secondary-foreground transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
            >
              {opening ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <ExternalLink className="size-4" />
              )}
              {opening ? 'Opening portal...' : 'Manage subscription'}
            </button>
          ) : billingOffline ? (
            <p className="mt-6 text-xs leading-relaxed text-muted-foreground">
              Paid plans are not open yet. Everything here is free during the
              beta, with the free tier's monthly limit.
            </p>
          ) : !showUpgrade ? (
            <p className="mt-6 text-xs text-muted-foreground">
              This account already has unlimited requests, so there is nothing
              to upgrade.
            </p>
          ) : (
            <button
              type="button"
              onClick={upgrade}
              disabled={starting}
              className="mt-6 inline-flex items-center justify-center gap-2 rounded-lg bg-background px-4 py-2.5 text-sm font-medium text-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {starting ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <CreditCard className="size-4" />
              )}
              {starting ? 'Starting checkout...' : 'Upgrade with Stripe'}
            </button>
          )}

          {isPro && !notice && (
            <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
              Invoices, card details and cancellation, on Stripe.
            </p>
          )}

          {notice && (
            <p
              className={`mt-3 text-xs leading-relaxed ${
                showUpgrade ? 'opacity-80' : 'text-muted-foreground'
              }`}
            >
              {notice}
            </p>
          )}
        </div>
      </div>
    </section>
  );
};

export default BillingManager;
