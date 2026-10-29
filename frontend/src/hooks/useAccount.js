import { useEffect, useState } from 'react';
import { cloud, session } from '@/services/api';

/**
 * The signed-in cloud account.
 *
 * Cached at module level so several components can ask for it without each
 * firing its own /v1/auth/me. The dashboard and the document manager both
 * need the identity, and two requests for one answer is two chances for them
 * to disagree.
 */
let cached = null;
let inFlight = null;

const fetchAccount = () => {
  if (cached) return Promise.resolve(cached);

  if (!inFlight) {
    inFlight = cloud
      .me()
      .then((account) => {
        cached = account;
        return account;
      })
      .finally(() => {
        inFlight = null;
      });
  }

  return inFlight;
};

/**
 * Merge a change into the cached account - a plan bought on the pricing page,
 * say - so the next page to mount shows it without refetching /v1/auth/me.
 */
export const updateAccount = (changes) => {
  if (cached) cached = { ...cached, ...changes };
};

/** Drop the cache on sign-out, so the next sign-in does not inherit it. */
export const clearAccount = () => {
  cached = null;
};

export function useAccount() {
  // No token means no account to fetch, and no point rendering a spinner for
  // a request that will not be made.
  const hasSession = Boolean(session.get());

  const [account, setAccount] = useState(cached);
  const [loading, setLoading] = useState(hasSession && !cached);

  useEffect(() => {
    if (!hasSession || cached) return;

    let cancelled = false;

    const load = async () => {
      try {
        const next = await fetchAccount();

        if (!cancelled) setAccount(next);
      } catch {
        // A 401 is handled by the response interceptor, which clears the
        // session and sends the browser to /login.
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();

    return () => {
      cancelled = true;
    };
  }, [hasSession]);

  return { account, loading, signedIn: hasSession };
}
