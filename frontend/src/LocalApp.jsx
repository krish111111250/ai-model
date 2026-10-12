import { useCallback, useEffect, useState } from 'react';
import ChatArea from '@/components/local/ChatArea';
import LocalSidebar from '@/components/local/LocalSidebar';
import SetupGate from '@/components/local/SetupGate';
import { api } from '@/services/api';

const USER_ID = 'test_user_01';

/**
 * Part 2 shell: the local chat UI served from the customer's own machine.
 *
 * The document list and the selection live here rather than in either child,
 * because both need them: the sidebar uploads and deletes, the chat area asks
 * questions against whatever is selected. Keeping one copy in the parent is
 * what stops the two panes disagreeing about what is indexed.
 */
const LocalApp = () => {
  const [settings, setSettings] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [selectedDocumentId, setSelectedDocumentId] = useState('');
  const [sessionId, setSessionId] = useState(() => `session_${Date.now()}`);

  const loadDocuments = useCallback(async () => {
    try {
      const data = await api.getDocuments(USER_ID);
      const list = data.documents || [];

      setDocuments(list);

      // Keep a valid selection at all times: the chat area cannot ask a
      // question in single-document mode without one, and a selection
      // pointing at a deleted document would fail server-side.
      setSelectedDocumentId((current) => {
        if (current && list.some((doc) => doc.document_id === current)) {
          return current;
        }

        return list[0]?.document_id || '';
      });
    } catch (error) {
      console.error('Failed to load documents:', error);
    }
  }, []);

  const loadSettings = useCallback(async () => {
    try {
      setSettings(await api.getSettings());
    } catch (error) {
      console.error('Failed to read gateway settings:', error);
      setSettings({ api_key_configured: false, unreachable: true });
    }
  }, []);

  useEffect(() => {
    // Both reads are awaited inside this wrapper rather than called straight
    // from the effect body: the state lands in a promise callback, so there
    // is no synchronous cascading render on mount.
    const bootstrap = async () => {
      await loadSettings();
      await loadDocuments();
    };

    bootstrap();
  }, [loadSettings, loadDocuments]);

  const startNewChat = () => setSessionId(`session_${Date.now()}`);

  // Nothing works without a key, so ask for it before showing the app rather
  // than letting every question fail with a 503.
  if (settings && !settings.api_key_configured) {
    return <SetupGate onSaved={loadSettings} unreachable={settings.unreachable} />;
  }

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <LocalSidebar
        userId={USER_ID}
        documents={documents}
        selectedDocumentId={selectedDocumentId}
        onSelectDocument={setSelectedDocumentId}
        onDocumentsChanged={loadDocuments}
        onNewChat={startNewChat}
      />

      <ChatArea
        userId={USER_ID}
        sessionId={sessionId}
        documents={documents}
        selectedDocumentId={selectedDocumentId}
        onSelectDocument={setSelectedDocumentId}
      />
    </div>
  );
};

export default LocalApp;
