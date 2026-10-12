import { useRef, useState } from 'react';
import {
  FileText,
  Loader2,
  MessageSquare,
  Plus,
  Settings,
  Trash2,
  Upload,
} from 'lucide-react';
import ConfirmModal from '@/components/ui/ConfirmModal';
import SettingsModal from '@/components/ui/SettingsModal';
import { api } from '@/services/api';

/**
 * Left rail: conversations on top, indexed documents below.
 *
 * Layout only for now. Each list renders from a placeholder array so the
 * spacing, truncation and scroll behaviour can be judged before any data is
 * wired in - a list that looks right with three items often breaks with
 * thirty, and that is cheaper to find now.
 */
const PLACEHOLDER_CHATS = [
  'Leave policy questions',
  'Expense claim deadlines',
  'Security rules summary',
];

const SectionLabel = ({ children }) => (
  <p className="px-3 pb-1 pt-4 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
    {children}
  </p>
);

const LocalSidebar = ({
  userId,
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

  const handleUpload = async (event) => {
    const file = event.target.files?.[0];

    if (!file) return;

    setUploading(true);
    setNotice('');

    try {
      const result = await api.uploadDocument(file, userId);

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
      await api.deleteDocument(doc.document_id, userId);
      await onDocumentsChanged?.();
    } catch (problem) {
      setNotice(problem.message || 'Delete failed.');
    } finally {
      setDeletingId('');
      setDocToDelete(null);
    }
  };

  return (
    <aside className="hidden w-72 shrink-0 flex-col border-r border-border bg-card md:flex">
      <div className="flex items-center gap-2 border-b border-border px-4 py-4">
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
      </div>

      {/* The two lists share the scroll container, so a long chat history
          does not push the document list out of reach. */}
      <div className="min-h-0 flex-1 overflow-y-auto pb-4">
        <SectionLabel>Chats</SectionLabel>

        <nav className="space-y-0.5 px-2">
          {PLACEHOLDER_CHATS.map((title) => (
            <button
              key={title}
              type="button"
              className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
            >
              <MessageSquare className="size-4 shrink-0" />
              <span className="truncate">{title}</span>
            </button>
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
        <button
          type="button"
          onClick={() => setSettingsOpen(true)}
          className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
        >
          <Settings className="size-4" />
          Settings
        </button>
      </div>

      {/* Rendered here for readability; ModalShell portals it to document.body,
          so it is not clipped by the scroll column above. */}
      <SettingsModal
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
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
