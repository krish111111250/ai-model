import { useCallback, useEffect, useState } from 'react';
import { Check, Copy, KeyRound, Loader2, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import ConfirmModal from '@/components/ui/ConfirmModal';
import EmptyState from '@/components/ui/EmptyState';
import PromptModal from '@/components/ui/PromptModal';
import { cloud } from '@/services/api';

/** "2026-10-09T17:40:40" -> "2026-10-09". Null stays null. */
const asDate = (value) => (value ? String(value).slice(0, 10) : null);

/**
 * Generate, list and revoke the account's API keys.
 *
 * Owns its own data rather than taking it as props: it is the only thing that
 * changes the key list, so having it fetch and refresh its own copy means
 * there is no second source of truth to keep in step. The dashboard's stat
 * cards read the same response through onData.
 */
const ApiKeyManager = ({ onData, refreshKey = 0 }) => {
  const [keys, setKeys] = useState([]);
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
      setError('');

      // The same response carries the account's quota, which the stat cards
      // above need. Handing it up beats a second request for it.
      onData?.(data);
    } catch (problem) {
      // A failed list leaves the section with nothing to show, so this one
      // stays inline. A toast would vanish and leave an empty table behind.
      setError(problem.message || 'Could not load API keys.');
    }
  }, [onData]);

  useEffect(() => {
    const bootstrap = async () => {
      await loadKeys();
      setLoading(false);
    };

    bootstrap();
    // refreshKey is a signal, not data: the dashboard bumps it after a Stripe
    // redirect so this list reflects the same change the plan card does.
  }, [loadKeys, refreshKey]);

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

      toast.success('API key created', {
        description: `${created.name} - copy it now, it cannot be shown again.`,
      });
    } catch (problem) {
      // The dialog stays open on failure so the name is not lost.
      toast.error('Could not generate a key', { description: problem.message });
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

      toast.success('Key revoked', {
        description: `${key.name} - requests using it now fail.`,
      });
    } catch (problem) {
      toast.error('Could not revoke the key', { description: problem.message });
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

      toast.success('Key copied to clipboard');
    } catch {
      // Clipboard access is denied outside a secure context. Say so, since
      // the button visibly did nothing.
      toast.error('Could not copy', {
        description: 'Select the key and copy it manually.',
      });
    }
  };

  return (
    <section>
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

      {/* The only moment this token exists outside the engine's hash. Shown
          as a panel rather than a table cell so it cannot be scrolled past. */}
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
            Paste it into the local app, or set KRISH_API_KEY before starting
            the gateway.
          </p>
        </div>
      )}

      {!loading && keys.length === 0 && !error ? (
        <div className="mt-5">
          <EmptyState
            icon={KeyRound}
            title="No API keys yet"
            description="A key lets your own code ask questions of your documents. The plaintext is shown once when it is created and only its hash is stored."
            action={
              <button
                type="button"
                onClick={() => setNaming(true)}
                disabled={generating}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                <Plus className="size-4" />
                Generate your first key
              </button>
            }
            hint="Send it as the X-API-Key header on /v1 requests."
          />
        </div>
      ) : (
      /* Scrolls sideways rather than forcing the page wide on a phone; the
         less critical columns drop out at sm and md first. */
      <div className="mt-5 overflow-x-auto rounded-xl border border-border">
        <table className="w-full min-w-[32rem] text-left text-sm">
          <thead className="border-b border-border bg-card">
            <tr className="text-xs uppercase tracking-wider text-muted-foreground">
              <th className="px-5 py-3 font-medium">Name</th>
              <th className="px-5 py-3 font-medium">Key</th>
              <th className="hidden px-5 py-3 font-medium sm:table-cell">Created</th>
              <th className="hidden px-5 py-3 font-medium md:table-cell">Last used</th>
              <th className="hidden px-5 py-3 font-medium lg:table-cell">Requests</th>
              <th className="px-5 py-3 text-right font-medium">Actions</th>
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
                      {/* Always masked. There is no plaintext to reveal: the
                          engine stored a hash, so no amount of UI can produce
                          the token again. */}
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

                    {/* Lifetime, per key. The month's figure is an account
                        total - the quota is enforced there - so there is no
                        per-key monthly number to show. */}
                    <td className="hidden px-5 py-4 text-muted-foreground lg:table-cell">
                      {(key.request_count || 0).toLocaleString()}
                      <span className="ml-1.5 text-[11px] opacity-70">all time</span>
                    </td>

                    <td className="px-5 py-4 text-right">
                      {/* Revoking a revoked key is a no-op on the engine, so
                          the button goes away rather than lying. */}
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
      )}

      {keys.length > 0 && (
        <p className="mt-3 text-xs text-muted-foreground">
          Revoked keys are kept so past usage stays auditable.
        </p>
      )}

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
    </section>
  );
};

export default ApiKeyManager;
