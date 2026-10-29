import { useMemo } from 'react';
import { useOutletContext } from 'react-router-dom';
import { Activity, KeyRound } from 'lucide-react';
import ApiKeyManager from '@/components/cloud/ApiKeyManager';
import BillingManager from '@/components/cloud/BillingManager';
import Skeleton from '@/components/ui/Skeleton';

const StatCard = ({ icon: Icon, label, value, note, loading }) => (
  <div className="rounded-xl border border-border bg-card p-5">
    <div className="flex items-center gap-2">
      <Icon className="size-4 text-muted-foreground" />
      <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
    </div>

    {loading ? (
      <>
        {/* Sized like the figures they stand in for, so the card does not
            change height when the numbers arrive. */}
        <Skeleton className="mt-3 h-7 w-24" />
        <Skeleton className="mt-2 h-3 w-36" />
      </>
    ) : (
      <>
        <p className="mt-3 text-2xl font-semibold tracking-tight">{value}</p>
        <p className="mt-1 text-xs text-muted-foreground">{note}</p>
      </>
    )}
  </div>
);

/**
 * The account page: what this account is using, what it pays, and its keys.
 *
 * Key state belongs to the layout, which is what Stripe returns to, but
 * ApiKeyManager is still the only thing that changes it: it reports upwards
 * through onData and the stat cards read the same response, so the two can
 * never disagree about how many keys exist.
 */
const SettingsPage = () => {
  const { summary, handleKeyData, refreshKey } = useOutletContext();

  const stats = useMemo(() => {
    const keys = summary?.keys || [];
    const quota = summary?.quota;

    const active = keys.filter((key) => !key.revoked_at).length;
    const lifetime = keys.reduce(
      (total, key) => total + (key.request_count || 0),
      0
    );

    let usage;

    if (!quota) {
      usage = {
        value: lifetime.toLocaleString(),
        note: 'All time - this engine does not report monthly usage',
      };
    } else if (quota.unlimited || quota.limit === null) {
      usage = {
        value: `${quota.used.toLocaleString()} / ∞`,
        note: 'Unlimited on this account',
      };
    } else {
      const left = Math.max(0, quota.limit - quota.used);

      usage = {
        value: `${quota.used.toLocaleString()} / ${quota.limit}`,
        note:
          left === 0
            ? 'Quota reached - requests are being refused'
            : `${left} left this month`,
      };
    }

    return [
      { icon: Activity, label: 'Monthly usage', ...usage },
      {
        icon: KeyRound,
        label: 'Active API keys',
        value: String(active),
        note:
          keys.length === active
            ? `${active} in use`
            : `${active} in use, ${keys.length - active} revoked`,
      },
    ];
  }, [summary]);

  return (
    <>
      <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
      <p className="mt-1.5 text-sm text-muted-foreground">
        Usage, plan, and keys for this account.
      </p>

      <section className="mt-6 grid gap-4 sm:grid-cols-2">
        {stats.map((stat) => (
          <StatCard key={stat.label} {...stat} loading={!summary} />
        ))}
      </section>

      <div className="mt-12 border-t border-border pt-12">
        <BillingManager plan={summary?.plan} quota={summary?.quota} />
      </div>

      <div className="mt-12">
        <ApiKeyManager onData={handleKeyData} refreshKey={refreshKey} />
      </div>
    </>
  );
};

export default SettingsPage;
