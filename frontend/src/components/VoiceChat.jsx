import React, { useState, useRef } from 'react';
import { Mic, MicOff, Send, Loader2 } from 'lucide-react';
import { sendChatMessage } from '../services/api';

const VoiceChat = () => {
  const [query, setQuery] = useState('');
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isListening, setIsListening] = useState(false);

  const handleListen = () => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new SpeechRecognition();
    recognition.lang = 'ta-IN'; // Tamil (India)
    
    recognition.onstart = () => setIsListening(true);
    recognition.onend = () => setIsListening(false);
    recognition.onresult = (event) => setQuery(event.results[0][0].transcript);
    
    recognition.start();
  };

  const handleSendMessage = async (e) => {
    e?.preventDefault();
    if (!query.trim()) return;

    setMessages(prev => [...prev, { text: query, sender: 'user' }]);
    const currentQuery = query;
    setQuery('');
    setIsLoading(true);

    try {
      const response = await sendChatMessage(currentQuery, 'tamil', 'session_01', 'test_user_01');
      setMessages(prev => [...prev, { text: response.answer, sender: 'bot' }]);
    } catch (error) {
      setMessages(prev => [...prev, { text: "Backend error occurred.", sender: 'error' }]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: '600px', margin: '50px auto', padding: '20px' }}>
      <h2>🎙️ Krish AI Assistant</h2>
      <div style={{ height: '400px', border: '1px solid #ccc', padding: '10px', overflowY: 'scroll', marginBottom: '10px' }}>
        {messages.map((m, i) => <p key={i}><b>{m.sender}:</b> {m.text}</p>)}
        {isLoading && <p>AI is thinking...</p>}
      </div>
      <form onSubmit={handleSendMessage} style={{ display: 'flex', gap: '10px' }}>
        <button type="button" onClick={handleListen} style={{ background: isListening ? 'red' : 'green', color: 'white' }}>
          {isListening ? <MicOff/> : <Mic/>}
        </button>
        <input value={query} onChange={(e) => setQuery(e.target.value)} style={{ flex: 1 }} />
        <button type="submit"><Send/></button>
      </form>
    </div>
  );
};

export default VoiceChat;