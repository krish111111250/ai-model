import axios from 'axios';

// The local gateway, not the answer engine. It runs on this machine, holds the
// documents and sends the engine only the chunks a question matched.
const client = axios.create({
  baseURL: import.meta.env.VITE_KRISH_GATEWAY_URL || 'http://localhost:8001',
  timeout: 300000,
});

// The cloud engine, which is a different origin from the gateway: it signs in
// users, issues API keys and generates answers. It never sees a document.
const cloudClient = axios.create({
  baseURL: import.meta.env.VITE_KRISH_ENGINE_URL || 'http://localhost:8000',
  timeout: 30000,
});

/**
 * A displayable string out of whatever an error response carried.
 *
 * FastAPI answers a 422 with `detail` as an array of Pydantic error objects,
 * not a string. Putting that array straight into React state crashes the
 * render with "Objects are not valid as a React child", so every catch block
 * goes through here.
 */
export const errorMessage = (data, fallback = 'Something went wrong.') => {
  const detail = data?.detail;

  if (typeof detail === 'string' && detail.trim()) {
    return detail;
  }

  if (Array.isArray(detail)) {
    const lines = detail
      .map((item) => {
        if (typeof item === 'string') return item;

        const message = item?.msg || item?.message;

        if (!message) return '';

        // loc is like ["body", "password"] - the field name is the useful
        // half, and "String should have at least 8 characters" means little
        // without knowing which field it refers to.
        const field = Array.isArray(item.loc)
          ? item.loc.filter((part) => typeof part === 'string' && part !== 'body').pop()
          : '';

        return field ? `${field}: ${message}` : message;
      })
      .filter(Boolean);

    if (lines.length) return lines.join('. ');
  }

  // Some proxies answer with a plain-text or HTML body instead of JSON.
  if (typeof data === 'string' && data.trim() && !data.trim().startsWith('<')) {
    return data.trim().slice(0, 300);
  }

  // A single object with no msg, or a Blob from a responseType:'blob' call:
  // there is nothing readable in it, so say something true instead.
  return fallback;
};

const SESSION_KEY = 'krish_session';

/**
 * Session token storage.
 *
 * localStorage is the right place for *this* secret, unlike the engine API
 * key: the dashboard is a browser app that must send the token on every
 * request, so it has to be readable here. It is short-lived (72h) and
 * revocable by signing out, which the API key is not.
 */
export const session = {
  get: () => {
    try {
      return localStorage.getItem(SESSION_KEY) || '';
    } catch {
      return '';
    }
  },

  set: (token) => {
    try {
      localStorage.setItem(SESSION_KEY, token);
    } catch {
      // Private browsing with storage blocked: the session lives for this
      // page only, which is better than failing the login outright.
    }
  },

  clear: () => {
    try {
      localStorage.removeItem(SESSION_KEY);
    } catch {
      // Nothing to clear.
    }
  },
};

cloudClient.interceptors.request.use((config) => {
  const token = session.get();

  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }

  return config;
});

cloudClient.interceptors.response.use(
  (response) => response,
  (error) => {
    // An expired or revoked session should not leave a half-working dashboard
    // retrying forever. Drop the token and send the user back to sign in.
    if (error.response?.status === 401 && session.get()) {
      session.clear();

      if (!window.location.pathname.startsWith('/login')) {
        window.location.replace('/login');
      }
    }

    return Promise.reject(error);
  }
);

const cloudError = (error, fallback) => {
  if (error.response) {
    return {
      status: error.response.status,
      message: errorMessage(error.response.data, fallback),
    };
  }

  return {
    status: 0,
    message: 'Cannot reach the engine. Is it running on port 8000?',
  };
};

const normalizeLanguage = () => 'english';

const normalizeDocumentMode = (mode) => {
  if (mode === 'all') return 'all';
  if (mode === 'multiple') return 'multiple';
  return 'single';
};

const cleanDocumentIds = (documentIds) => {
  if (!Array.isArray(documentIds)) return [];
  return [...new Set(documentIds.filter(Boolean))];
};

export const api = {
  // The gateway's own readiness, used by the initialization banner. It never
  // throws: not being able to reach the gateway is a state to show, not an
  // error to handle at every call site.
  getGatewayStatus: async () => {
    try {
      const response = await client.get('/health', { timeout: 5000 });
      return response.data;
    } catch {
      return {
        status: 'offline',
        message: 'Local gateway is not running. Start it with ./start.sh',
        semantic: { state: 'unknown' },
      };
    }
  },

  // Whether the gateway already holds an engine key. The key itself is never
  // sent to the browser, so this is all the setup screen can know.
  getSettings: async () => {
    const response = await client.get('/settings', { timeout: 5000 });
    return response.data;
  },

  // The gateway checks the key against the engine and stores it on this
  // machine. It deliberately does not live in localStorage: the browser never
  // needs it, and a file only this user can read is the safer place for it.
  saveApiKey: async (apiKey) => {
    try {
      const response = await client.post(
        '/settings/api-key',
        { api_key: apiKey },
        { timeout: 20000 }
      );

      return response.data;
    } catch (error) {
      if (error.response) {
        throw {
          status: error.response.status,
          message: errorMessage(error.response.data, 'Could not save the key.'),
        };
      }

      throw {
        status: 500,
        message: 'Local gateway not reachable. Start it with ./start.sh',
      };
    }
  },

  // No user id: the gateway derives the owner from the API key it holds, so
  // anything sent here would be ignored.
  uploadDocument: async (file) => {
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await client.post('/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });

      return response.data;
    } catch (error) {
      if (error.response) {
        throw {
          status: error.response.status,
          message: errorMessage(error.response.data, 'Upload failed.'),
        };
      }

      throw {
        status: 500,
        message: 'Backend not reachable. Please check FastAPI server.',
      };
    }
  },

  getDocuments: async () => {
    try {
      const response = await client.get('/documents');

      return response.data;
    } catch (error) {
      if (error.response) {
        throw {
          status: error.response.status,
          message: errorMessage(error.response.data, 'Failed to load documents.'),
        };
      }

      throw {
        status: 500,
        message: 'Backend not reachable. Please check FastAPI server.',
      };
    }
  },

  renameDocument: async ({ documentId, newFileName }) => {
    try {
      const response = await client.patch(`/documents/${documentId}/rename`, {
        new_file_name: newFileName,
      });

      return response.data;
    } catch (error) {
      if (error.response) {
        throw {
          status: error.response.status,
          message: errorMessage(error.response.data, 'Document rename failed.'),
        };
      }

      throw {
        status: 500,
        message: 'Backend not reachable. Please check FastAPI server.',
      };
    }
  },

  deleteDocument: async (documentId) => {
    try {
      const response = await client.delete(`/documents/${documentId}`);

      return response.data;
    } catch (error) {
      if (error.response) {
        throw {
          status: error.response.status,
          message: errorMessage(error.response.data, 'Document delete failed.'),
        };
      }

      throw {
        status: 500,
        message: 'Backend not reachable. Please check FastAPI server.',
      };
    }
  },

  sendChatMessage: async ({
    query,
    language = 'english',
    sessionId = 'test_session_01',
    documentId = null,
    documentIds = [],
    documentMode = 'single',
  }) => {
    const normalizedLanguage = normalizeLanguage(language);
    const normalizedDocumentMode = normalizeDocumentMode(documentMode);
    const cleanedDocumentIds = cleanDocumentIds(documentIds);

    let finalDocumentId = null;
    let finalDocumentIds = [];

    if (normalizedDocumentMode === 'single') {
      finalDocumentId = documentId || null;
      finalDocumentIds = [];
    }

    if (normalizedDocumentMode === 'multiple') {
      finalDocumentId = null;
      finalDocumentIds = cleanedDocumentIds;
    }

    if (normalizedDocumentMode === 'all') {
      finalDocumentId = null;
      finalDocumentIds = [];
    }

    if (normalizedDocumentMode === 'single' && !finalDocumentId) {
      throw {
        status: 400,
        message: 'No selected PDF found. Please select one PDF and save.',
      };
    }

    if (normalizedDocumentMode === 'multiple' && finalDocumentIds.length < 2) {
      throw {
        status: 400,
        message: 'Please select at least 2 PDFs for multi-document mode.',
      };
    }

    const payload = {
      query,
      language: normalizedLanguage,
      session_id: sessionId,
      document_mode: normalizedDocumentMode,
      document_id: finalDocumentId,
      document_ids: finalDocumentIds,
    };

    console.log('[KRISH AI] Sending chat payload:', payload);

    try {
      const response = await client.post('/chat', payload);
      return response.data;
    } catch (error) {
      if (error.response) {
        throw {
          status: error.response.status,
          message: errorMessage(error.response.data, 'Chat request failed.'),
        };
      }

      throw {
        status: 500,
        message: 'Backend not reachable. Please check FastAPI server.',
      };
    }
  },

  generateSpeech: async ({
    text,
    language = 'english',
    voice = null,
  }) => {
    const normalizedLanguage = normalizeLanguage(language);

    try {
      const response = await client.post(
        '/tts',
        {
          text,
          language: normalizedLanguage,
          voice,
        },
        {
          responseType: 'blob',
          timeout: 120000,
        }
      );

      const audioBlob = new Blob([response.data], { type: 'audio/mpeg' });

      console.log('[KRISH AI] TTS blob size:', audioBlob.size);
      console.log('[KRISH AI] TTS language:', normalizedLanguage);

      if (!audioBlob.size) {
        throw {
          status: 500,
          message: 'Empty audio file received from backend.',
        };
      }

      return URL.createObjectURL(audioBlob);
    } catch (error) {
      console.error('[KRISH AI] TTS API error:', error);

      if (error.response) {
        throw {
          status: error.response.status,
          message: errorMessage(error.response.data, 'Voice generation failed.'),
        };
      }

      throw {
        status: 500,
        message: error.message || 'Voice generation failed.',
      };
    }
  },

  getChatSessions: async () => {
    try {
      const response = await client.get('/chat-sessions');

      return response.data;
    } catch (error) {
      if (error.response) {
        throw {
          status: error.response.status,
          message: errorMessage(error.response.data, 'Failed to load chat sessions.'),
        };
      }

      throw {
        status: 500,
        message: 'Backend not reachable. Please check FastAPI server.',
      };
    }
  },

  getChatHistory: async (sessionId) => {
    try {
      const response = await client.get(`/chat-history/${sessionId}`);

      return response.data;
    } catch (error) {
      if (error.response) {
        throw {
          status: error.response.status,
          message: errorMessage(error.response.data, 'Failed to load chat history.'),
        };
      }

      throw {
        status: 500,
        message: 'Backend not reachable. Please check FastAPI server.',
      };
    }
  },

  deleteChatSession: async (sessionId) => {
    try {
      const response = await client.delete(`/chat-sessions/${sessionId}`);

      return response.data;
    } catch (error) {
      if (error.response) {
        throw {
          status: error.response.status,
          message: errorMessage(error.response.data, 'Conversation delete failed.'),
        };
      }

      throw {
        status: 500,
        message: 'Backend not reachable. Please check FastAPI server.',
      };
    }
  },
};

/**
 * Cloud dashboard API. Accounts and API keys, never documents.
 */
export const cloud = {
  signup: async (email, password) => {
    try {
      const response = await cloudClient.post('/v1/auth/signup', { email, password });
      session.set(response.data.access_token);
      return response.data;
    } catch (error) {
      throw cloudError(error, 'Could not create the account.');
    }
  },

  login: async (email, password) => {
    try {
      const response = await cloudClient.post('/v1/auth/login', { email, password });
      session.set(response.data.access_token);
      return response.data;
    } catch (error) {
      throw cloudError(error, 'Could not sign in.');
    }
  },

  logout: () => session.clear(),

  me: async () => {
    try {
      const response = await cloudClient.get('/v1/auth/me');
      return response.data;
    } catch (error) {
      throw cloudError(error, 'Could not load the account.');
    }
  },

  // Which OAuth buttons to render. A button for a provider the server has no
  // credentials for is a button that fails when clicked.
  providers: async () => {
    try {
      const response = await cloudClient.get('/v1/auth/providers');
      return response.data.providers || [];
    } catch {
      return [];
    }
  },

  // A full page navigation, not an XHR: the provider's consent screen has to
  // render in the address bar, and its redirect back must hit the browser.
  startOAuth: (providerId) => {
    const base = import.meta.env.VITE_KRISH_ENGINE_URL || 'http://localhost:8000';
    window.location.assign(`${base}/v1/auth/${providerId}/login`);
  },

  getKeys: async () => {
    try {
      const response = await cloudClient.get('/v1/keys');
      return response.data;
    } catch (error) {
      throw cloudError(error, 'Could not load API keys.');
    }
  },

  // The plaintext token is in this response and nowhere else, ever again -
  // the engine stores only a hash.
  generateKey: async (name) => {
    try {
      const response = await cloudClient.post('/v1/keys/generate', { name });
      return response.data;
    } catch (error) {
      throw cloudError(error, 'Could not generate a key.');
    }
  },

  // Scaffold. The endpoint does not exist yet; a 404 is reported as "not
  // wired" rather than as a failure, so adding the Python side later needs no
  // change here.
  createCheckoutSession: async (plan = 'pro') => {
    try {
      const response = await cloudClient.post('/v1/billing/checkout', { plan });

      return response.data;
    } catch (error) {
      if (error.response?.status === 404) {
        throw {
          status: 404,
          message: 'Checkout is not wired up yet - no Stripe backend behind this button.',
        };
      }

      throw cloudError(error, 'Could not start checkout.');
    }
  },

  // Stripe's hosted portal: invoices, cards and cancellation. Needs a
  // stripe_customer_id, which only exists once an account has checked out.
  createPortalSession: async () => {
    try {
      const response = await cloudClient.post('/v1/billing/portal');

      return response.data;
    } catch (error) {
      if (error.response?.status === 404) {
        throw {
          status: 404,
          message: 'The billing portal is not wired up on this server yet.',
        };
      }

      throw cloudError(error, 'Could not open the billing portal.');
    }
  },

  revokeKey: async (keyId) => {
    try {
      const response = await cloudClient.delete(`/v1/keys/${keyId}`);
      return response.data;
    } catch (error) {
      throw cloudError(error, 'Could not revoke the key.');
    }
  },
};
