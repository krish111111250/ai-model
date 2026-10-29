import { lazy, Suspense, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  ArrowRight,
  Check,
  Cpu,
  Database,
  FileText,
  Search,
  Server,
  Workflow,
} from 'lucide-react';
import { toast } from 'sonner';
import { updateAccount, useAccount } from '@/hooks/useAccount';
import { loadRazorpay } from '@/lib/razorpay';
import { cloud } from '@/services/api';

// three.js is ~600KB; it loads only once the landing page renders this.
const ArchitectureVisualizer = lazy(() => import('./ArchitectureVisualizer'));

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

const LOCAL_ENGINE_PARTS = [
  {
    icon: Cpu,
    title: 'Ollama LLM Core',
    detail: 'The language model runs on your CPU or GPU. No API calls out.',
  },
  {
    icon: Server,
    title: 'FastAPI Gateway',
    detail: 'API key authentication and per-key rate limiting, on localhost.',
  },
  {
    icon: Workflow,
    title: 'LangChain Orchestration',
    detail: 'Turns your question and its snippets into a grounded answer.',
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
    // Bought through Razorpay rather than linked: see startCheckout.
    checkout: true,
  },
];

// Plans the engine treats as paid. Matches UNLIMITED_PLANS on the server;
// the Enterprise card sells the engine's 'pro' plan.
const PAID_PLANS = new Set(['pro']);

// Matches the app's card surface, so the checkout header reads as ours.
const CHECKOUT_THEME_COLOR = '#111111';

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
  const navigate = useNavigate();
  const { account, signedIn } = useAccount();
  const [checkingOut, setCheckingOut] = useState(false);

  const onPaidPlan = PAID_PLANS.has(account?.plan);

  // The engine fixes the amount on the order and grants the plan only after
  // verifying Razorpay's signature; this page just opens checkout between
  // the two.
  const startCheckout = async () => {
    if (!signedIn) {
      navigate('/login');
      return;
    }

    if (checkingOut || onPaidPlan) return;

    setCheckingOut(true);

    try {
      const [Razorpay, order] = await Promise.all([
        loadRazorpay(),
        cloud.createRazorpayOrder(),
      ]);

      const checkout = new Razorpay({
        key: order.key_id,
        order_id: order.order_id,
        amount: order.amount,
        currency: order.currency,
        name: 'Krish AI',
        description: 'Enterprise plan - 1 month',
        prefill: { email: account?.email || '' },
        theme: { color: CHECKOUT_THEME_COLOR },
        handler: async (payment) => {
          try {
            const result = await cloud.verifyRazorpayPayment(payment);

            updateAccount({ plan: result.plan });
            toast.success('Payment received', {
              description: 'Your account is upgraded. No monthly limit applies.',
            });
            navigate('/dashboard');
          } catch (problem) {
            console.error('Payment verification failed:', problem);
            toast.error('Payment not confirmed', {
              description:
                problem.message ||
                'If you were charged, the plan updates once Razorpay confirms it.',
            });
          } finally {
            setCheckingOut(false);
          }
        },
        modal: { ondismiss: () => setCheckingOut(false) },
      });

      // Checkout stays open on a failed attempt so the user can retry; this
      // only says why it failed.
      checkout.on('payment.failed', (response) => {
        toast.error('Payment failed', {
          description: response.error?.description || 'Try another method.',
        });
      });

      checkout.open();
    } catch (problem) {
      console.error('Failed to start checkout:', problem);
      toast.error('Could not start checkout', { description: problem.message });
      setCheckingOut(false);
    }
  };

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
            Your documents never leave your machine. Powered by local LLMs
            (Ollama) and on-premise vector storage (Chroma), our RAG engine
            processes everything completely offline. Zero cloud API calls, 100%
            data privacy.
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
            Runs entirely on your hardware · Zero external server dependencies
          </p>
        </section>

        {/* ---------- Pipeline visual ---------- */}
        <section className="w-full max-w-5xl mx-auto my-16 px-4">
          <h2 className="text-3xl font-bold text-white text-center mb-8">
            How Our Air-Gapped Engine Works
          </h2>
          <Suspense
            fallback={
              <div className="h-96 w-full rounded-2xl bg-[#0a0a0a] border border-gray-800 animate-pulse" />
            }
          >
            <ArchitectureVisualizer />
          </Suspense>
        </section>

        {/* ---------- Architecture ---------- */}
        <section className="border-t border-border py-16 sm:py-20">
          <h2 className="text-xl font-semibold tracking-tight sm:text-2xl">
            Where your data actually sits
          </h2>

          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground">
            Your host machine does all the heavy lifting. Documents, vector
            embeddings, and LLM inference stay entirely on your secure local
            environment.
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

            {/* What passes between the two local processes, stated plainly. */}
            <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border px-5 py-6 lg:w-56">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Stays on localhost
              </p>

              <div className="w-full rounded-lg bg-secondary px-3 py-2 text-center">
                <p className="text-xs font-medium text-foreground">
                  Question + 3 snippets
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
                Nothing leaves the machine: not the file, the index, or your chat history.
              </p>
            </div>

            <div className="rounded-xl border border-border bg-card p-6">
              <div className="mb-5 flex items-center justify-between">
                <p className="text-sm font-semibold">Local AI Engine</p>
                <span className="rounded-md bg-secondary px-2 py-0.5 text-[11px] text-muted-foreground">
                  localhost:8000
                </span>
              </div>

              <PartList parts={LOCAL_ENGINE_PARTS} />
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

                {plan.checkout ? (
                  <button
                    type="button"
                    onClick={startCheckout}
                    disabled={checkingOut || onPaidPlan}
                    className={`mt-7 rounded-lg px-4 py-2.5 text-center text-sm font-medium transition-opacity hover:opacity-90 disabled:cursor-default disabled:opacity-60 disabled:hover:opacity-60 ${
                      plan.featured
                        ? 'bg-background text-foreground'
                        : 'bg-primary text-primary-foreground'
                    }`}
                  >
                    {onPaidPlan
                      ? 'Current Plan'
                      : checkingOut
                        ? 'Opening checkout...'
                        : plan.cta}
                  </button>
                ) : (
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
                )}
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
