import React, { useEffect, useMemo, useState } from 'react';
import {
  FileText,
  CheckCircle,
  Trash2,
  Pencil,
  Check,
  X,
  Layers,
  Square,
  CheckSquare,
  Save,
} from 'lucide-react';
import { api } from '../services/api';

const cleanIds = (ids) => {
  if (!Array.isArray(ids)) return [];
  return [...new Set(ids.filter(Boolean))];
};

const normalizeMode = (mode) => {
  if (mode === 'all') return 'all';
  if (mode === 'multiple') return 'multiple';
  return 'single';
};

const DocumentSelector = ({
  documents,
  selectedDocumentId,
  selectedDocumentIds = [],
  documentMode = 'single',
  onSelectDocument,
  onRefresh,
  userId = 'test_user_01',
  showHeader = true,
}) => {
  const [draftMode, setDraftMode] = useState('single');
  const [draftDocumentId, setDraftDocumentId] = useState('');
  const [draftDocumentIds, setDraftDocumentIds] = useState([]);

  const [deletingDocumentId, setDeletingDocumentId] = useState(null);
  const [renamingDocumentId, setRenamingDocumentId] = useState(null);
  const [renameValue, setRenameValue] = useState('');
  const [savingRenameId, setSavingRenameId] = useState(null);

  useEffect(() => {
    const mode = normalizeMode(documentMode);

    setDraftMode(mode);
    setDraftDocumentId(selectedDocumentId || '');

    if (mode === 'single') {
      setDraftDocumentIds(selectedDocumentId ? [selectedDocumentId] : []);
    } else if (mode === 'multiple') {
      setDraftDocumentIds(cleanIds(selectedDocumentIds));
    } else {
      setDraftDocumentIds([]);
    }
  }, [documentMode, selectedDocumentId, selectedDocumentIds]);

  const selectedDocument = documents.find(
    (doc) => doc.document_id === selectedDocumentId
  );

  const draftSelectedDocuments = useMemo(() => {
    if (draftMode === 'all') return documents;

    if (draftMode === 'multiple') {
      return documents.filter((doc) =>
        draftDocumentIds.includes(doc.document_id)
      );
    }

    const doc = documents.find((item) => item.document_id === draftDocumentId);
    return doc ? [doc] : [];
  }, [documents, draftMode, draftDocumentId, draftDocumentIds]);

  const hasUnsavedChanges = useMemo(() => {
    const currentMode = normalizeMode(documentMode);
    const currentIds = cleanIds(selectedDocumentIds);
    const draftIds = cleanIds(draftDocumentIds);

    if (currentMode !== draftMode) return true;

    if ((selectedDocumentId || '') !== (draftDocumentId || '')) {
      if (currentMode === 'single' || draftMode === 'single') return true;
    }

    if (currentIds.length !== draftIds.length) return true;

    return currentIds.some((id) => !draftIds.includes(id));
  }, [
    documentMode,
    selectedDocumentId,
    selectedDocumentIds,
    draftMode,
    draftDocumentId,
    draftDocumentIds,
  ]);

  const selectSingleDraft = (docId) => {
    setDraftMode('single');
    setDraftDocumentId(docId);
    setDraftDocumentIds([docId]);
  };

  const selectAllDraft = () => {
    setDraftMode('all');
    setDraftDocumentId('');
    setDraftDocumentIds([]);
  };

  const toggleMultiDraft = (e, docId) => {
    e.stopPropagation();

    const exists = draftDocumentIds.includes(docId);

    const nextIds = exists
      ? draftDocumentIds.filter((id) => id !== docId)
      : [...draftDocumentIds, docId];

    if (nextIds.length >= 2) {
      setDraftMode('multiple');
      setDraftDocumentId('');
      setDraftDocumentIds(nextIds);
      return;
    }

    if (nextIds.length === 1) {
      setDraftMode('single');
      setDraftDocumentId(nextIds[0]);
      setDraftDocumentIds(nextIds);
      return;
    }

    setDraftMode('single');
    setDraftDocumentId('');
    setDraftDocumentIds([]);
  };

  const saveSelection = () => {
    if (documents.length === 0) {
      alert('No documents available.');
      return;
    }

    if (draftMode === 'single' && !draftDocumentId) {
      alert('Please select one PDF.');
      return;
    }

    if (draftMode === 'multiple' && draftDocumentIds.length < 2) {
      alert('Please select at least 2 PDFs for multi-document mode.');
      return;
    }

    onSelectDocument({
      mode: draftMode,
      documentId: draftMode === 'single' ? draftDocumentId : '',
      documentIds: draftMode === 'multiple' ? draftDocumentIds : draftDocumentId ? [draftDocumentId] : [],
      startNewChat: true,
    });
  };

  const startRename = (e, doc) => {
    e.stopPropagation();
    setRenamingDocumentId(doc.document_id);
    setRenameValue(doc.file_name || '');
  };

  const cancelRename = (e) => {
    e.stopPropagation();
    setRenamingDocumentId(null);
    setRenameValue('');
  };

  const saveRename = async (e, doc) => {
    e.stopPropagation();

    const trimmedName = renameValue.trim();

    if (!trimmedName) {
      alert('Document name cannot be empty.');
      return;
    }

    try {
      setSavingRenameId(doc.document_id);

      await api.renameDocument({
        documentId: doc.document_id,
        newFileName: trimmedName,
        userId,
      });

      setRenamingDocumentId(null);
      setRenameValue('');

      if (onRefresh) {
        await onRefresh();
      }
    } catch (error) {
      console.error('Failed to rename document:', error);
      alert(error.message || 'Failed to rename document. Check backend console.');
    } finally {
      setSavingRenameId(null);
    }
  };

  const handleDeleteDocument = async (e, doc) => {
    e.stopPropagation();

    const confirmed = window.confirm(
      `Are you sure you want to delete this PDF?\n\n${doc.file_name}`
    );

    if (!confirmed) return;

    try {
      setDeletingDocumentId(doc.document_id);

      await api.deleteDocument(doc.document_id, userId);

      const remainingDraftIds = draftDocumentIds.filter(
        (id) => id !== doc.document_id
      );

      if (draftMode === 'all') {
        setDraftMode('all');
        setDraftDocumentId('');
        setDraftDocumentIds([]);
      } else if (draftDocumentId === doc.document_id || remainingDraftIds.length === 0) {
        setDraftMode('single');
        setDraftDocumentId('');
        setDraftDocumentIds([]);
      } else if (remainingDraftIds.length === 1) {
        setDraftMode('single');
        setDraftDocumentId(remainingDraftIds[0]);
        setDraftDocumentIds(remainingDraftIds);
      } else {
        setDraftMode('multiple');
        setDraftDocumentId('');
        setDraftDocumentIds(remainingDraftIds);
      }

      if (selectedDocumentId === doc.document_id) {
        onSelectDocument({
          mode: 'single',
          documentId: '',
          documentIds: [],
          startNewChat: true,
        });
      }

      if (onRefresh) {
        await onRefresh();
      }
    } catch (error) {
      console.error('Failed to delete document:', error);
      alert(error.message || 'Failed to delete document. Check backend console.');
    } finally {
      setDeletingDocumentId(null);
    }
  };

  const handleRenameKeyDown = (e, doc) => {
    if (e.key === 'Enter') {
      saveRename(e, doc);
    }

    if (e.key === 'Escape') {
      cancelRename(e);
    }
  };

  const selectionNote = useMemo(() => {
    if (documents.length === 0) return null;

    if (documentMode === 'all') {
      return {
        label: 'Saved Selection',
        value: `All Documents (${documents.length} PDFs)`,
      };
    }

    if (documentMode === 'multiple') {
      return {
        label: 'Saved Selection',
        value: `${selectedDocumentIds.length} PDFs selected`,
      };
    }

    if (selectedDocument) {
      return {
        label: 'Saved Selection',
        value: selectedDocument.file_name,
      };
    }

    return {
      label: 'Saved Selection',
      value: 'No document selected',
    };
  }, [
    documents.length,
    documentMode,
    selectedDocument,
    selectedDocumentIds.length,
  ]);

  const draftNote = useMemo(() => {
    if (documents.length === 0) return 'No PDFs uploaded yet.';

    if (draftMode === 'all') {
      return `Draft: All Documents (${documents.length} PDFs)`;
    }

    if (draftMode === 'multiple') {
      return `Draft: ${draftDocumentIds.length} PDFs`;
    }

    const doc = documents.find((item) => item.document_id === draftDocumentId);
    return doc ? `Draft: ${doc.file_name}` : 'Draft: No PDF selected';
  }, [documents, draftMode, draftDocumentId, draftDocumentIds.length]);

  return (
    <section className="document-selector-card profile-document-selector">
      {showHeader && (
        <div className="document-selector-header">
          <div>
            <h3>Uploaded Documents</h3>
            <p>Select PDFs, then click Save Selection.</p>
          </div>
        </div>
      )}

      {documents.length === 0 ? (
        <div className="empty-documents">
          <FileText size={22} />
          <div>
            <strong>No documents uploaded yet</strong>
            <span>Click + in chat input to upload your first PDF.</span>
          </div>
        </div>
      ) : (
        <>
          <div className="selection-save-panel">
            <div>
              <span>{draftNote}</span>
              <strong>
                {hasUnsavedChanges
                  ? 'Unsaved selection'
                  : 'Selection already saved'}
              </strong>
            </div>

            <button
              type="button"
              className="save-selection-btn"
              onClick={saveSelection}
              disabled={!hasUnsavedChanges}
            >
              <Save size={16} />
              Save Selection
            </button>
          </div>

          <div
            role="button"
            tabIndex={0}
            className={`document-card all-documents-card ${
              draftMode === 'all' ? 'active draft-active' : ''
            }`}
            onClick={selectAllDraft}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                selectAllDraft();
              }
            }}
          >
            <div className="document-file-icon">
              <Layers size={19} />
            </div>

            <div className="document-info">
              <strong>All Documents</strong>
              <span>Search across {documents.length} uploaded PDFs</span>
            </div>

            <div className="document-actions">
              {draftMode === 'all' && (
                <span className="document-selected-badge" title="Draft selected">
                  <CheckCircle size={18} />
                </span>
              )}
            </div>
          </div>

          <div className="document-list">
            {documents.map((doc) => {
              const draftSingleActive =
                draftMode === 'single' && draftDocumentId === doc.document_id;

              const draftMultiActive =
                draftMode === 'multiple' &&
                draftDocumentIds.includes(doc.document_id);

              const draftActive = draftSingleActive || draftMultiActive;

              const savedActive =
                documentMode === 'single'
                  ? selectedDocumentId === doc.document_id
                  : documentMode === 'multiple'
                    ? selectedDocumentIds.includes(doc.document_id)
                    : false;

              const isDeleting = deletingDocumentId === doc.document_id;
              const isRenaming = renamingDocumentId === doc.document_id;
              const isSavingRename = savingRenameId === doc.document_id;

              return (
                <div
                  key={doc.document_id}
                  role="button"
                  tabIndex={0}
                  className={`document-card ${draftActive ? 'active draft-active' : ''} ${
                    savedActive ? 'saved-active' : ''
                  } ${isDeleting ? 'deleting' : ''} ${isRenaming ? 'renaming' : ''}`}
                  onClick={() => {
                    if (!isDeleting && !isRenaming) {
                      selectSingleDraft(doc.document_id);
                    }
                  }}
                  onKeyDown={(e) => {
                    if (renamingDocumentId) return;

                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      selectSingleDraft(doc.document_id);
                    }
                  }}
                >
                  <button
                    type="button"
                    className={`document-multi-check ${
                      draftDocumentIds.includes(doc.document_id) ? 'checked' : ''
                    }`}
                    title="Add to multi-document draft"
                    onClick={(e) => toggleMultiDraft(e, doc.document_id)}
                    disabled={isDeleting || isRenaming}
                  >
                    {draftDocumentIds.includes(doc.document_id) ? (
                      <CheckSquare size={18} />
                    ) : (
                      <Square size={18} />
                    )}
                  </button>

                  <div className="document-file-icon">
                    <FileText size={19} />
                  </div>

                  <div className="document-info">
                    {isRenaming ? (
                      <input
                        className="document-rename-input"
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onClick={(e) => e.stopPropagation()}
                        onKeyDown={(e) => handleRenameKeyDown(e, doc)}
                        autoFocus
                        disabled={isSavingRename}
                      />
                    ) : (
                      <strong title={doc.file_name}>{doc.file_name}</strong>
                    )}

                    <span>
                      {doc.pages || 0} pages · {doc.total_chunks || 0} chunks
                    </span>
                  </div>

                  <div className="document-actions">
                    {draftActive && !isRenaming && (
                      <span className="document-selected-badge" title="Draft selected">
                        <CheckCircle size={18} />
                      </span>
                    )}

                    {isRenaming ? (
                      <>
                        <button
                          type="button"
                          className="document-save-btn"
                          title="Save name"
                          onClick={(e) => saveRename(e, doc)}
                          disabled={isSavingRename}
                        >
                          <Check size={15} />
                        </button>

                        <button
                          type="button"
                          className="document-cancel-btn"
                          title="Cancel rename"
                          onClick={cancelRename}
                          disabled={isSavingRename}
                        >
                          <X size={15} />
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          type="button"
                          className="document-rename-btn"
                          title="Rename document"
                          onClick={(e) => startRename(e, doc)}
                          disabled={isDeleting}
                        >
                          <Pencil size={15} />
                        </button>

                        <button
                          type="button"
                          className="document-delete-btn"
                          title="Delete document"
                          onClick={(e) => handleDeleteDocument(e, doc)}
                          disabled={isDeleting}
                        >
                          <Trash2 size={15} />
                        </button>
                      </>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {selectionNote && (
            <div className="selected-document-note">
              <span>{selectionNote.label}</span>
              <strong>{selectionNote.value}</strong>
            </div>
          )}
        </>
      )}
    </section>
  );
};

export default DocumentSelector;