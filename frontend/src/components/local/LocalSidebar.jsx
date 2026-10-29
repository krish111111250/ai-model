import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  ChevronsUpDown,
  FileText,
  Loader2,
  LogOut,
  MessageSquare,
  MoreVertical,
  Pencil,
  Plus,
  Search,
  Settings,
  Share2,
  Sparkles,
  Trash2,
  Upload,
  UserPlus,
  X,
} from 'lucide-react';
import { toast } from 'sonner';
import ConfirmModal from '@/components/ui/ConfirmModal';
import PromptModal from '@/components/ui/PromptModal';
import SettingsModal from '@/components/ui/SettingsModal';
import { loadRazorpay } from '@/lib/razorpay';
import { api } from '@/services/api';

/**
 * Left rail: conversations on top, indexed documents below.
 *
 * Both lists come from the gateway's SQLite store, so what is shown here is
 * what survives a refresh.
 */

// Placeholder until the local app has sign-in of its own. The plan is not
// here: it is read from the engine, so it survives a reload.
const PROFILE = {
  name: 'Krishnan',
  email: 'ramanikrish133@gmail.com',
};

// The engine stores plans lowercase ('free', 'pro'); the badge shows them
// capitalised.
const planLabel = (plan) =>
  plan ? plan.charAt(0).toUpperCase() + plan.slice(1) : 'Free';

// Matches the app's card surface, so the checkout header reads as ours.
const CHECKOUT_THEME_COLOR = '#111111';

// Free reads as a quiet outline; any paid plan gets the filled badge.
const PLAN_BADGE_STYLES = {
  Free: 'border-border bg-transparent text-muted-foreground',
};

const PAID_BADGE_STYLE = 'border-transparent bg-primary text-primary-foreground';

const PlanBadge = ({ plan }) => (
  <span
    className={`shrink-0 rounded-full border px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider ${
      PLAN_BADGE_STYLES[plan] || PAID_BADGE_STYLE
    }`}
  >
    {plan}
  </span>
);

const SectionLabel = ({ children }) => (
  <p className="px-3 pb-1 pt-4 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
    {children}
  </p>
);

const MenuItem = ({ icon: Icon, children, onClick }) => (
  <button
    type="button"
    role="menuitem"
    onClick={onClick}
    className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:bg-accent focus-visible:text-accent-foreground focus-visible:outline-none"
  >
    <Icon className="size-4 shrink-0" />
    {children}
  </button>
);

const MENU_WIDTH = 208;
const MENU_HEIGHT = 140;

/**
 * Share / Rename / Delete for one chat row.
 *
 * Portalled and fixed-positioned from the trigger's rect: the chat list
 * scrolls, and an absolutely positioned menu inside it would scroll away or
 * get cut off at the bottom of the column. Any scroll or resize closes it
 * rather than leaving it floating over the wrong row.
 */
const ChatMenu = ({ chat, busy, onShare, onRename, onDelete }) => {
  const trigger = useRef(null);
  const menu = useRef(null);
  const [position, setPosition] = useState(null);

  const open = Boolean(position);

  useEffect(() => {
    if (!open) return undefined;

    const close = () => setPosition(null);

    const onPointerDown = (event) => {
      if (
        !menu.current?.contains(event.target) &&
        !trigger.current?.contains(event.target)
      ) {
        close();
      }
    };

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        close();
        trigger.current?.focus();
      }
    };

    menu.current?.querySelector('[role="menuitem"]')?.focus();

    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    window.addEventListener('resize', close);
    window.addEventListener('scroll', close, true);

    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('resize', close);
      window.removeEventListener('scroll', close, true);
    };
  }, [open]);

  const toggle = () => {
    if (open) {
      setPosition(null);
      return;
    }

    const rect = trigger.current.getBoundingClientRect();

    // Below the button by default; flipped above it near the bottom of the
    // window so the last few rows still get a usable menu.
    const top =
      rect.bottom + 4 + MENU_HEIGHT > window.innerHeight
        ? rect.top - 4 - MENU_HEIGHT
        : rect.bottom + 4;

    setPosition({
      top: Math.max(8, top),
      left: Math.max(8, Math.min(rect.left, window.innerWidth - MENU_WIDTH - 8)),
    });
  };

  const choose = (action) => () => {
    setPosition(null);
    action(chat);
  };

  return (
    <>
      <button
        ref={trigger}
        type="button"
        aria-label={`Options for ${chat.title}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={toggle}
        disabled={busy}
        className={`absolute right-1 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-muted-foreground transition-opacity hover:bg-background/60 hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100 disabled:opacity-100 ${
          open ? 'bg-background/60 text-foreground opacity-100' : 'opacity-0'
        }`}
      >
        {busy ? (
          <Loader2 className="size-3.5 animate-spin" />
        ) : (
          <MoreVertical className="size-3.5" />
        )}
      </button>

      {open &&
        createPortal(
          <div
            ref={menu}
            role="menu"
            style={{ top: position.top, left: position.left, width: MENU_WIDTH }}
            className="fixed z-50 rounded-xl border border-border bg-card p-1 shadow-xl shadow-black/40"
          >
            <MenuItem icon={Share2} onClick={choose(onShare)}>
              Share conversation
            </MenuItem>
            <MenuItem icon={Pencil} onClick={choose(onRename)}>
              Rename
            </MenuItem>

            <div className="my-1 border-t border-border" />

            <MenuItem icon={Trash2} onClick={choose(onDelete)}>
              Delete
            </MenuItem>
          </div>,
          document.body
        )}
    </>
  );
};

/**
 * Bottom-left profile trigger and the menu that floats above it.
 *
 * Positioned absolutely against the footer rather than portalled: the footer
 * sits outside the sidebar's scroll column, so nothing clips it there.
 */
const ProfileMenu = ({ plan, upgrading, onUpgrade, onOpenSettings }) => {
  const container = useRef(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return undefined;

    const onPointerDown = (event) => {
      if (!container.current?.contains(event.target)) setOpen(false);
    };

    const onKeyDown = (event) => {
      if (event.key === 'Escape') setOpen(false);
    };

    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);

    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const choose = (action) => () => {
    setOpen(false);
    action?.();
  };

  const avatar = (
    <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
      {PROFILE.name.charAt(0)}
    </span>
  );

  return (
    <div ref={container} className="relative">
      {open && (
        <div
          role="menu"
          className="absolute bottom-full left-0 right-0 z-40 mb-2 rounded-2xl border border-border bg-card p-1.5 shadow-xl shadow-black/40"
        >
          <div className="flex items-center gap-3 px-3 py-3">
            {avatar}
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <p className="truncate text-sm font-semibold text-foreground">
                  {PROFILE.name}
                </p>
                <PlanBadge plan={plan} />
              </div>
              <p className="truncate text-xs text-muted-foreground">
                {PROFILE.email}
              </p>
            </div>
          </div>

          {plan === 'Free' && (
            <div className="px-1.5 pb-1.5">
              <button
                type="button"
                role="menuitem"
                onClick={choose(onUpgrade)}
                disabled={upgrading}
                className="flex w-full items-center gap-3 rounded-lg bg-primary px-3 py-2 text-left text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-wait disabled:opacity-70"
              >
                {upgrading ? (
                  <Loader2 className="size-4 shrink-0 animate-spin" />
                ) : (
                  <Sparkles className="size-4 shrink-0" />
                )}
                <span className="flex-1">
                  {upgrading ? 'Opening checkout...' : 'Upgrade to Pro'}
                </span>
                <span className="text-xs font-normal opacity-70">₹1600/mo</span>
              </button>
            </div>
          )}

          <div className="my-1 border-t border-border" />

          <MenuItem icon={Settings} onClick={choose(onOpenSettings)}>
            Settings
          </MenuItem>
          <MenuItem icon={UserPlus} onClick={choose()}>
            Add another account
          </MenuItem>

          <div className="my-1 border-t border-border" />

          <MenuItem icon={LogOut} onClick={choose()}>
            Sign out
          </MenuItem>
        </div>
      )}

      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className={`flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-accent ${
          open ? 'bg-accent' : ''
        }`}
      >
        {avatar}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground">
            {PROFILE.name}
          </p>
          <p className="truncate text-[11px] text-muted-foreground">
            {plan} plan
          </p>
        </div>
        <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" />
      </button>
    </div>
  );
};

const LocalSidebar = ({
  isOpen = true,
  documents,
  selectedDocumentId,
  onSelectDocument,
  onDocumentsChanged,
  onNewChat,
}) => {
  const fileInput = useRef(null);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState('');
  const [notice, setNotice] = useState('');
  const [docToDelete, setDocToDelete] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [chats, setChats] = useState([]);
  const [deletingChatId, setDeletingChatId] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [chatToRename, setChatToRename] = useState(null);
  const [renaming, setRenaming] = useState(false);
  const [plan, setPlan] = useState('Free');
  const [upgrading, setUpgrading] = useState(false);

  const query = searchQuery.trim().toLowerCase();
  const visibleChats = query
    ? chats.filter((chat) => chat.title.toLowerCase().includes(query))
    : chats;

  useEffect(() => {
    const loadChats = async () => {
      try {
        const data = await api.getChatSessions();

        setChats(
          (data.sessions || []).map((session) => ({
            id: session.session_id,
            title: session.title || 'Untitled chat',
          }))
        );
      } catch (problem) {
        console.error('Failed to load chats:', problem);
      }
    };

    loadChats();
  }, []);

  useEffect(() => {
    const loadPlan = async () => {
      try {
        const data = await api.getBillingPlan();

        setPlan(planLabel(data.plan));
      } catch (problem) {
        // The badge falls back to Free; nothing else depends on this read.
        console.error('Failed to load plan:', problem);
      }
    };

    loadPlan();
  }, []);

  // The order is created on the engine, which fixes the amount; the browser
  // only opens checkout for it. The plan changes once the engine has
  // verified Razorpay's signature on the payment, not when checkout says so.
  const handleUpgrade = async () => {
    if (upgrading) return;

    setUpgrading(true);

    try {
      const [Razorpay, order] = await Promise.all([
        loadRazorpay(),
        api.createBillingOrder(),
      ]);

      const checkout = new Razorpay({
        key: order.key_id,
        order_id: order.order_id,
        amount: order.amount,
        currency: order.currency,
        name: 'Krish AI',
        description: 'Pro plan - 1 month',
        prefill: { name: PROFILE.name, email: PROFILE.email },
        theme: { color: CHECKOUT_THEME_COLOR },
        handler: async (payment) => {
          try {
            const result = await api.verifyBillingPayment(payment);

            setPlan(planLabel(result.plan));
            toast.success('Welcome to Pro', {
              description: 'Your plan is upgraded. No monthly limit applies.',
            });
          } catch (problem) {
            console.error('Payment verification failed:', problem);
            toast.error('Payment not confirmed', {
              description:
                problem.message ||
                'If you were charged, the plan updates once Razorpay confirms it.',
            });
          } finally {
            setUpgrading(false);
          }
        },
        modal: { ondismiss: () => setUpgrading(false) },
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
      setUpgrading(false);
    }
  };

  // The row goes only once the gateway confirms the delete, so a failure
  // leaves the chat visible instead of hiding something that still exists.
  const handleDeleteChat = async (chatId) => {
    if (deletingChatId) return;

    setDeletingChatId(chatId);

    try {
      await api.deleteChatSession(chatId);
      setChats((current) => current.filter((chat) => chat.id !== chatId));
    } catch (problem) {
      console.error('Failed to delete chat:', problem);
      toast.error('Delete failed', { description: problem.message });
    } finally {
      setDeletingChatId('');
    }
  };

  // No public link to share yet - everything stays on this machine - so
  // sharing copies the conversation as plain text instead.
  const handleShareChat = async (chat) => {
    try {
      const { messages = [] } = await api.getChatHistory(chat.id);

      if (messages.length === 0) {
        toast('Nothing to share yet', {
          description: 'This conversation has no messages.',
        });
        return;
      }

      const transcript = [
        chat.title,
        '',
        ...messages.map(
          (message) =>
            `${message.role === 'user' ? 'You' : 'Krish AI'}: ${message.content}`
        ),
      ].join('\n');

      await navigator.clipboard.writeText(transcript);
      toast.success('Conversation copied', {
        description: 'Paste it anywhere to share.',
      });
    } catch (problem) {
      console.error('Failed to share chat:', problem);
      toast.error('Share failed', {
        description: problem.message || 'Could not copy the conversation.',
      });
    }
  };

  const confirmRename = async (title) => {
    const chat = chatToRename;

    if (!chat || renaming) return;

    if (!title || title === chat.title) {
      setChatToRename(null);
      return;
    }

    setRenaming(true);

    try {
      const result = await api.renameChatSession(chat.id, title);

      setChats((current) =>
        current.map((item) =>
          item.id === chat.id ? { ...item, title: result.title } : item
        )
      );
      setChatToRename(null);
    } catch (problem) {
      console.error('Failed to rename chat:', problem);
      toast.error('Rename failed', { description: problem.message });
    } finally {
      setRenaming(false);
    }
  };

  const handleUpload = async (event) => {
    const file = event.target.files?.[0];

    if (!file) return;

    setUploading(true);
    setNotice('');

    try {
      const result = await api.uploadDocument(file);

      await onDocumentsChanged?.();
      onSelectDocument?.(result.document_id);

      setNotice(
        result.semantic_pending
          ? 'Indexed. Semantic search is still initializing.'
          : `Indexed ${result.total_chunks} chunks from ${result.pages} page(s).`
      );
    } catch (problem) {
      // 409 is the gateway saying this exact file is already indexed, which
      // is worth saying plainly rather than reporting as a failure.
      setNotice(
        problem.status === 409
          ? 'Already indexed - select it below.'
          : problem.message || 'Upload failed.'
      );
    } finally {
      setUploading(false);

      // Clear the input, or picking the same file again fires no change event.
      if (fileInput.current) fileInput.current.value = '';
    }
  };

  const confirmDelete = async () => {
    const doc = docToDelete;

    if (!doc || deletingId) return;

    setDeletingId(doc.document_id);
    setNotice('');

    try {
      await api.deleteDocument(doc.document_id);
      await onDocumentsChanged?.();
    } catch (problem) {
      setNotice(problem.message || 'Delete failed.');
    } finally {
      setDeletingId('');
      setDocToDelete(null);
    }
  };

  return (
    // The aside animates its width; the inner column keeps a fixed w-72, so
    // the contents slide out of view instead of reflowing as it narrows.
    <aside
      aria-hidden={!isOpen}
      inert={!isOpen}
      className={`hidden shrink-0 overflow-hidden bg-card transition-[width] duration-300 ease-in-out md:block ${
        isOpen ? 'w-72 border-r border-border' : 'w-0'
      }`}
    >
      <div className="flex h-full w-72 flex-col">
        {/* pl-14 leaves room for the layout's sidebar toggle, which sits over
            this corner. */}
        <div className="flex items-center gap-2 border-b border-border py-4 pl-14 pr-4">
          <img
            src="/krish-logo.png"
            alt="Krish AI"
            className="h-6 w-6 shrink-0 object-contain"
            onError={(event) => {
              event.currentTarget.style.display = 'none';
            }}
          />
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">Krish AI</p>
            <p className="truncate text-[11px] text-muted-foreground">
              Running on this machine
            </p>
          </div>
        </div>

        <div className="px-3 pt-3">
          <button
            type="button"
            onClick={onNewChat}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-border bg-secondary px-3 py-2 text-sm font-medium text-secondary-foreground transition-colors hover:bg-accent"
          >
            <Plus className="size-4" />
            New chat
          </button>

          {/* Outside the scroll column, so it stays put while the lists scroll. */}
          <div className="relative mt-3">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              type="search"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Escape') setSearchQuery('');
              }}
              placeholder="Search chats"
              aria-label="Search chats"
              autoComplete="off"
              spellCheck="false"
              className="w-full rounded-lg border border-border bg-background py-1.5 pl-8 pr-8 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-ring [&::-webkit-search-cancel-button]:hidden"
            />
            {searchQuery && (
              <button
                type="button"
                aria-label="Clear search"
                onClick={() => setSearchQuery('')}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground transition-colors hover:text-foreground"
              >
                <X className="size-3.5" />
              </button>
            )}
          </div>
        </div>

        {/* The two lists share the scroll container, so a long chat history
            does not push the document list out of reach. */}
        <div className="min-h-0 flex-1 overflow-y-auto pb-4">
          <SectionLabel>Chats</SectionLabel>

          {visibleChats.length === 0 && (
            <p className="px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
              {query ? `No chats match "${searchQuery.trim()}".` : 'No saved chats yet.'}
            </p>
          )}

          <nav className="space-y-0.5 px-2">
            {visibleChats.map((chat) => (
              <div key={chat.id} className="group relative">
                <button
                  type="button"
                  title={chat.title}
                  className="flex w-full items-center gap-2 rounded-md px-2 py-2 pr-9 text-left text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
                >
                  <MessageSquare className="size-4 shrink-0" />
                  <span className="truncate">{chat.title}</span>
                </button>

                <ChatMenu
                  chat={chat}
                  busy={deletingChatId === chat.id}
                  onShare={handleShareChat}
                  onRename={setChatToRename}
                  onDelete={(item) => handleDeleteChat(item.id)}
                />
              </div>
            ))}
          </nav>

          <SectionLabel>Documents</SectionLabel>

          <div className="px-2 pb-1">
            <input
              ref={fileInput}
              type="file"
              accept="application/pdf,.pdf"
              onChange={handleUpload}
              className="hidden"
            />

            <button
              type="button"
              onClick={() => fileInput.current?.click()}
              disabled={uploading}
              className="flex w-full items-center justify-center gap-2 rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground transition-colors hover:border-ring hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
            >
              {uploading ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Upload className="size-3.5" />
              )}
              {uploading ? 'Uploading...' : 'Upload PDF'}
            </button>

            {notice && (
              <p className="px-1 pt-2 text-[11px] leading-relaxed text-muted-foreground">
                {notice}
              </p>
            )}
          </div>

          {documents.length === 0 && !uploading && (
            <p className="px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
              Nothing indexed yet. Upload a PDF to ask questions about it.
            </p>
          )}

          <ul className="space-y-0.5 px-2">
            {documents.map((doc) => {
              const active = doc.document_id === selectedDocumentId;
              const deleting = deletingId === doc.document_id;

              return (
                <li key={doc.document_id} className="group relative">
                  <button
                    type="button"
                    onClick={() => onSelectDocument?.(doc.document_id)}
                    className={`flex w-full items-center gap-2 rounded-md px-2 py-2 pr-8 text-left text-sm transition-colors ${
                      active
                        ? 'bg-accent text-accent-foreground'
                        : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                    }`}
                  >
                    <FileText className="size-4 shrink-0" />
                    <span className="min-w-0 flex-1 truncate" title={doc.file_name}>
                      {doc.file_name}
                    </span>
                    <span className="shrink-0 text-[11px]">{doc.pages}p</span>
                  </button>

                  {/* Kept out of the select button: a delete nested inside a
                      clickable row fires both actions on one click. */}
                  <button
                    type="button"
                    aria-label={`Delete ${doc.file_name}`}
                    onClick={() => setDocToDelete(doc)}
                    disabled={deleting}
                    className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-1.5 text-muted-foreground opacity-0 transition-opacity hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100 disabled:opacity-100"
                  >
                    {deleting ? (
                      <Loader2 className="size-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="size-3.5" />
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>

        <div className="border-t border-border p-3">
          <ProfileMenu
            plan={plan}
            upgrading={upgrading}
            onUpgrade={handleUpgrade}
            onOpenSettings={() => setSettingsOpen(true)}
          />
        </div>
      </div>

      {/* Rendered here for readability; ModalShell portals it to document.body,
          so it is not clipped by the scroll column above. */}
      <SettingsModal
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />

      <PromptModal
        isOpen={Boolean(chatToRename)}
        title="Rename conversation"
        defaultValue={chatToRename?.title || ''}
        placeholder="Conversation name"
        confirmText="Rename"
        onConfirm={confirmRename}
        onCancel={() => setChatToRename(null)}
        busy={renaming}
      />

      <ConfirmModal
        isOpen={Boolean(docToDelete)}
        title={`Delete ${docToDelete?.file_name || 'this document'}?`}
        description={`Its ${docToDelete?.total_chunks || 0} chunks are removed from this machine. Nothing was ever uploaded, so there is no copy to restore from.`}
        confirmText="Delete"
        onConfirm={confirmDelete}
        onCancel={() => setDocToDelete(null)}
        busy={Boolean(deletingId)}
      />
    </aside>
  );
};

export default LocalSidebar;
