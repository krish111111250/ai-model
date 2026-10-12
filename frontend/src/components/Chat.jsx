import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Send,
  Mic,
  MicOff,
  Volume2,
  VolumeX,
  Loader2,
  Radio,
  Plus,
  X,
  FileText,
  Layers,
} from 'lucide-react';
import { api } from '../services/api';
import FileUpload from './FileUpload';

const Chat = ({
  sessionId = 'test_session_01',
  userId = 'test_user_01',
  documentId = null,
  documentIds = [],
  documentMode = 'single',
  selectedDocument = null,
  selectedDocuments = [],
  onChatUpdated,
  onUploadSuccess,
}) => {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [autoSpeak, setAutoSpeak] = useState(true);
  const [isGeneratingVoice, setIsGeneratingVoice] = useState(false);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);

  const chatEndRef = useRef(null);
  const audioRef = useRef(null);
  const currentAudioUrlRef = useRef(null);

  const normalizeDocumentMode = (value) => {
    if (value === 'all') return 'all';
    if (value === 'multiple') return 'multiple';
    return 'single';
  };

  // English only: the local model's Tanglish/Tamil output was not accurate.
  const selectedLanguage = 'english';
  const selectedMode = normalizeDocumentMode(documentMode);

  const cleanDocumentIds = useMemo(() => {
    return Array.isArray(documentIds) ? documentIds.filter(Boolean) : [];
  }, [documentIds]);

  const hasValidDocumentSelection = useMemo(() => {
    if (selectedMode === 'all') {
      return true;
    }

    if (selectedMode === 'multiple') {
      return cleanDocumentIds.length > 0;
    }

    return Boolean(documentId);
  }, [selectedMode, cleanDocumentIds, documentId]);

  const selectedDocumentLabel = useMemo(() => {
    if (selectedMode === 'all') {
      const count = selectedDocuments?.length || 0;
      return count > 0 ? `All Documents (${count} PDFs)` : 'All Documents';
    }

    if (selectedMode === 'multiple') {
      const count = cleanDocumentIds.length;
      return `${count} PDFs selected`;
    }

    return selectedDocument?.file_name || 'Selected PDF';
  }, [selectedMode, selectedDocuments, cleanDocumentIds.length, selectedDocument]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading, isGeneratingVoice]);

  useEffect(() => {
    const loadHistory = async () => {
      if (!sessionId) return;

      try {
        const data = await api.getChatHistory(sessionId, userId);
        setMessages(data.messages || []);
      } catch (error) {
        console.error('Failed to load chat history:', error);
        setMessages([]);
      }
    };

    stopSpeaking();
    loadHistory();
  }, [sessionId, userId]);

  useEffect(() => {
    return () => {
      stopSpeaking();

      if (currentAudioUrlRef.current) {
        URL.revokeObjectURL(currentAudioUrlRef.current);
      }
    };
  }, []);

  const getSpeechLangCode = () => 'en-US';

  const getVoiceName = () => 'en-US-JennyNeural';

  const stopSpeaking = () => {
    try {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current.currentTime = 0;
        audioRef.current.src = '';
        audioRef.current.load();
      }

      setIsGeneratingVoice(false);
    } catch (error) {
      console.error('Stop voice error:', error);
    }
  };

  const speakResponse = async (text) => {
    if (!text) return;

    try {
      stopSpeaking();

      setIsGeneratingVoice(true);

      const audioUrl = await api.generateSpeech({
        text,
        language: 'english',
        voice: getVoiceName(),
      });

      if (currentAudioUrlRef.current) {
        URL.revokeObjectURL(currentAudioUrlRef.current);
      }

      currentAudioUrlRef.current = audioUrl;

      const audio = new Audio();
      audioRef.current = audio;

      audio.src = audioUrl;
      audio.preload = 'auto';
      audio.volume = 1;
      audio.muted = false;
      audio.playbackRate = 1;

      audio.onended = () => setIsGeneratingVoice(false);

      audio.onerror = (error) => {
        console.error('[KRISH AI] Audio play error:', error);
        setIsGeneratingVoice(false);
        alert('Audio generated, but browser could not play it. Check Chrome tab mute / volume.');
      };

      await audio.play();
    } catch (error) {
      console.error('[KRISH AI] Edge TTS voice error:', error);
      setIsGeneratingVoice(false);

      alert(
        error?.message ||
          'Voice generation failed. Check backend /tts endpoint and browser audio permission.'
      );
    }
  };

  const handleListen = () => {
    const SpeechRecognition =
      window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognition) {
      alert('Browser does not support Voice API. Try Google Chrome.');
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = getSpeechLangCode();
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onstart = () => setIsListening(true);
    recognition.onend = () => setIsListening(false);

    recognition.onerror = (event) => {
      console.error('Speech recognition error:', event.error);
      setIsListening(false);
    };

    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      setInput(transcript);
    };

    recognition.start();
  };

  const formatSources = (msg) => {
    if (msg.source_labels && msg.source_labels.length > 0) {
      return msg.source_labels.join(', ');
    }

    if (msg.sources && msg.sources.length > 0) {
      return msg.sources
        .map((source) => {
          if (typeof source === 'string') return source;

          const fileName = source.file_name || 'Unknown file';
          const pageNumber = source.page_number || 'Unknown page';
          const chunkIndex = source.chunk_index || 'Unknown chunk';

          return `${fileName} - Page ${pageNumber} - Chunk ${chunkIndex}`;
        })
        .join(', ');
    }

    return '';
  };

  const getNoDocumentMessage = () =>
    'Please click the + icon and upload a PDF first.';

  const getFallbackAnswer = () =>
    'This information is not available in the selected document.';

  const sendMessage = async (e) => {
    e.preventDefault();

    const trimmedInput = input.trim();

    if (!trimmedInput || isLoading) return;

    if (!hasValidDocumentSelection) {
      const warningMessage = {
        role: 'bot',
        content: getNoDocumentMessage(),
        sources: [],
        source_labels: [],
        language: selectedLanguage,
      };

      setMessages((prev) => [...prev, warningMessage]);

      if (autoSpeak) {
        await speakResponse(warningMessage.content);
      }

      return;
    }

    const userMessage = {
      role: 'user',
      content: trimmedInput,
      sources: [],
      source_labels: [],
      language: selectedLanguage,
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      const response = await api.sendChatMessage({
        query: trimmedInput,
        language: selectedLanguage,
        sessionId,
        userId,
        documentId: selectedMode === 'single' ? documentId : null,
        documentIds: selectedMode === 'multiple' ? cleanDocumentIds : [],
        documentMode: selectedMode,
      });

      const botMessage = {
        role: 'bot',
        content: response.answer || getFallbackAnswer(),
        sources: response.sources || [],
        source_labels: response.source_labels || [],
        language: selectedLanguage,
      };

      setMessages((prev) => [...prev, botMessage]);

      if (autoSpeak) {
        await speakResponse(botMessage.content);
      }

      if (onChatUpdated) {
        onChatUpdated();
      }
    } catch (error) {
      console.error('Chat error:', error);

      const errorMessage = {
        role: 'bot',
        content:
          'Error connecting to the AI backend. Please check if the backend is running.',
        sources: [],
        source_labels: [],
        language: selectedLanguage,
      };

      setMessages((prev) => [...prev, errorMessage]);

      if (autoSpeak) {
        await speakResponse(errorMessage.content);
      }
    } finally {
      setIsLoading(false);
    }
  };

  const clearCurrentView = () => {
    stopSpeaking();
    setMessages([]);
  };

  const handleUploadDone = async (response) => {
    if (onUploadSuccess) {
      await onUploadSuccess(response);
    }

    setUploadModalOpen(false);
  };

  const emptyChatText = () =>
    hasValidDocumentSelection
      ? 'Ask questions from the selected PDF.'
      : 'Click the + icon to upload a PDF.';

  const inputPlaceholder = () =>
    hasValidDocumentSelection
      ? 'Ask about selected PDF...'
      : 'Click + to upload a PDF...';

  return (
    <section className="glass-card chat-card main-chat-card">
      <div className="chat-toolbar">
        <div className="session-info">
          <Radio size={18} />
          <span>Session</span>
          <strong>{sessionId.slice(0, 22)}...</strong>
        </div>

        <div className="chat-controls">
          <button
            type="button"
            onClick={() => setAutoSpeak((prev) => !prev)}
            className={`voice-toggle ${autoSpeak ? 'on' : ''}`}
          >
            {autoSpeak ? <Volume2 size={18} /> : <VolumeX size={18} />}
            {autoSpeak ? 'Edge Voice On' : 'Voice Off'}
          </button>

          <button type="button" onClick={stopSpeaking} className="danger-btn">
            Stop Voice
          </button>

          <button type="button" onClick={clearCurrentView} className="dark-btn">
            Clear View
          </button>
        </div>
      </div>

      {hasValidDocumentSelection && (
        <div className="selected-doc-bar">
          {selectedMode === 'all' || selectedMode === 'multiple' ? (
            <Layers size={16} />
          ) : (
            <FileText size={16} />
          )}
          <span>
            {selectedMode === 'all'
              ? 'Mode:'
              : selectedMode === 'multiple'
                ? 'Selected PDFs:'
                : 'Selected PDF:'}
          </span>
          <strong>{selectedDocumentLabel}</strong>
        </div>
      )}

      <div className="chat-window">
        {messages.length === 0 && (
          <div className="empty-chat">
            <h3>Ask anything from your PDF</h3>
            <p>{emptyChatText()}</p>
          </div>
        )}

        {messages.map((msg, idx) => {
          const sourcesText = formatSources(msg);
          return (
            <div
              key={idx}
              className={`message-row ${msg.role === 'user' ? 'user' : 'bot'}`}
            >
              <div className={`message-bubble ${msg.role}`}>
                <p>{msg.content}</p>

                {msg.role === 'bot' && (
                  <button
                    type="button"
                    onClick={() => speakResponse(msg.content)}
                    disabled={isGeneratingVoice}
                    className="mini-speak-btn"
                  >
                    {isGeneratingVoice ? (
                      <>
                        <Loader2 size={14} className="spin" />
                        Voice...
                      </>
                    ) : (
                      <>
                        <Volume2 size={14} />
                        Edge Speak
                      </>
                    )}
                  </button>
                )}

                {sourcesText && (
                  <div className="source-box">
                    <strong>Sources</strong>
                    <span>{sourcesText}</span>
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {isLoading && (
          <div className="thinking-row">
            <Loader2 size={18} className="spin" />
            <span>
              AI is thinking...
            </span>
          </div>
        )}

        {isGeneratingVoice && (
          <div className="voice-row">
            <span className="voice-wave" />
            <span>
              Generating voice...
            </span>
          </div>
        )}

        <div ref={chatEndRef} />
      </div>

      <form onSubmit={sendMessage} className="input-console chatgpt-input-console">
        <button
          type="button"
          className="plus-upload-btn"
          title="Upload PDF"
          onClick={() => setUploadModalOpen(true)}
        >
          <Plus size={22} />
        </button>

        <button
          type="button"
          onClick={handleListen}
          disabled={isLoading}
          className={`mic-btn ${isListening ? 'listening' : ''}`}
          title="Voice input"
        >
          {isListening ? <MicOff size={20} /> : <Mic size={20} />}
        </button>

        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={inputPlaceholder()}
          disabled={isLoading}
        />

        <button
          type="submit"
          disabled={isLoading || !input.trim()}
          className="send-btn"
          title="Send message"
        >
          <Send size={20} />
        </button>
      </form>

      {uploadModalOpen && (
        <div className="upload-modal-overlay">
          <div className="upload-modal">
            <div className="upload-modal-header">
              <div>
                <h3>Upload PDF</h3>
                <p>Choose a PDF and train Krish AI.</p>
              </div>

              <button
                type="button"
                className="drawer-close-btn"
                onClick={() => setUploadModalOpen(false)}
              >
                <X size={18} />
              </button>
            </div>

            <FileUpload onUploadSuccess={handleUploadDone} userId={userId} />
          </div>
        </div>
      )}
    </section>
  );
};

export default Chat;