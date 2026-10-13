import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Activity,
  Check,
  Copy,
  KeyRound,
  Loader2,
  Plus,
  Trash2,
} from 'lucide-react';
import ConfirmModal from '@/components/ui/ConfirmModal';
import PromptModal from '@/components/ui/PromptModal';
import { cloud } from '@/services/api';

/** "2026-10-09T17:40:40" -> "2026-10-09". Null stays null. */
const asDate = (value) => (value ? String(value).slice(0, 10) : null);

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

const DashboardLayout = () => {
  const navigate = useNavigate();

  const [account, setAccount] = useState(null);
  const [keys, setKeys] = useState([]);
  const [quota, setQuota] = useState(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [revokingId, setRevokingId] = useState('');
  const [error, setError] = useState('');

  // The plaintext of a key just created. Held in component state only: it is
  // never stored, because the engine keeps a hash and cannot reproduce it.
  const [freshKey, setFreshKey] = useState(null);
  const [copied, setCopied] = useState(false);

  // Which dialog is open, and for what. Holding the key itself rather than a
  // boolean means the confirm text can name it.
  const [naming, setNaming] = useState(false);
  const [keyToRevoke, setKeyToRevoke] = useState(null);

  const loadKeys = useCallback(async () => {
    try {
      const data = await cloud.getKeys();
      setKeys(data.keys || []);

      // An older engine will not send these. Null means "the server did not
      // say", which the card reports as unknown rather than guessing zero.
      setQuota(
        data.quota_used === undefined
          ? null
          : {
              used: data.quota_used,
              limit: data.quota_limit,
              unlimited: Boolean(data.unlimited),
            }
      );

      setError('');
    } catch (problem) {
      setError(problem.message || 'Could not load API keys.');
    }
  }, []);

  useEffect(() => {
    const bootstrap = async () => {
      try {
        setAccount(await cloud.me());
      } catch {
        // A 401 is handled by the interceptor, which clears the session and
        // sends the browser to /login. Anything else is shown by loadKeys.
      }

      await loadKeys();
      setLoading(false);
    };

    bootstrap();
  }, [loadKeys]);

  const activeKeys = keys.filter((key) => !key.revoked_at).length;

  // Summed from the keys themselves - the only usage figure the engine
  // actually records.
  const totalRequests = keys.reduce(
    (total, key) => total + (key.request_count || 0),
    0
  );

  const monthlyUsage = useMemo(() => {
    if (!quota) {
      // Pre-quota engine: the month's figure does not exist, so show the
      // all-time total and say so, rather than passing it off as monthly.
      return {
        value: totalRequests.toLocaleString(),
        note: 'All time - this engine does not report monthly usage',
      };
    }

    if (quota.unlimited || quota.limit === null) {
      return {
        value: `${quota.used.toLocaleString()} / ∞`,
        note: 'Unlimited on this account',
      };
    }

    const left = Math.max(0, quota.limit - quota.used);

    return {
      value: `${quota.used.toLocaleString()} / ${quota.limit}`,
      note: left === 0
        ? 'Quota reached - requests are being refused'
        : `${left} left this month`,
    };
  }, [quota, totalRequests]);

  const stats = useMemo(
    () => [
      {
        icon: Activity,
        label: 'Monthly usage',
        value: monthlyUsage.value,
        note: monthlyUsage.note,
      },
      {
        icon: KeyRound,
        label: 'Active API keys',
        value: String(activeKeys),
        note:
          keys.length === activeKeys
            ? `${activeKeys} in use`
            : `${activeKeys} in use, ${keys.length - activeKeys} revoked`,
      },
    ],
    [activeKeys, keys.length, monthlyUsage]
  );

  const generateKey = async (name) => {
    if (generating) return;

    setGenerating(true);
    setError('');

    try {
      const created = await cloud.generateKey(name || 'unnamed key');

      setFreshKey(created);
      setCopied(false);
      setNaming(false);
      await loadKeys();
    } catch (problem) {
      setError(problem.message || 'Could not generate a key.');
      // The dialog stays open on failure so the name is not lost.
    } finally {
      setGenerating(false);
    }
  };

  const confirmRevoke = async () => {
    const key = keyToRevoke;

    if (!key || revokingId) return;

    setRevokingId(key.key_id);
    setError('');

    try {
      await cloud.revokeKey(key.key_id);

      if (freshKey?.key_id === key.key_id) setFreshKey(null);

      setKeyToRevoke(null);
      await loadKeys();
    } catch (problem) {
      setError(problem.message || 'Could not revoke the key.');
      setKeyToRevoke(null);
    } finally {
      setRevokingId('');
    }
  };

  const copyFreshKey = async () => {
    try {
      await navigator.clipboard.writeText(freshKey.api_key);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard is unavailable outside a secure context. The key is on
      // screen and selectable, so this is not worth interrupting over.
    }
  };

  const signOut = () => {
    cloud.logout();
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

        <section className="mt-12">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold tracking-tight">API keys</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Each key authenticates requests to the stateless engine.
              </p>
            </div>

            <button
              type="button"
              onClick={() => setNaming(true)}
              disabled={generating || loading}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {generating ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Plus className="size-4" />
              )}
              {generating ? 'Generating...' : 'Generate new key'}
            </button>
          </div>

          {error && (
            <p className="mt-4 rounded-lg border border-border bg-destructive px-4 py-2.5 text-sm text-destructive-foreground">
              {error}
            </p>
          )}

          {/* The only moment this token exists outside the engine's hash.
              Shown as a panel rather than a table cell so it cannot be
              scrolled past. */}
          {freshKey && (
            <div className="mt-4 rounded-xl border border-foreground bg-card p-4">
              <p className="text-sm font-medium">
                Copy your key now - it cannot be shown again
              </p>

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <code className="min-w-0 flex-1 break-all rounded-lg bg-secondary px-3 py-2 font-mono text-xs">
                  {freshKey.api_key}
                </code>

                <button
                  type="button"
                  onClick={copyFreshKey}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90"
                >
                  {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
                  {copied ? 'Copied' : 'Copy'}
                </button>

                <button
                  type="button"
                  onClick={() => setFreshKey(null)}
                  className="rounded-lg border border-border px-3 py-2 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                >
                  Done
                </button>
              </div>

              <p className="mt-2.5 text-xs text-muted-foreground">
                Paste it into the local app, or set KRISH_API_KEY before
                starting the gateway.
              </p>
            </div>
          )}

          <div className="mt-5 overflow-hidden rounded-xl border border-border">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border bg-card">
                <tr className="text-xs uppercase tracking-wider text-muted-foreground">
                  <th className="px-5 py-3 font-medium">Name</th>
                  <th className="px-5 py-3 font-medium">Key</th>
                  <th className="hidden px-5 py-3 font-medium sm:table-cell">
                    Created
                  </th>
                  <th className="hidden px-5 py-3 font-medium md:table-cell">
                    Last used
                  </th>
                  <th className="hidden px-5 py-3 font-medium lg:table-cell">
                    Requests
                  </th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>

              <tbody>
                {loading && (
                  <tr>
                    <td colSpan={6} className="px-5 py-10 text-center">
                      <Loader2 className="mx-auto size-4 animate-spin text-muted-foreground" />
                    </td>
                  </tr>
                )}

                {!loading && keys.length === 0 && (
                  <tr>
                    <td
                      colSpan={6}
                      className="px-5 py-10 text-center text-sm text-muted-foreground"
                    >
                      No keys. Generate one to start making requests.
                    </td>
                  </tr>
                )}

                {!loading &&
                  keys.map((key) => {
                    const revoked = Boolean(key.revoked_at);
                    const busy = revokingId === key.key_id;

                    return (
                      <tr
                        key={key.key_id}
                        className={`border-b border-border last:border-0 transition-colors hover:bg-accent ${
                          revoked ? 'opacity-50' : ''
                        }`}
                      >
                        <td className="px-5 py-4 font-medium">
                          {key.name}
                          {revoked && (
                            <span className="ml-2 rounded bg-secondary px-1.5 py-0.5 text-[11px] font-normal text-muted-foreground">
                              revoked
                            </span>
                          )}
                        </td>

                        <td className="px-5 py-4">
                          {/* Always masked. There is no plaintext to reveal:
                              the engine stored a hash, so no amount of UI can
                              produce the token again. */}
                          <code className="font-mono text-xs text-muted-foreground">
                            {key.masked}
                          </code>
                        </td>

                        <td className="hidden px-5 py-4 text-muted-foreground sm:table-cell">
                          {asDate(key.created_at) || '--'}
                        </td>

                        <td className="hidden px-5 py-4 text-muted-foreground md:table-cell">
                          {asDate(key.last_used_at) || 'Never'}
                        </td>

                        {/* Lifetime, per key. The month's figure is an
                            account total now - the quota is enforced there -
                            so there is no per-key monthly number to show. */}
                        <td className="hidden px-5 py-4 text-muted-foreground lg:table-cell">
                          {(key.request_count || 0).toLocaleString()}
                          <span className="ml-1.5 text-[11px] opacity-70">
                            all time
                          </span>
                        </td>

                        <td className="px-5 py-4 text-right">
                          {/* Revoking a revoked key is a no-op on the engine,
                              so the button goes away rather than lying. */}
                          {!revoked && (
                            <button
                              type="button"
                              onClick={() => setKeyToRevoke(key)}
                              disabled={busy}
                              aria-label={`Revoke ${key.name}`}
                              className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-100"
                            >
                              {busy ? (
                                <Loader2 className="size-4 animate-spin" />
                              ) : (
                                <Trash2 className="size-4" />
                              )}
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>

          <p className="mt-3 text-xs text-muted-foreground">
            Revoked keys are kept so past usage stays auditable.
          </p>
        </section>
      </main>

      <PromptModal
        isOpen={naming}
        title="Generate an API key"
        description="Give it a name you will recognise in this list later."
        placeholder="Production Key"
        defaultValue="Production Key"
        confirmText="Generate"
        onConfirm={generateKey}
        onCancel={() => setNaming(false)}
        busy={generating}
      />

      <ConfirmModal
        isOpen={Boolean(keyToRevoke)}
        title={`Revoke ${keyToRevoke?.name || 'this key'}?`}
        description="Requests using it start failing immediately. The key stays in the list, marked revoked, so its past usage remains auditable."
        confirmText="Revoke key"
        onConfirm={confirmRevoke}
        onCancel={() => setKeyToRevoke(null)}
        busy={Boolean(revokingId)}
      />
    </div>
  );
};

export default DashboardLayout;
