import { useState } from 'react';
import { ArrowUpRight, KeyRound, Loader2 } from 'lucide-react';
import { api } from '@/services/api';

/**
 * First-run screen: collect the engine API key.
 *
 * The key is posted to the local gateway, which verifies it against the
 * engine and writes it to ~/.krish/config.json with owner-only permissions.
 * It is never kept in the browser - nothing in the browser needs it, and
 * localStorage is readable by anything else running on this origin.
 */
const SetupGate = ({ onSaved, unreachable }) => {
  const [apiKey, setApiKey] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const submit = async (event) => {
    event.preventDefault();

    const trimmed = apiKey.trim();

    if (!trimmed || saving) return;

    setSaving(true);
    setError('');

    try {
      await api.saveApiKey(trimmed);
      setApiKey('');
      onSaved?.();
    } catch (problem) {
      setError(problem.message || 'Could not save the key.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex h-screen items-center justify-center bg-background px-4 text-foreground">
      <div className="w-full max-w-md rounded-xl border border-border bg-card p-6">
        <div className="mb-5 flex items-center gap-2">
          <KeyRound className="size-5 text-muted-foreground" />
          <h1 className="text-base font-semibold">Connect to the engine</h1>
        </div>

        {unreachable ? (
          <p className="text-sm leading-relaxed text-muted-foreground">
            The local gateway is not running on port 8001. Start it with{' '}
            <code className="rounded bg-secondary px-1.5 py-0.5 text-xs">
              ./start.sh
            </code>{' '}
            and reload this page.
          </p>
        ) : (
          <form onSubmit={submit}>
            <p className="mb-4 text-sm leading-relaxed text-muted-foreground">
              Paste the API key issued by the engine. It is verified, then
              stored on this machine - your documents and this key never leave
              it.
            </p>

            <input
              type="password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="krish_..."
              autoComplete="off"
              className="w-full rounded-lg border border-input bg-background px-3 py-2 font-mono text-sm text-foreground outline-none placeholder:text-muted-foreground focus:border-ring"
            />

            {error && (
              <p className="mt-2 text-xs text-destructive-foreground">{error}</p>
            )}

            <button
              type="submit"
              disabled={!apiKey.trim() || saving}
              className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {saving && <Loader2 className="size-4 animate-spin" />}
              {saving ? 'Verifying...' : 'Save and continue'}
            </button>

            <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
              No key yet? Sign in to your Krish account and generate one from
              the dashboard.
            </p>

            <a
              href="http://localhost:5173/login"
              className="mt-2 inline-flex items-center gap-1.5 text-xs font-medium text-foreground underline-offset-4 transition-colors hover:underline"
            >
              Open the dashboard
              <ArrowUpRight className="size-3.5" />
            </a>
          </form>
        )}
      </div>
    </div>
  );
};

export default SetupGate;
