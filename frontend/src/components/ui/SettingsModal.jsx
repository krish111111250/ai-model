import { useEffect, useRef, useState } from 'react';
import { Check, Loader2 } from 'lucide-react';
import ModalShell from './ModalShell';
import { api } from '@/services/api';

/**
 * Local app settings: the engine API key.
 *
 * The key is write-only from here. The gateway returns a masked form of what
 * it holds and never the key itself, so this shows which key is in use
 * without being able to hand it back - the same reason the dashboard cannot
 * re-reveal a key after creating it.
 */
const SettingsModal = ({ isOpen, onClose, onSaved }) => {
  const input = useRef(null);

  const [settings, setSettings] = useState(null);
  const [apiKey, setApiKey] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!isOpen) return;

    const load = async () => {
      setApiKey('');
      setError('');
      setSaved(false);

      try {
        setSettings(await api.getSettings());
      } catch {
        setSettings(null);
      }
    };

    load();
  }, [isOpen]);

  const save = async (event) => {
    event.preventDefault();

    const trimmed = apiKey.trim();

    if (!trimmed || saving) return;

    setSaving(true);
    setError('');

    try {
      const result = await api.saveApiKey(trimmed);

      setSettings(result);
      setApiKey('');
      setSaved(true);
      onSaved?.();
    } catch (problem) {
      setError(problem.message || 'Could not save the key.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <ModalShell
      isOpen={isOpen}
      title="Settings"
      description="The engine API key this machine uses. Your documents never leave it either way."
      onCancel={saving ? undefined : onClose}
      initialFocusRef={input}
    >
      <form onSubmit={save}>
        <div className="mt-5 rounded-lg border border-border bg-secondary px-3 py-2.5">
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Current key
          </p>

          <code className="mt-1 block font-mono text-xs text-foreground">
            {settings?.api_key_configured
              ? settings.api_key_masked
              : 'None configured'}
          </code>
        </div>

        <label
          htmlFor="api-key"
          className="mb-1.5 mt-5 block text-xs font-medium text-muted-foreground"
        >
          {settings?.api_key_configured ? 'Replace with' : 'API key'}
        </label>

        <input
          ref={input}
          id="api-key"
          name="engine-api-key-hidden"
          type="password"
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
          placeholder="krish_..."
          autoComplete="new-password"
          spellCheck="false"
          disabled={saving}
          className="w-full rounded-lg border border-input bg-background px-3 py-2 font-mono text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-ring disabled:opacity-60"
        />

        {error && (
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
            {error}
          </p>
        )}

        {saved && !error && (
          <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
            <Check className="size-3.5" />
            Verified against the engine and saved.
          </p>
        )}

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="rounded-lg border border-border bg-secondary px-4 py-2 text-sm font-medium text-secondary-foreground transition-colors hover:bg-accent disabled:opacity-50"
          >
            Close
          </button>

          <button
            type="submit"
            disabled={!apiKey.trim() || saving}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {saving && <Loader2 className="size-4 animate-spin" />}
            {saving ? 'Verifying...' : 'Save'}
          </button>
        </div>
      </form>
    </ModalShell>
  );
};

export default SettingsModal;
