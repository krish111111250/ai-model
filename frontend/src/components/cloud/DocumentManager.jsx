import { useCallback, useEffect, useRef, useState } from 'react';
import {
  CheckCircle2,
  FileText,
  Loader2,
  Trash2,
  Upload,
  WifiOff,
} from 'lucide-react';
import { toast } from 'sonner';
import ConfirmModal from '@/components/ui/ConfirmModal';
import EmptyState from '@/components/ui/EmptyState';
import { SkeletonRows } from '@/components/ui/Skeleton';
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
const DocumentManager = ({ onDocuments }) => {
  const fileInput = useRef(null);

  // No identity is passed to the gateway: it derives the owner from the API
  // key it holds, so a browser cannot ask for someone else's documents.

  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState('');
  const [error, setError] = useState('');
  const [offline, setOffline] = useState(false);
  const [docToDelete, setDocToDelete] = useState(null);

  const loadDocuments = useCallback(async () => {
    try {
      const data = await api.getDocuments();
      const list = data.documents || [];

      setDocuments(list);
      setOffline(false);
      setError('');

      // The playground needs the same list for its selector. Handing it up
      // beats a second request, and means an upload here refreshes it there.
      onDocuments?.(list);
    } catch (problem) {
      // The dashboard is reachable without the local app running, so this is
      // an expected state rather than a failure to report as an error.
      setOffline(problem.status === 500 || problem.status === 0);
      setError(problem.message || 'Could not load documents.');
    }
  }, [onDocuments]);

  useEffect(() => {
    const bootstrap = async () => {
      await loadDocuments();
      setLoading(false);
    };

    bootstrap();
  }, [loadDocuments]);

  const handleUpload = async (event) => {
    const file = event.target.files?.[0];

    if (!file) return;

    setUploading(true);
    setError('');

    try {
      const result = await api.uploadDocument(file);

      await loadDocuments();

      toast.success(`${result.file_name} indexed`, {
        description: result.semantic_pending
          ? 'Searchable now by keyword; semantic search is still initializing.'
          : `${result.total_chunks} chunks from ${result.pages} page(s), all on this machine.`,
      });
    } catch (problem) {
      // 409 is the gateway saying this exact file is already indexed, which
      // is worth saying plainly rather than reporting as a failure.
      if (problem.status === 409) {
        toast('Already indexed', {
          description: 'That exact file is in the list below.',
        });
      } else {
        toast.error('Upload failed', { description: problem.message });
      }
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
    setError('');

    try {
      await api.deleteDocument(doc.document_id);
      await loadDocuments();

      toast.success(`${doc.file_name} deleted`, {
        description: 'Its index is gone from this machine.',
      });
    } catch (problem) {
      toast.error('Delete failed', { description: problem.message });
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
          disabled={uploading || offline}
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

      {error && !offline && (
        <p className="mt-4 rounded-lg border border-border bg-destructive px-4 py-2.5 text-sm text-destructive-foreground">
          {error}
        </p>
      )}

      {!loading && documents.length === 0 ? (
        <div className="mt-5">
          <EmptyState
            icon={offline ? WifiOff : FileText}
            title={offline ? 'Local app not running' : 'No documents yet'}
            description={
              offline
                ? 'Your documents live on this machine, so this list comes from the gateway on port 8001.'
                : 'Upload a PDF and it is read, split and indexed here. Only the snippets a question matches are ever sent to the engine.'
            }
            action={
              offline ? null : (
                <button
                  type="button"
                  onClick={() => fileInput.current?.click()}
                  disabled={uploading}
                  className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  <Upload className="size-4" />
                  Upload your first document
                </button>
              )
            }
            hint={
              offline
                ? 'Start it with ./start.sh and reload this page.'
                : 'PDFs with selectable text. A scanned page needs OCR first.'
            }
          />
        </div>
      ) : (
      /* Scrolls sideways rather than forcing the page wide on a phone; the
         less critical columns drop out at sm and md first. */
      <div className="mt-5 overflow-x-auto rounded-xl border border-border">
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
              <SkeletonRows
                rows={3}
                columns={[
                  // Two bars: the filename and the "N pages - N chunks" line
                  // underneath it.
                  { width: 'w-44', second: 'w-24' },
                  { width: 'w-12', className: 'hidden sm:table-cell' },
                  { width: 'w-20', className: 'hidden md:table-cell' },
                  { width: 'w-16' },
                  { width: 'ml-auto w-6' },
                ]}
              />
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
      )}

      {documents.length > 0 && (
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
