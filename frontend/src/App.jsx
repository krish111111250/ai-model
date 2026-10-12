import React, { useEffect, useMemo, useState } from 'react';
import Chat from './components/Chat';
import InitBanner from './components/InitBanner';
import Sidebar from './components/Sidebar';
import { api } from './services/api';
import './App.css';
import logo from './assets/logo.png';

const USER_ID = 'test_user_01';

const STORAGE_KEYS = {
  sessionId: 'selected_session_id',
  documentMode: 'selected_document_mode',
  documentId: 'selected_document_id',
  documentIds: 'selected_document_ids',
};

function safeParseArray(value) {
  try {
    const parsed = JSON.parse(value || '[]');
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function normalizeDocumentMode(mode) {
  if (mode === 'all') return 'all';
  if (mode === 'multiple') return 'multiple';
  return 'single';
}

function uniqueIds(ids) {
  if (!Array.isArray(ids)) return [];
  return [...new Set(ids.filter(Boolean))];
}

function App() {
  const [sessions, setSessions] = useState([]);
  const [documents, setDocuments] = useState([]);

  const [selectedSessionId, setSelectedSessionId] = useState(() => {
    return localStorage.getItem(STORAGE_KEYS.sessionId) || `session_${Date.now()}`;
  });

  const [documentMode, setDocumentMode] = useState(() => {
    return normalizeDocumentMode(localStorage.getItem(STORAGE_KEYS.documentMode));
  });

  const [selectedDocumentId, setSelectedDocumentId] = useState(() => {
    return localStorage.getItem(STORAGE_KEYS.documentId) || '';
  });

  const [selectedDocumentIds, setSelectedDocumentIds] = useState(() => {
    return uniqueIds(safeParseArray(localStorage.getItem(STORAGE_KEYS.documentIds)));
  });

  const loadSessions = async () => {
    try {
      const data = await api.getChatSessions(USER_ID);
      setSessions(data.sessions || []);
    } catch (error) {
      console.error('Failed to load sessions:', error);
    }
  };

  const saveDocumentSelection = ({
    mode = 'single',
    documentId = '',
    documentIds = [],
  }) => {
    const safeMode = normalizeDocumentMode(mode);
    const cleanIds = uniqueIds(documentIds);

    let finalMode = safeMode;
    let finalDocumentId = '';
    let finalDocumentIds = [];

    if (safeMode === 'all') {
      finalMode = 'all';
      finalDocumentId = '';
      finalDocumentIds = [];
    }

    if (safeMode === 'multiple') {
      if (cleanIds.length >= 2) {
        finalMode = 'multiple';
        finalDocumentId = '';
        finalDocumentIds = cleanIds;
      } else if (cleanIds.length === 1) {
        finalMode = 'single';
        finalDocumentId = cleanIds[0];
        finalDocumentIds = [cleanIds[0]];
      } else {
        finalMode = 'single';
        finalDocumentId = '';
        finalDocumentIds = [];
      }
    }

    if (safeMode === 'single') {
      finalMode = 'single';
      finalDocumentId = documentId || cleanIds[0] || '';
      finalDocumentIds = finalDocumentId ? [finalDocumentId] : [];
    }

    setDocumentMode(finalMode);
    setSelectedDocumentId(finalDocumentId);
    setSelectedDocumentIds(finalDocumentIds);

    localStorage.setItem(STORAGE_KEYS.documentMode, finalMode);

    if (finalDocumentId) {
      localStorage.setItem(STORAGE_KEYS.documentId, finalDocumentId);
    } else {
      localStorage.removeItem(STORAGE_KEYS.documentId);
    }

    if (finalDocumentIds.length > 0) {
      localStorage.setItem(
        STORAGE_KEYS.documentIds,
        JSON.stringify(finalDocumentIds)
      );
    } else {
      localStorage.removeItem(STORAGE_KEYS.documentIds);
    }
  };

  const loadDocuments = async () => {
    try {
      const data = await api.getDocuments(USER_ID);
      const docs = data.documents || [];

      setDocuments(docs);

      const storedMode = normalizeDocumentMode(
        localStorage.getItem(STORAGE_KEYS.documentMode)
      );

      const storedDocumentId = localStorage.getItem(STORAGE_KEYS.documentId) || '';

      const storedDocumentIds = uniqueIds(
        safeParseArray(localStorage.getItem(STORAGE_KEYS.documentIds))
      );

      if (docs.length === 0) {
        saveDocumentSelection({
          mode: 'single',
          documentId: '',
          documentIds: [],
        });
        return;
      }

      const validDocIds = docs.map((doc) => doc.document_id);

      if (storedMode === 'all') {
        saveDocumentSelection({
          mode: 'all',
          documentId: '',
          documentIds: [],
        });
        return;
      }

      if (storedMode === 'multiple') {
        const validStoredIds = storedDocumentIds.filter((id) =>
          validDocIds.includes(id)
        );

        if (validStoredIds.length >= 2) {
          saveDocumentSelection({
            mode: 'multiple',
            documentId: '',
            documentIds: validStoredIds,
          });
          return;
        }

        if (validStoredIds.length === 1) {
          saveDocumentSelection({
            mode: 'single',
            documentId: validStoredIds[0],
            documentIds: [validStoredIds[0]],
          });
          return;
        }
      }

      if (storedDocumentId && validDocIds.includes(storedDocumentId)) {
        saveDocumentSelection({
          mode: 'single',
          documentId: storedDocumentId,
          documentIds: [storedDocumentId],
        });
        return;
      }

      saveDocumentSelection({
        mode: 'single',
        documentId: docs[0].document_id,
        documentIds: [docs[0].document_id],
      });
    } catch (error) {
      console.error('Failed to load documents:', error);
    }
  };

  useEffect(() => {
    loadSessions();
    loadDocuments();
  }, []);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.sessionId, selectedSessionId);
  }, [selectedSessionId]);

  const handleNewChat = () => {
    const newSessionId = `session_${Date.now()}`;
    setSelectedSessionId(newSessionId);
    localStorage.setItem(STORAGE_KEYS.sessionId, newSessionId);
  };

  const handleSelectSession = (sessionId) => {
    const selectedSession = sessions.find(
      (session) => session.session_id === sessionId
    );

    setSelectedSessionId(sessionId);
    localStorage.setItem(STORAGE_KEYS.sessionId, sessionId);

    if (!selectedSession) return;

    const sessionMode = normalizeDocumentMode(selectedSession.document_mode);
    const sessionDocumentId = selectedSession.document_id || '';
    const sessionDocumentIds = uniqueIds(selectedSession.document_ids || []);
    const validDocIds = documents.map((doc) => doc.document_id);

    if (sessionMode === 'all') {
      saveDocumentSelection({
        mode: 'all',
        documentId: '',
        documentIds: [],
      });
      return;
    }

    if (sessionMode === 'multiple') {
      const validSessionIds = sessionDocumentIds.filter((id) =>
        validDocIds.includes(id)
      );

      if (validSessionIds.length >= 2) {
        saveDocumentSelection({
          mode: 'multiple',
          documentId: '',
          documentIds: validSessionIds,
        });
        return;
      }

      if (validSessionIds.length === 1) {
        saveDocumentSelection({
          mode: 'single',
          documentId: validSessionIds[0],
          documentIds: [validSessionIds[0]],
        });
        return;
      }
    }

    if (sessionDocumentId && validDocIds.includes(sessionDocumentId)) {
      saveDocumentSelection({
        mode: 'single',
        documentId: sessionDocumentId,
        documentIds: [sessionDocumentId],
      });
    }
  };

  const handleDeleteSession = async (sessionIdToDelete) => {
    try {
      await api.deleteChatSession(sessionIdToDelete, USER_ID);
      await loadSessions();

      if (selectedSessionId === sessionIdToDelete) {
        handleNewChat();
      }
    } catch (error) {
      console.error('Failed to delete session:', error);
      alert('Failed to delete conversation. Check backend console.');
    }
  };

  const handleUploadSuccess = async (uploadResponse) => {
    await loadDocuments();
    await loadSessions();

    if (uploadResponse?.document_id) {
      saveDocumentSelection({
        mode: 'single',
        documentId: uploadResponse.document_id,
        documentIds: [uploadResponse.document_id],
      });

      handleNewChat();
    }
  };

  const handleDocumentSelectionChange = ({
    mode = 'single',
    documentId = '',
    documentIds = [],
    startNewChat = true,
  }) => {
    saveDocumentSelection({
      mode,
      documentId,
      documentIds,
    });

    if (startNewChat) {
      handleNewChat();
    }
  };

  const selectedDocument = useMemo(() => {
    return documents.find((doc) => doc.document_id === selectedDocumentId) || null;
  }, [documents, selectedDocumentId]);

  const selectedDocuments = useMemo(() => {
    if (documentMode === 'all') {
      return documents;
    }

    if (documentMode === 'multiple') {
      return documents.filter((doc) =>
        selectedDocumentIds.includes(doc.document_id)
      );
    }

    return selectedDocument ? [selectedDocument] : [];
  }, [documents, documentMode, selectedDocument, selectedDocumentIds]);

  const selectedDocText = useMemo(() => {
    if (documents.length === 0) {
      return 'No PDF selected. Click + in chat to upload.';
    }

    if (documentMode === 'all') {
      return `Selected: All Documents (${documents.length} PDFs)`;
    }

    if (documentMode === 'multiple') {
      return selectedDocuments.length > 0
        ? `Selected: ${selectedDocuments.length} PDFs`
        : 'No PDF selected. Choose documents from profile.';
    }

    return selectedDocument
      ? `Selected PDF: ${selectedDocument.file_name}`
      : 'No PDF selected. Choose a document from profile.';
  }, [documents.length, documentMode, selectedDocument, selectedDocuments.length]);

  const chatDocumentId = documentMode === 'single' ? selectedDocumentId : null;

  const chatDocumentIds =
    documentMode === 'multiple'
      ? selectedDocumentIds
      : [];

  return (
    <div className="app-shell">
      <Sidebar
        sessions={sessions}
        documents={documents}
        selectedSessionId={selectedSessionId}
        selectedDocumentId={selectedDocumentId}
        selectedDocumentIds={selectedDocumentIds}
        documentMode={documentMode}
        onSelectSession={handleSelectSession}
        onNewChat={handleNewChat}
        onRefresh={loadSessions}
        onDeleteSession={handleDeleteSession}
        onSelectDocument={handleDocumentSelectionChange}
        onRefreshDocuments={loadDocuments}
        userId={USER_ID}
      />

      <main className="main-panel">
        <section className="hero-section">
          <div className="hero-logo-frame">
            <img src={logo} alt="Krish AI Logo" className="hero-logo" />
          </div>

          <div>
            <h1 className="app-title">Krish AI</h1>
            <p className="app-subtitle">
              Voice-Controlled RAG Assistant · Document Intelligence · Local AI
            </p>

            <p className="selected-doc-pill">{selectedDocText}</p>
          </div>
        </section>

        <InitBanner />

        <div className="content-stack chat-only-stack">
          <Chat
            sessionId={selectedSessionId}
            userId={USER_ID}
            documentId={chatDocumentId}
            documentIds={chatDocumentIds}
            documentMode={documentMode}
            selectedDocument={selectedDocument}
            selectedDocuments={selectedDocuments}
            onChatUpdated={loadSessions}
            onUploadSuccess={handleUploadSuccess}
          />
        </div>
      </main>
    </div>
  );
}

export default App;