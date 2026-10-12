import { Link } from 'react-router-dom';
import {
  ArrowRight,
  Ban,
  Check,
  Cpu,
  Database,
  FileText,
  KeyRound,
  Search,
} from 'lucide-react';

const LOCAL_PARTS = [
  {
    icon: FileText,
    title: 'Your PDFs',
    detail: 'Read and split on this machine. The file is never uploaded.',
  },
  {
    icon: Database,
    title: 'Vector index',
    detail: 'Embeddings stored in ~/.krish. Yours to delete at any time.',
  },
  {
    icon: Search,
    title: 'Hybrid retrieval',
    detail: 'Keyword and semantic search, fused, running locally.',
  },
];

const CLOUD_PARTS = [
  {
    icon: Cpu,
    title: 'Stateless LLM',
    detail: 'Turns your question and its snippets into a grounded answer.',
  },
  {
    icon: KeyRound,
    title: 'Keys and limits',
    detail: 'API key authentication and per-key rate limiting.',
  },
  {
    icon: Ban,
    title: 'Keeps nothing',
    detail: 'No documents, no vectors, no chat history. Only the key table.',
  },
];

const PLANS = [
  {
    name: 'Developer',
    price: 'Free',
    cadence: '',
    summary: 'For trying it on your own documents.',
    features: ['100 queries per month', 'Local RAG UI', 'Hybrid search', 'One API key'],
    cta: 'Start free',
    to: '/login',
    featured: false,
  },
  {
    name: 'Enterprise',
    price: '$20',
    cadence: '/month',
    summary: 'For teams whose documents cannot leave their machines.',
    features: [
      'Unlimited queries',
      'API key access',
      'Rate limiting per key',
      'Multiple keys per tenant',
    ],
    cta: 'Get started',
    to: '/login',
    featured: true,
  },
];

const PartList = ({ parts }) => (
  <ul className="space-y-4">
    {parts.map(({ icon: Icon, title, detail }) => (
      <li key={title} className="flex gap-3">
        <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div>
          <p className="text-sm font-medium text-foreground">{title}</p>
          <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
            {detail}
          </p>
        </div>
      </li>
    ))}
  </ul>
);

const LandingPage = () => {
  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Temporary nav, kept at the top so the routes stay clickable. */}
      <header className="sticky top-0 z-10 border-b border-border bg-background/80 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center gap-4 px-6 py-3.5">
          <span className="text-sm font-semibold tracking-tight">Krish AI</span>

          <nav className="ml-auto flex items-center gap-1">
            <Link
              to="/chat"
              className="rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              Chat
            </Link>
            <Link
              to="/dashboard"
              className="rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              Dashboard
            </Link>
            <Link
              to="/login"
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90"
            >
              Sign in
            </Link>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6">
        {/* ---------- Hero ---------- */}
        <section className="py-20 sm:py-28">
          <h1 className="max-w-3xl text-4xl font-semibold leading-[1.05] tracking-tight sm:text-6xl">
            Private RAG AI.
            <br />
            <span className="text-muted-foreground">100% Data Privacy.</span>
          </h1>

          <p className="mt-6 max-w-2xl text-base leading-relaxed text-muted-foreground sm:text-lg">
            Your documents are indexed and searched on your own machine. Only
            your question and the few snippets that match it reach the cloud,
            where a stateless model turns them into a grounded answer and keeps
            nothing.
          </p>

          <div className="mt-9 flex flex-wrap items-center gap-3">
            <Link
              to="/chat"
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90"
            >
              Open the local app
              <ArrowRight className="size-4" />
            </Link>

            <Link
              to="/dashboard"
              className="rounded-lg border border-border bg-secondary px-5 py-2.5 text-sm font-medium text-secondary-foreground transition-colors hover:bg-accent"
            >
              View dashboard
            </Link>
          </div>

          <p className="mt-6 text-xs text-muted-foreground">
            Runs on your hardware · No document storage on our servers
          </p>
        </section>

        {/* ---------- Architecture ---------- */}
        <section className="border-t border-border py-16 sm:py-20">
          <h2 className="text-xl font-semibold tracking-tight sm:text-2xl">
            Where your data actually sits
          </h2>

          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground">
            The split is the product. Everything that touches a document runs
            locally; the cloud only generates.
          </p>

          <div className="mt-10 grid items-stretch gap-4 lg:grid-cols-[1fr_auto_1fr]">
            <div className="rounded-xl border border-border bg-card p-6">
              <div className="mb-5 flex items-center justify-between">
                <p className="text-sm font-semibold">Local machine</p>
                <span className="rounded-md bg-secondary px-2 py-0.5 text-[11px] text-muted-foreground">
                  localhost:8001
                </span>
              </div>

              <PartList parts={LOCAL_PARTS} />
            </div>

            {/* The boundary, stated plainly: naming exactly what crosses it is
                more convincing than a claim that nothing does. */}
            <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border px-5 py-6 lg:w-56">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Crosses the wire
              </p>

              <div className="w-full rounded-lg bg-secondary px-3 py-2 text-center">
                <p className="text-xs font-medium text-foreground">
                  Question + 4 snippets
                </p>
                <ArrowRight className="mx-auto mt-1 size-3.5 text-muted-foreground" />
              </div>

              <div className="w-full rounded-lg bg-secondary px-3 py-2 text-center">
                <ArrowRight className="mx-auto mb-1 size-3.5 rotate-180 text-muted-foreground" />
                <p className="text-xs font-medium text-foreground">
                  Grounded answer
                </p>
              </div>

              <p className="text-center text-[11px] leading-relaxed text-muted-foreground">
                Never the file, the index, or your chat history.
              </p>
            </div>

            <div className="rounded-xl border border-border bg-card p-6">
              <div className="mb-5 flex items-center justify-between">
                <p className="text-sm font-semibold">Cloud</p>
                <span className="rounded-md bg-secondary px-2 py-0.5 text-[11px] text-muted-foreground">
                  stateless API
                </span>
              </div>

              <PartList parts={CLOUD_PARTS} />
            </div>
          </div>
        </section>

        {/* ---------- Pricing ---------- */}
        <section className="border-t border-border py-16 sm:py-20">
          <h2 className="text-xl font-semibold tracking-tight sm:text-2xl">
            Pricing
          </h2>

          <p className="mt-3 text-sm text-muted-foreground">
            The local app is the same on both plans.
          </p>

          <div className="mt-10 grid gap-4 sm:grid-cols-2">
            {PLANS.map((plan) => (
              <div
                key={plan.name}
                className={`flex flex-col rounded-xl border p-6 ${
                  plan.featured
                    ? 'border-foreground bg-foreground text-background'
                    : 'border-border bg-card'
                }`}
              >
                <p className="text-sm font-semibold">{plan.name}</p>

                <div className="mt-4 flex items-baseline gap-1">
                  <span className="text-3xl font-semibold tracking-tight">
                    {plan.price}
                  </span>
                  {plan.cadence && (
                    <span
                      className={`text-sm ${
                        plan.featured ? 'opacity-70' : 'text-muted-foreground'
                      }`}
                    >
                      {plan.cadence}
                    </span>
                  )}
                </div>

                <p
                  className={`mt-3 text-xs leading-relaxed ${
                    plan.featured ? 'opacity-80' : 'text-muted-foreground'
                  }`}
                >
                  {plan.summary}
                </p>

                <ul className="mt-6 flex-1 space-y-2.5">
                  {plan.features.map((feature) => (
                    <li key={feature} className="flex items-center gap-2 text-sm">
                      <Check
                        className={`size-4 shrink-0 ${
                          plan.featured ? '' : 'text-muted-foreground'
                        }`}
                      />
                      {feature}
                    </li>
                  ))}
                </ul>

                <Link
                  to={plan.to}
                  className={`mt-7 rounded-lg px-4 py-2.5 text-center text-sm font-medium transition-opacity hover:opacity-90 ${
                    plan.featured
                      ? 'bg-background text-foreground'
                      : 'bg-primary text-primary-foreground'
                  }`}
                >
                  {plan.cta}
                </Link>
              </div>
            ))}
          </div>
        </section>
      </main>

      <footer className="border-t border-border py-8">
        <p className="mx-auto max-w-5xl px-6 text-xs text-muted-foreground">
          Krish AI · Documents stay on your machine
        </p>
      </footer>
    </div>
  );
};

export default LandingPage;
