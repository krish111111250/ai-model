import { useCallback, useEffect, useRef, useState } from 'react';
import {
  CheckCircle2,
  FileText,
  Loader2,
  Trash2,
  Upload,
  WifiOff,
} from 'lucide-react';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { useAccount } from '@/hooks/useAccount';
import { api } from '@/services/api';

/** "2026-10-09T17:40:40" -> "2026-10-09". Null stays null. */
const asDate = (value) => (value ? String(value).slice(0, 10) : null);

/** 0 means the document predates size tracking, not that the file was empty. */
const asSize = (bytes) => {
  if (!bytes) return '--';

  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let unit = 0;

  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }

  return `${value < 10 && unit > 0 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
};

const STATUS = {
  ready: { label: 'Indexed', icon: CheckCircle2 },
  indexing: { label: 'Indexing', icon: Loader2 },
  empty: { label: 'No text found', icon: FileText },
};

/**
 * Upload and manage the documents this machine can answer questions about.
 *
 * Talks to the local gateway on port 8001, not the cloud engine. That is the
 * whole architecture: the file is read, split and embedded here, and only the
 * few chunks a question matches are ever sent anywhere. An endpoint on the
 * engine would mean uploading the document itself, which is the one thing
 * this product promises not to do.
 */
const DocumentManager = () => {
  const fileInput = useRef(null);

  // The gateway stores documents under whatever id it is given, so this is
  // the key the whole list is scoped by. user_id rather than email: it is
  // stable even if the address on the account ever changes.
  const { account, loading: accountLoading, signedIn } = useAccount();
  const userId = account?.user_id || '';

  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [offline, setOffline] = useState(false);
  const [docToDelete, setDocToDelete] = useState(null);

  const loadDocuments = useCallback(async () => {
    // Guard rather than default: sending an empty or undefined id would read
    // and write under a different scope than the one the user owns.
    if (!userId) return;

    try {
      const data = await api.getDocuments(userId);

      setDocuments(data.documents || []);
      setOffline(false);
      setError('');
    } catch (problem) {
      // The dashboard is reachable without the local app running, so this is
      // an expected state rather than a failure to report as an error.
      setOffline(problem.status === 500 || problem.status === 0);
      setError(problem.message || 'Could not load documents.');
    }
    // userId belongs here: without it this callback keeps closing over the
    // empty id from the first render, so the effect never re-runs once the
    // account arrives and the list stays empty.
  }, [userId]);

  useEffect(() => {
    // Wait for the identity before the first read. Without this the list
    // would load empty, then reload once the account arrived.
    if (accountLoading) return;

    const bootstrap = async () => {
      await loadDocuments();
      setLoading(false);
    };

    bootstrap();
  }, [accountLoading, loadDocuments]);

  const handleUpload = async (event) => {
    const file = event.target.files?.[0];

    if (!file || !userId) return;

    setUploading(true);
    setNotice('');
    setError('');

    try {
      const result = await api.uploadDocument(file, userId);

      await loadDocuments();

      setNotice(
        result.semantic_pending
          ? `${result.file_name} indexed. Semantic search is still initializing.`
          : `${result.file_name}: ${result.total_chunks} chunks from ${result.pages} page(s).`
      );
    } catch (problem) {
      // 409 is the gateway saying this exact file is already indexed, which
      // is worth saying plainly rather than reporting as a failure.
      if (problem.status === 409) {
        setNotice('Already indexed - it is in the list below.');
      } else {
        setError(problem.message || 'Upload failed.');
      }
    } finally {
      setUploading(false);

      // Clear the input, or picking the same file again fires no change event.
      if (fileInput.current) fileInput.current.value = '';
    }
  };

  const confirmDelete = async () => {
    const doc = docToDelete;

    if (!doc || deletingId || !userId) return;

    setDeletingId(doc.document_id);
    setError('');

    try {
      await api.deleteDocument(doc.document_id, userId);
      await loadDocuments();
      setNotice(`${doc.file_name} removed from this machine.`);
    } catch (problem) {
      setError(problem.message || 'Delete failed.');
    } finally {
      setDeletingId('');
      setDocToDelete(null);
    }
  };

  return (
    <section>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold tracking-tight">Documents</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Indexed on this machine. The file itself is never uploaded.
          </p>
        </div>

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
          disabled={uploading || offline || !userId}
          className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {uploading ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Upload className="size-4" />
          )}
          {uploading ? 'Indexing...' : 'Upload document'}
        </button>
      </div>

      {accountLoading && (
        <div className="mt-5 flex items-center justify-center rounded-xl border border-border py-10">
          <Loader2 className="size-4 animate-spin text-muted-foreground" />
        </div>
      )}

      {!accountLoading && !signedIn && (
        <div className="mt-4 flex items-start gap-2.5 rounded-lg border border-border bg-card px-4 py-3">
          <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <div>
            <p className="text-sm font-medium">Sign in to see your documents</p>
            <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
              Documents are listed per account, so this needs a signed-in
              session.
            </p>
          </div>
        </div>
      )}

      {offline && (
        <div className="mt-4 flex items-start gap-2.5 rounded-lg border border-border bg-card px-4 py-3">
          <WifiOff className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <div>
            <p className="text-sm font-medium">Local app not running</p>
            <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
              Documents live on your machine, so this list comes from the
              gateway on port 8001. Start it with{' '}
              <code className="rounded bg-secondary px-1 py-0.5">./start.sh</code>{' '}
              and reload.
            </p>
          </div>
        </div>
      )}

      {error && !offline && (
        <p className="mt-4 rounded-lg border border-border bg-destructive px-4 py-2.5 text-sm text-destructive-foreground">
          {error}
        </p>
      )}

      {notice && (
        <p className="mt-4 rounded-lg border border-border bg-card px-4 py-2.5 text-sm text-muted-foreground">
          {notice}
        </p>
      )}

      {/* Scrolls sideways rather than forcing the page wide on a phone; the
          less critical columns drop out at sm and md first. */}
      <div
        className={`mt-5 overflow-x-auto rounded-xl border border-border ${
          accountLoading || !userId ? 'hidden' : ''
        }`}
      >
        <table className="w-full min-w-[32rem] text-left text-sm">
          <thead className="border-b border-border bg-card">
            <tr className="text-xs uppercase tracking-wider text-muted-foreground">
              <th className="px-5 py-3 font-medium">Filename</th>
              <th className="hidden px-5 py-3 font-medium sm:table-cell">Size</th>
              <th className="hidden px-5 py-3 font-medium md:table-cell">Uploaded</th>
              <th className="px-5 py-3 font-medium">Status</th>
              <th className="px-5 py-3 text-right font-medium">Actions</th>
            </tr>
          </thead>

          <tbody>
            {loading && (
              <tr>
                <td colSpan={5} className="px-5 py-10 text-center">
                  <Loader2 className="mx-auto size-4 animate-spin text-muted-foreground" />
                </td>
              </tr>
            )}

            {!loading && documents.length === 0 && (
              <tr>
                <td
                  colSpan={5}
                  className="px-5 py-10 text-center text-sm text-muted-foreground"
                >
                  {offline
                    ? 'Start the local app to see your documents.'
                    : 'No documents yet. Upload a PDF to ask questions about it.'}
                </td>
              </tr>
            )}

            {!loading &&
              documents.map((doc) => {
                const state = STATUS[doc.status] || STATUS.ready;
                const StateIcon = state.icon;
                const busy = deletingId === doc.document_id;

                return (
                  <tr
                    key={doc.document_id}
                    className="border-b border-border last:border-0 transition-colors hover:bg-accent"
                  >
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-2">
                        <FileText className="size-4 shrink-0 text-muted-foreground" />
                        <span
                          className="max-w-[16rem] truncate font-medium"
                          title={doc.file_name}
                        >
                          {doc.file_name}
                        </span>
                      </div>

                      <p className="mt-1 pl-6 text-[11px] text-muted-foreground">
                        {doc.pages} page{doc.pages === 1 ? '' : 's'} ·{' '}
                        {doc.total_chunks} chunks
                      </p>
                    </td>

                    <td className="hidden px-5 py-4 text-muted-foreground sm:table-cell">
                      {asSize(doc.size_bytes)}
                    </td>

                    <td className="hidden px-5 py-4 text-muted-foreground md:table-cell">
                      {asDate(doc.created_at) || '--'}
                    </td>

                    <td className="px-5 py-4">
                      <span className="inline-flex items-center gap-1.5 rounded-md bg-secondary px-2 py-1 text-[11px] text-muted-foreground">
                        <StateIcon
                          className={`size-3 ${
                            doc.status === 'indexing' ? 'animate-spin' : ''
                          }`}
                        />
                        {state.label}
                      </span>
                    </td>

                    <td className="px-5 py-4 text-right">
                      <button
                        type="button"
                        onClick={() => setDocToDelete(doc)}
                        disabled={busy}
                        aria-label={`Delete ${doc.file_name}`}
                        className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-100"
                      >
                        {busy ? (
                          <Loader2 className="size-4 animate-spin" />
                        ) : (
                          <Trash2 className="size-4" />
                        )}
                      </button>
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>

      {userId && !accountLoading && (
        <p className="mt-3 text-xs text-muted-foreground">
          Deleting a document removes its index from this machine. There is no
          server-side copy to restore from.
        </p>
      )}

      <ConfirmModal
        isOpen={Boolean(docToDelete)}
        title={`Delete ${docToDelete?.file_name || 'this document'}?`}
        description={`Its ${docToDelete?.total_chunks || 0} chunks are removed from this machine. Nothing was ever uploaded, so there is no copy to restore from.`}
        confirmText="Delete"
        onConfirm={confirmDelete}
        onCancel={() => setDocToDelete(null)}
        busy={Boolean(deletingId)}
      />
    </section>
  );
};

export default DocumentManager;
