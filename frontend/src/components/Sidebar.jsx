import React, { useState } from 'react';
import {
  MessageSquare,
  Plus,
  RefreshCw,
  Trash2,
  User,
  FileText,
  ChevronRight,
  X,
} from 'lucide-react';
import logo from '../assets/logo.png';
import DocumentSelector from './DocumentSelector';

const Sidebar = ({
  sessions,
  documents,
  selectedSessionId,
  selectedDocumentId,
  selectedDocumentIds = [],
  documentMode = 'single',
  onSelectSession,
  onNewChat,
  onRefresh,
  onDeleteSession,
  onSelectDocument,
  onRefreshDocuments,
  userId = 'test_user_01',
}) => {
  const [profileOpen, setProfileOpen] = useState(false);
  const [documentsOpen, setDocumentsOpen] = useState(false);

  const handleDeleteClick = (e, sessionId) => {
    e.stopPropagation();

    const confirmed = window.confirm(
      'Are you sure you want to delete this conversation?'
    );

    if (!confirmed) return;

    onDeleteSession(sessionId);
  };

  const handleOpenDocuments = async () => {
    if (onRefreshDocuments) {
      await onRefreshDocuments();
    }

    setDocumentsOpen(true);
    setProfileOpen(false);
  };

  const handleSaveDocumentSelection = (selectionPayload) => {
    onSelectDocument(selectionPayload);
    setDocumentsOpen(false);
  };

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="brand-box">
          <div className="brand-icon">
            <img src={logo} alt="Krish AI Logo" className="sidebar-logo" />
          </div>

          <div>
            <h2>KRISH AI</h2>
            <p>Document Intelligence</p>
          </div>
        </div>

        <button onClick={onNewChat} className="primary-action-btn">
          <Plus size={18} />
          New Chat
        </button>

        <button onClick={onRefresh} className="ghost-action-btn">
          <RefreshCw size={16} />
          Refresh History
        </button>
      </div>

      <div className="sidebar-body">
        <p className="sidebar-label">Previous Conversations</p>

        {sessions.length === 0 && (
          <div className="empty-sidebar">
            <MessageSquare size={22} />
            <p>No previous chats yet.</p>
          </div>
        )}

        {sessions.map((session) => {
          const active = selectedSessionId === session.session_id;

          return (
            <div
              key={session.session_id}
              onClick={() => onSelectSession(session.session_id)}
              className={`session-card ${active ? 'active' : ''}`}
            >
              <div className="session-top-row">
                <MessageSquare size={16} />

                <strong>{session.title || 'Untitled Chat'}</strong>

                <button
                  onClick={(e) => handleDeleteClick(e, session.session_id)}
                  title="Delete conversation"
                  className="delete-session-btn"
                >
                  <Trash2 size={14} />
                </button>
              </div>

              <p>{session.last_message || 'No messages'}</p>
            </div>
          );
        })}
      </div>

      <div className="sidebar-profile-area">
        <button
          type="button"
          className="profile-card"
          onClick={() => {
            setProfileOpen((prev) => !prev);
            setDocumentsOpen(false);
          }}
        >
          <div className="profile-avatar">KN</div>

          <div className="profile-text">
            <strong>Krishan Nan</strong>
            <span>Plus · Local AI</span>
          </div>

          <ChevronRight
            size={18}
            className={profileOpen ? 'profile-arrow open' : 'profile-arrow'}
          />
        </button>

        {profileOpen && (
          <div className="profile-menu">
            <button
              type="button"
              className="profile-menu-item"
              onClick={handleOpenDocuments}
            >
              <FileText size={18} />
              <div>
                <strong>Uploaded Documents</strong>
                <span>{documents.length} PDFs available</span>
              </div>
            </button>

            <button type="button" className="profile-menu-item disabled">
              <User size={18} />
              <div>
                <strong>Profile Settings</strong>
                <span>Coming soon</span>
              </div>
            </button>
          </div>
        )}
      </div>

      {documentsOpen && (
        <div className="documents-drawer-overlay">
          <div className="documents-drawer">
            <div className="drawer-header">
              <div>
                <h3>Uploaded Documents</h3>
                <p>Select documents, then click Save Selection.</p>
              </div>

              <button
                type="button"
                className="drawer-close-btn"
                onClick={() => setDocumentsOpen(false)}
              >
                <X size={18} />
              </button>
            </div>

            <div className="drawer-toolbar">
              <div className="drawer-count">
                <FileText size={16} />
                <span>{documents.length} PDFs</span>
              </div>

              <button
                type="button"
                onClick={onRefreshDocuments}
                className="document-refresh-btn"
              >
                <RefreshCw size={16} />
                Refresh
              </button>
            </div>

            <DocumentSelector
              documents={documents}
              selectedDocumentId={selectedDocumentId}
              selectedDocumentIds={selectedDocumentIds}
              documentMode={documentMode}
              onSelectDocument={handleSaveDocumentSelection}
              onRefresh={onRefreshDocuments}
              userId={userId}
              showHeader={false}
            />
          </div>
        </div>
      )}
    </aside>
  );
};

export default Sidebar;