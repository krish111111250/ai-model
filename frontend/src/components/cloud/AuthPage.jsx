import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { cloud, session } from '@/services/api';

/**
 * lucide dropped its brand icons in v1, so the mark is inlined. Keeping the
 * real logo matters on an OAuth button: a generic icon makes people hesitate
 * about where their credentials are going.
 */
const GitHubMark = ({ className }) => (
  <svg viewBox="0 0 16 16" aria-hidden="true" fill="currentColor" className={className}>
    <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.07-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.42 7.42 0 0 1 2-.27c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.15 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A7.995 7.995 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
  </svg>
);

const GoogleMark = ({ className }) => (
  <svg viewBox="0 0 18 18" aria-hidden="true" className={className}>
    <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.71-1.57 2.68-3.89 2.68-6.62Z" />
    <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.81.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.34A9 9 0 0 0 9 18Z" />
    <path fill="#FBBC05" d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.94H.96a9 9 0 0 0 0 8.12l3.01-2.34Z" />
    <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.59A8.99 8.99 0 0 0 .96 4.94l3.01 2.34C4.68 5.16 6.66 3.58 9 3.58Z" />
  </svg>
);

const MARKS = { github: GitHubMark, google: GoogleMark };

// Google only for the MVP. The engine will offer any provider it has
// credentials for, so this is the second gate: a half-configured GitHub app
// would otherwise put a button on this page that leads nowhere. Add 'github'
// back once that flow has been through a real round trip.
const ENABLED_PROVIDERS = new Set(['google']);

/** One value out of the URL fragment, which is where the callback leaves it. */
const readFragment = (key) => {
  try {
    return new URLSearchParams(window.location.hash.slice(1)).get(key) || '';
  } catch {
    return '';
  }
};

const AuthPage = () => {
  const navigate = useNavigate();

  const [mode, setMode] = useState('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [providers, setProviders] = useState([]);

  // The OAuth callback sends the browser back here with the outcome in the
  // URL fragment. Both are read once, during the first render, so the value
  // is on screen immediately and no effect has to set state to produce it.
  const [oauthToken] = useState(() => readFragment('token'));
  const [error, setError] = useState(() => readFragment('error'));

  const signingIn = mode === 'signin';

  useEffect(() => {
    // Strip the fragment either way: a session token has no business staying
    // in the address bar, where it can be copied or bookmarked.
    if (oauthToken || error) {
      window.history.replaceState(null, '', window.location.pathname);
    }

    if (oauthToken) {
      session.set(oauthToken);
      navigate('/dashboard', { replace: true });
    }
    // Deliberately mount-only: this consumes a one-time value, and re-running
    // it after the user types into the form would strip nothing and navigate
    // nowhere.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const load = async () => {
      const offered = await cloud.providers();

      setProviders(offered.filter((provider) => ENABLED_PROVIDERS.has(provider.id)));
    };

    load();
  }, []);

  const submit = async (event) => {
    event.preventDefault();

    if (submitting) return;

    setSubmitting(true);
    setError('');

    try {
      // Both store the session token on success, so the dashboard is
      // reachable the moment this resolves.
      if (signingIn) {
        await cloud.login(email, password);
      } else {
        await cloud.signup(email, password);
      }

      navigate('/dashboard', { replace: true });
    } catch (problem) {
      setError(problem.message || 'Something went wrong.');
      setSubmitting(false);
    }
  };

  const switchMode = () => {
    setMode(signingIn ? 'signup' : 'signin');
    setError('');
  };

  const inputClass =
    'w-full rounded-lg border border-input bg-transparent px-3 py-2 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-ring';

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-6 py-12 text-foreground">
      <Link to="/" className="text-sm font-semibold tracking-tight">
        Krish AI
      </Link>

      <div className="mt-8 w-full max-w-sm rounded-xl border border-border bg-card p-6 sm:p-7">
        <h1 className="text-lg font-semibold tracking-tight">
          {signingIn ? 'Welcome back' : 'Create an account'}
        </h1>

        <p className="mt-1.5 text-sm text-muted-foreground">
          {signingIn
            ? 'Sign in to manage your API keys and usage.'
            : 'Start with 100 queries a month, no card required.'}
        </p>

        {providers.length > 0 && (
          <>
            <div className="mt-6 space-y-2">
              {providers.map((provider) => {
                const Mark = MARKS[provider.id];

                return (
                  <button
                    key={provider.id}
                    type="button"
                    onClick={() => cloud.startOAuth(provider.id)}
                    className="flex w-full items-center justify-center gap-2 rounded-lg border border-border bg-secondary px-3 py-2 text-sm font-medium text-secondary-foreground transition-colors hover:bg-accent"
                  >
                    {Mark && <Mark className="size-4" />}
                    Continue with {provider.label}
                  </button>
                );
              })}
            </div>

            <div className="my-5 flex items-center gap-3">
              <span className="h-px flex-1 bg-border" />
              <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
                or
              </span>
              <span className="h-px flex-1 bg-border" />
            </div>
          </>
        )}

        <form
          onSubmit={submit}
          className={`space-y-4 ${providers.length === 0 ? 'mt-6' : ''}`}
        >
          <div>
            <label
              htmlFor="email"
              className="mb-1.5 block text-xs font-medium text-muted-foreground"
            >
              Email
            </label>

            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@company.com"
              className={inputClass}
            />
          </div>

          <div>
            <div className="mb-1.5 flex items-baseline justify-between">
              <label
                htmlFor="password"
                className="text-xs font-medium text-muted-foreground"
              >
                Password
              </label>

              {signingIn && (
                <button
                  type="button"
                  className="text-xs text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline"
                >
                  Forgot?
                </button>
              )}
            </div>

            <input
              id="password"
              type="password"
              required
              minLength={8}
              /* Tells a password manager whether to offer a saved password or
                 generate a new one - it guesses wrong without this. */
              autoComplete={signingIn ? 'current-password' : 'new-password'}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={signingIn ? 'Your password' : 'At least 8 characters'}
              className={inputClass}
            />
          </div>

          {error && (
            <p className="rounded-lg border border-border bg-destructive px-3 py-2 text-xs leading-relaxed text-destructive-foreground">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            {submitting && <Loader2 className="size-4 animate-spin" />}
            {signingIn ? 'Sign in' : 'Create account'}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-muted-foreground">
          {signingIn ? "Don't have an account?" : 'Already have an account?'}{' '}
          <button
            type="button"
            onClick={switchMode}
            className="font-medium text-foreground underline-offset-4 transition-colors hover:underline"
          >
            {signingIn ? 'Sign up' : 'Sign in'}
          </button>
        </p>
      </div>

      <p className="mt-6 max-w-sm text-center text-xs leading-relaxed text-muted-foreground">
        An account manages keys and billing only. Your documents stay on your
        machine either way.
      </p>
    </div>
  );
};

export default AuthPage;
