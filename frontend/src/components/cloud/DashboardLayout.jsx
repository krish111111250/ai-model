import { useCallback, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Activity, KeyRound } from 'lucide-react';
import ApiKeyManager from '@/components/cloud/ApiKeyManager';
import ApiPlayground from '@/components/cloud/ApiPlayground';
import BillingManager from '@/components/cloud/BillingManager';
import DocumentManager from '@/components/cloud/DocumentManager';
import { clearAccount, useAccount } from '@/hooks/useAccount';
import { cloud } from '@/services/api';

const StatCard = ({ icon: Icon, label, value, note }) => (
  <div className="rounded-xl border border-border bg-card p-5">
    <div className="flex items-center gap-2">
      <Icon className="size-4 text-muted-foreground" />
      <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
    </div>

    <p className="mt-3 text-2xl font-semibold tracking-tight">{value}</p>
    <p className="mt-1 text-xs text-muted-foreground">{note}</p>
  </div>
);

/**
 * The tenant dashboard: usage above, key management below.
 *
 * Key state lives in ApiKeyManager, which is the only thing that changes it.
 * This passes a callback down and reads the same /v1/keys response for the
 * stat cards, so the two never disagree about how many keys exist.
 */
const DashboardLayout = () => {
  const navigate = useNavigate();

  // Same hook the document manager uses, so the header and the document
  // list can never be scoped to different accounts.
  const { account } = useAccount();

  const [summary, setSummary] = useState(null);
  const [documents, setDocuments] = useState([]);

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

  const signOut = () => {
    cloud.logout();
    clearAccount();
    navigate('/login', { replace: true });
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-10 border-b border-border bg-background/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-6 py-3.5">
          <Link to="/" className="text-sm font-semibold tracking-tight">
            Krish AI
          </Link>

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
        <h1 className="text-xl font-semibold tracking-tight">Overview</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          Usage across every key on this account.
        </p>

        <section className="mt-6 grid gap-4 sm:grid-cols-2">
          {stats.map((stat) => (
            <StatCard key={stat.label} {...stat} />
          ))}
        </section>

        <div className="mt-12 border-t border-border pt-12">
          <BillingManager plan={summary?.plan} quota={summary?.quota} />
        </div>

        <div className="mt-12">
          <ApiKeyManager onData={handleKeyData} />
        </div>

        <div className="mt-12 border-t border-border pt-12">
          <DocumentManager onDocuments={setDocuments} />
        </div>

        <div className="mt-12 border-t border-border pt-12">
          <ApiPlayground documents={documents} />
        </div>
      </main>
    </div>
  );
};

export default DashboardLayout;
