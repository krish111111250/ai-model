import { useEffect, useRef, useState } from 'react';
import { Loader2, Search, WifiOff } from 'lucide-react';
import { api } from '../services/api';

const POLL_MS = 3000;

/**
 * Tells the user what the local AI is doing before it is fully ready.
 *
 * On a first run the gateway downloads its embedding model (~80MB) in the
 * background. Nothing is blocked while that happens - uploads work and
 * questions are answered by the keyword half of search - so this is a notice,
 * not a gate. Blocking the UI here would be the one thing guaranteed to make
 * it feel broken.
 *
 * With no colour to signal severity, the states separate by weight: the one
 * that stops you working inverts to a white bar, the ones you can work
 * through stay a quiet dark strip.
 */
const InitBanner = () => {
  const [status, setStatus] = useState(null);
  const timer = useRef(null);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      const next = await api.getGatewayStatus();

      if (cancelled) return;

      setStatus(next);

      // Stop polling once there is nothing left to wait for.
      const settled =
        next.status === 'ok' || next.semantic?.state === 'unavailable';

      if (!settled) {
        timer.current = setTimeout(poll, POLL_MS);
      }
    };

    poll();

    return () => {
      cancelled = true;
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  if (!status || status.status === 'ok') return null;

  if (status.status === 'offline') {
    return (
      <div className="flex items-start gap-2.5 border-b border-border bg-foreground px-4 py-2.5 text-background">
        <WifiOff className="mt-0.5 size-4 shrink-0" />
        <div className="min-w-0">
          <p className="text-sm font-medium">Local gateway not running</p>
          <p className="text-xs opacity-80">{status.message}</p>
        </div>
      </div>
    );
  }

  if (status.semantic?.state === 'unavailable') {
    return (
      <div className="flex items-start gap-2.5 border-b border-border bg-card px-4 py-2.5">
        <Search className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0">
          <p className="text-sm font-medium text-foreground">
            Keyword search only
          </p>
          <p className="text-xs text-muted-foreground">
            The semantic model could not be loaded, so answers match on exact
            words. Everything still runs on this machine.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-2.5 border-b border-border bg-card px-4 py-2.5">
      <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin text-muted-foreground" />
      <div className="min-w-0">
        <p className="text-sm font-medium text-foreground">
          Preparing semantic search
        </p>
        <p className="text-xs text-muted-foreground">
          Downloading the language model once (~80 MB). You can upload a PDF and
          ask questions now - answers get sharper when this finishes.
        </p>
      </div>
    </div>
  );
};

export default InitBanner;
