import { useState, useRef, useEffect } from 'react';
import { Send, Mic, Sparkles, Calendar, Clock } from 'lucide-react';

interface Message {
  id: number;
  text: string;
  sender: 'user' | 'assistant';
  timestamp: Date;
  actionCard?: {
    type: 'schedule' | 'room' | 'mensa' | 'campus';
    title: string;
    items?: string[];
  };
}

interface ChatInterfaceProps {
  username?: string;
  onLogout?: () => void;
}

export function ChatInterface({ username, onLogout }: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 1,
      text: 'Willkommen beim JKU AI Assistant! Ich bin Ihr Begleiter für alles rund um Ihr Studium. Wie kann ich Ihnen heute helfen?',
      sender: 'assistant',
      timestamp: new Date(),
      actionCard: {
        type: 'schedule',
        title: 'Schnellzugriffe',
        items: ['Prüfungstermine', 'Stundenplan'],
      },
    },
  ]);
  const [inputText, setInputText] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [studyProgram, setStudyProgram] = useState<'bachelor' | 'master'>('bachelor');
  const [error, setError] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!inputText.trim()) {
      setError('Bitte stellen Sie eine Frage, damit der Assistant antworten kann.');
      return;
    }

    const userMessage: Message = {
      id: messages.length + 1,
      text: inputText.trim(),
      sender: 'user',
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputText('');
    setIsTyping(true);

    try {
      const response = await fetch('http://127.0.0.1:8000/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: inputText,
          study_program_id: studyProgram,
        }),
      });

      if (!response.ok) {
        const errorBody = await response.json();
        throw new Error(errorBody.detail || 'Fehler beim Chatten mit dem Backend.');
      }

      const data = await response.json();
      const assistantMessage: Message = {
        id: messages.length + 2,
        text: data.response,
        sender: 'assistant',
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err) {
      console.error('Chat error:', err);
      setError('Die Anfrage konnte nicht verarbeitet werden. Bitte prüfen Sie das Backend.');
    } finally {
      setIsTyping(false);
    }
  };

  const handleQuickAction = (action: string) => {
    if (action === 'Stundenplan') {
      setInputText('Zeige mir meinen Stundenplan.');
    } else if (action === 'Prüfungstermine') {
      setInputText('Zeige mir meine Prüfungstermine.');
    }
  };

  return (
    <div className="w-full h-screen flex bg-gradient-to-br from-[#0a0a0a] via-[#1a1a1a] to-[#0f1f15] relative overflow-hidden">
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-20 right-20 w-96 h-96 bg-white/10 rounded-full blur-3xl animate-pulse"></div>
        <div className="absolute bottom-40 left-40 w-96 h-96 bg-white/5 rounded-full blur-3xl animate-pulse" style={{ animationDelay: '2s' }}></div>
      </div>

      <div className="absolute inset-0 opacity-[0.02]">
        <svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <pattern id="chatGrid" width="100" height="100" patternUnits="userSpaceOnUse">
              <path d="M 100 0 L 0 0 0 100" fill="none" stroke="#ffffff" strokeWidth="0.5" />
              <circle cx="0" cy="0" r="1.5" fill="#ffffff" opacity="0.4" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#chatGrid)" />
        </svg>
      </div>

      <div className="hidden md:flex md:w-64 relative z-10 flex-col">
        <div className="bg-white/5 backdrop-blur-xl border-r border-white/10 h-full flex flex-col">
          <div className="p-5 border-b border-white/10">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-14 h-14 flex items-center justify-center">
                <img src="/src/imports/image-1.png" alt="JKU Logo" className="w-full h-full object-contain opacity-90" />
              </div>
              <div>
                <h2 className="text-white font-semibold">JKU AI</h2>
                <p className="text-xs text-gray-400">Assistant</p>
              </div>
            </div>
          </div>
          <div className="p-4 text-sm text-gray-400">
            <p>Wählen Sie Ihren Studiengang für kontextbezogene Antworten aus. Uploads von iCal-/ICS-Dateien sind aktuell nicht aktiviert.</p>
          </div>
        </div>
      </div>

      <div className="flex-1 flex flex-col relative z-10">
        <div className="bg-white/5 backdrop-blur-xl border-b border-white/10">
          <div className="px-6 py-4 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Sparkles className="w-6 h-6 text-white" />
              <h1 className="text-xl font-semibold text-white">JKU AI Assistant</h1>
            </div>
            {username && (
              <div className="hidden sm:flex items-center gap-2 px-4 py-2 bg-white/5 rounded-xl text-gray-300">
                <span>{username}</span>
              </div>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          <div className="max-w-4xl mx-auto px-4 py-8 space-y-6">
            {messages.map((message) => (
              <div key={message.id}>
                <div className={`flex ${message.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[80%] ${message.sender === 'user' ? 'bg-gradient-to-br from-white to-gray-200 text-black rounded-2xl rounded-tr-sm shadow-lg shadow-white/30' : 'bg-white/5 backdrop-blur-xl border border-white/10 text-white rounded-2xl rounded-tl-sm'} px-5 py-4`}>
                    <p className="text-[15px] leading-relaxed whitespace-pre-wrap">{message.text}</p>
                    <p className={`text-xs mt-2 ${message.sender === 'user' ? 'text-black/70' : 'text-gray-500'}`}>
                      {message.timestamp.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })}
                    </p>
                  </div>
                </div>

                {message.actionCard && (
                  <div className="mt-4 flex justify-start">
                    <div className="max-w-[80%] bg-white/5 backdrop-blur-xl border border-white/10 rounded-2xl p-4">
                      <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
                        <Sparkles className="w-4 h-4 text-white" />
                        {message.actionCard.title}
                      </h3>
                      <div className="grid grid-cols-2 gap-2">
                        {message.actionCard.items?.map((item, idx) => (
                          <button
                            key={idx}
                            onClick={() => handleQuickAction(item)}
                            className="flex items-center justify-center gap-2 px-4 py-3 bg-white/5 hover:bg-white/20 border border-white/10 hover:border-white/50 rounded-xl transition-all text-sm text-gray-300 hover:text-white group"
                          >
                            {item === 'Prüfungstermine' && <Clock className="w-4 h-4" />}
                            {item === 'Stundenplan' && <Calendar className="w-4 h-4" />}
                            <span>{item}</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))}

            {isTyping && (
              <div className="flex justify-start">
                <div className="bg-white/5 backdrop-blur-xl border border-white/10 rounded-2xl rounded-tl-sm px-5 py-4">
                  <div className="flex gap-1.5 items-center">
                    <div className="w-2.5 h-2.5 bg-white rounded-full animate-bounce"></div>
                    <div className="w-2.5 h-2.5 bg-white rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                    <div className="w-2.5 h-2.5 bg-white rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </div>

        <div className="px-4 py-5">
          <div className="max-w-4xl mx-auto">
            <form onSubmit={handleSendMessage}>
              <div className="mb-4 flex flex-wrap items-center gap-3">
                <span className="text-sm text-gray-400">Studiengang:</span>
                <button
                  type="button"
                  onClick={() => setStudyProgram('bachelor')}
                  className={`px-4 py-2 rounded-2xl transition text-sm ${studyProgram === 'bachelor' ? 'bg-white text-black' : 'bg-white/5 text-gray-300 hover:bg-white/10'}`}
                >
                  Bachelor Wirtschaftsinformatik
                </button>
                <button
                  type="button"
                  onClick={() => setStudyProgram('master')}
                  className={`px-4 py-2 rounded-2xl transition text-sm ${studyProgram === 'master' ? 'bg-white text-black' : 'bg-white/5 text-gray-300 hover:bg-white/10'}`}
                >
                  Master Wirtschaftsinformatik
                </button>
              </div>

              <div className="relative flex items-center gap-3 bg-white/5 backdrop-blur-xl border-2 border-white/10 focus-within:border-white rounded-2xl px-2 py-2 transition-all shadow-lg shadow-black/20">
                <input
                  type="text"
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  placeholder="Fragen Sie den JKU AI Assistant..."
                  className="flex-1 px-2 py-3 bg-transparent outline-none text-white placeholder:text-gray-500 text-[15px]"
                />
                <button
                  type="button"
                  className="flex-shrink-0 p-3 hover:bg-white/10 rounded-xl transition text-gray-400 hover:text-white"
                  title="Spracheingabe"
                >
                  <Mic className="w-5 h-5" />
                </button>
                <div className="relative">
                  <div className="absolute inset-0 bg-white blur-lg opacity-50" />
                  <button
                    type="submit"
                    className="relative flex-shrink-0 p-3 bg-gradient-to-br from-white to-gray-200 text-black rounded-xl hover:shadow-lg hover:shadow-white/50 transition-all"
                  >
                    <Send className="w-5 h-5" />
                  </button>
                </div>
              </div>

              {error && (
                <p className="text-xs text-red-400 text-center mt-3">{error}</p>
              )}
              <p className="text-xs text-gray-500 text-center mt-3">
                JKU AI Assistant kann Fehler machen. Überprüfen Sie wichtige Informationen.
              </p>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
