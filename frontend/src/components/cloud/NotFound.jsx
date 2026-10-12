import { Link } from 'react-router-dom';

/** Catch-all, so a mistyped path is not a blank screen. */
const NotFound = () => {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-background px-6 text-foreground">
      <h1 className="text-2xl font-semibold tracking-tight">Page not found</h1>

      <Link
        to="/"
        className="mt-6 text-sm text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline"
      >
        Back home
      </Link>
    </main>
  );
};

export default NotFound;
