import { useState, useRef, useEffect } from 'react';
import { Send, Paperclip, FileText, X, Mic, LogOut, Bell, User, LayoutDashboard, Calendar, BookOpen, Coffee, Map, HelpCircle, Sparkles, Clock, MapPin, Utensils } from 'lucide-react';
import { ScheduleView } from './ScheduleView';
import { ExamsView } from './ExamsView';

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
  username: string;
  onLogout: () => void;
}

export function ChatInterface({ username, onLogout }: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 1,
      text: 'Willkommen beim JKU AI Assistant! Ich bin Ihr intelligenter Begleiter für alles rund um Ihr Studium. Wie kann ich Ihnen heute helfen?',
      sender: 'assistant',
      timestamp: new Date(),
      actionCard: {
        type: 'schedule',
        title: 'Schnellzugriffe',
        items: ['Prüfungstermine', 'Stundenplan']
      }
    },
  ]);
  const [inputText, setInputText] = useState('');
  const [attachedFiles, setAttachedFiles] = useState<File[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [activeMenu, setActiveMenu] = useState('dashboard');
  const [showSchedule, setShowSchedule] = useState(false);
  const [showExams, setShowExams] = useState(false);
  const [scheduleFile, setScheduleFile] = useState<File | null>(null);
  const [scheduleIcsText, setScheduleIcsText] = useState<string | null>(null);
  const [examsFile, setExamsFile] = useState<File | null>(null);
  const [examsIcsText, setExamsIcsText] = useState<string | null>(null);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [studyProgram, setStudyProgram] = useState<'bachelor' | 'master'>('bachelor');

  // KI-Schnittstelle: Arrays für Events, die vom AI Assistant befüllt werden können
  const [scheduleEvents, setScheduleEvents] = useState<Array<{
    id: string;
    title: string;
    date: string;
    time: string;
    location?: string;
  }>>([]);

  const [examEvents, setExamEvents] = useState<Array<{
    id: string;
    title: string;
    date: string;
    time: string;
    location?: string;
    daysUntil?: number;
  }>>([]);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleScheduleIcsUpload = (file: File) => {
    setScheduleFile(file);
    file.text()
      .then((text) => {
        setScheduleIcsText(text);
        setAttachmentError(null);
      })
      .catch(() => {
        setAttachmentError('Die iCal-Datei konnte nicht gelesen werden.');
      });
  };

  const handleExamsIcsUpload = (file: File) => {
    setExamsFile(file);
    file.text()
      .then((text) => {
        setExamsIcsText(text);
        setAttachmentError(null);
      })
      .catch(() => {
        setAttachmentError('Die iCal-Datei konnte nicht gelesen werden.');
      });
  };

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();

    if (inputText.trim() || attachedFiles.length > 0) {
      const newMessage: Message = {
        id: messages.length + 1,
        text: inputText.trim() || `${attachedFiles.length} PDF(s) hochgeladen`,
        sender: 'user',
        timestamp: new Date(),
      };

      setMessages([...messages, newMessage]);
      setInputText('');
      setAttachedFiles([]);
      setIsTyping(true);

      console.log('Chat send:', { inputText, attachedFiles });

      fetch('http://127.0.0.1:8000/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: inputText,
          study_program_id: studyProgram,
          schedule_ics: scheduleIcsText,
          exams_ics: examsIcsText,
        }),
      })
        .then((res) => res.json())
        .then((data) => {
          console.log('Chat response:', data);
          const response: Message = {
            id: messages.length + 2,
            text: data.response,
            sender: 'assistant',
            timestamp: new Date(),
          };

          setMessages((prev) => [...prev, response]);
          setIsTyping(false);
        })
        .catch((err) => {
          console.error('Chat error:', err);
          setIsTyping(false);
        });
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    const pdfFiles = files.filter(file => file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf'));
    const invalidFiles = files.filter(file => !(file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')));

    if (pdfFiles.length > 0) {
      setAttachedFiles([...attachedFiles, ...pdfFiles]);
      setAttachmentError(null);
    }

    if (invalidFiles.length > 0) {
      setAttachmentError('Nur PDF-Dateien können hier angehängt werden.');
    }
  };

  const removeFile = (index: number) => {
    setAttachedFiles(attachedFiles.filter((_, i) => i !== index));
  };

  const menuItems = [
    { id: 'dashboard', icon: LayoutDashboard, label: 'Dashboard' },
    { id: 'schedule', icon: Calendar, label: 'Stundenplan' },
    { id: 'exams', icon: Clock, label: 'Prüfungen' },
  ];

  const handleMenuClick = (menuId: string) => {
    setActiveMenu(menuId);
    if (menuId === 'schedule') {
      setShowSchedule(true);
    } else if (menuId === 'exams') {
      setShowExams(true);
    }
  };

  const handleQuickAction = (action: string) => {
    if (action === 'Stundenplan') {
      setShowSchedule(true);
    } else if (action === 'Prüfungstermine') {
      setShowExams(true);
    }
  };

  return (
    <>
      {showSchedule && (
        <ScheduleView
          scheduleFile={scheduleFile}
          scheduleEvents={scheduleEvents}
          onFileUpload={handleScheduleIcsUpload}
          onClose={() => setShowSchedule(false)}
        />
      )}

      {showExams && (
        <ExamsView
          examsFile={examsFile}
          examEvents={examEvents}
          onFileUpload={handleExamsIcsUpload}
          onClose={() => setShowExams(false)}
        />
      )}

<div className="w-full h-screen flex bg-gradient-to-br from-[#0a0a0a] via-[#1a1a1a] to-[#0f1f15] relative overflow-hidden">      {/* Animated Background Elements */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-20 right-20 w-96 h-96 bg-white/10 rounded-full blur-3xl animate-pulse"></div>
        <div className="absolute bottom-40 left-40 w-96 h-96 bg-white/5 rounded-full blur-3xl animate-pulse" style={{ animationDelay: '2s' }}></div>
      </div>

      {/* Grid Pattern */}
      <div className="absolute inset-0 opacity-[0.02]">
        <svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <pattern id="chatGrid" width="100" height="100" patternUnits="userSpaceOnUse">
              <path d="M 100 0 L 0 0 0 100" fill="none" stroke="#ffffff" strokeWidth="0.5"/>
              <circle cx="0" cy="0" r="1.5" fill="#ffffff" opacity="0.4"/>
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#chatGrid)" />
        </svg>
      </div>

      {/* Sidebar */}
      <div className="hidden md:flex md:w-64 relative z-10 flex-col">
        <div className="bg-white/5 backdrop-blur-xl border-r border-white/10 h-full flex flex-col">
          {/* Sidebar Header */}
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

          {/* Menu Items */}
          <div className="flex-1 overflow-y-auto p-3 space-y-1">
            {menuItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeMenu === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => handleMenuClick(item.id)}
                  className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all group ${
                    isActive
                      ? 'bg-white/20 text-white shadow-lg shadow-white/20'
                      : 'text-gray-400 hover:bg-white/5 hover:text-white'
                  }`}
                >
                  <Icon className={`w-5 h-5 ${isActive ? 'drop-shadow-[0_0_8px_rgba(255,255,255,0.8)]' : ''}`} />
                  <span className="text-sm font-medium">{item.label}</span>
                </button>
              );
            })}
          </div>

          {/* User Section */}
          <div className="p-4 border-t border-white/10">
            <div className="flex items-center gap-3 px-3 py-2 bg-white/5 rounded-xl">
              <div className="w-9 h-9 bg-gradient-to-br from-gray-600 to-gray-800 rounded-full flex items-center justify-center">
                <span className="text-white text-sm font-medium">{username?.charAt(0).toUpperCase()}</span>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-white truncate">{username}</p>
                <p className="text-xs text-gray-400">Student</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col relative z-10">
        {/* Header */}
        <div className="bg-white/5 backdrop-blur-xl border-b border-white/10">
          <div className="px-6 py-4 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Sparkles className="w-6 h-6 text-white" />
              <h1 className="text-xl font-semibold text-white">JKU AI Assistant</h1>
            </div>

            <div className="flex items-center gap-2">
              <button className="hidden sm:flex items-center gap-2 px-4 py-2 bg-white/5 hover:bg-white/10 rounded-xl transition">
                <User className="w-4 h-4 text-gray-300" />
                <span className="text-sm text-white">{username}</span>
              </button>
              <button
                onClick={onLogout}
                className="p-2.5 hover:bg-white/10 rounded-xl transition"
                title="Abmelden"
              >
                <LogOut className="w-5 h-5 text-gray-300" />
              </button>
            </div>
          </div>
        </div>

        {/* Messages Area */}
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-4xl mx-auto px-4 py-8 space-y-6">
            {messages.map((message) => (
              <div key={message.id}>
                <div
                  className={`flex ${message.sender === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[80%] ${
                      message.sender === 'user'
                        ? 'bg-gradient-to-br from-white to-gray-200 text-black rounded-2xl rounded-tr-sm shadow-lg shadow-white/30'
                        : 'bg-white/5 backdrop-blur-xl border border-white/10 text-white rounded-2xl rounded-tl-sm'
                    } px-5 py-4`}
                  >
                    <p className="text-[15px] leading-relaxed whitespace-pre-wrap">{message.text}</p>
                    <p
                      className={`text-xs mt-2 ${
                        message.sender === 'user' ? 'text-black/70' : 'text-gray-500'
                      }`}
                    >
                      {message.timestamp.toLocaleTimeString('de-DE', {
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </p>
                  </div>
                </div>

                {/* Action Card */}
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

        {/* Attached Files Display */}
        {attachedFiles.length > 0 && (
          <div className="px-4 pb-3">
            <div className="max-w-4xl mx-auto bg-white/5 backdrop-blur-xl border border-white/10 rounded-2xl p-3">
              <p className="text-sm font-medium text-gray-300 mb-2">Angehängte Dateien:</p>
              <div className="flex flex-wrap gap-2">
                {attachedFiles.map((file, index) => (
                  <div
                    key={index}
                    className="flex items-center gap-2 bg-white/10 rounded-lg px-3 py-2 border border-white/30"
                  >
                    <FileText className="w-4 h-4 text-white" />
                    <span className="text-sm text-white max-w-[200px] truncate">{file.name}</span>
                    <button
                      onClick={() => removeFile(index)}
                      className="text-gray-400 hover:text-red-400 transition ml-1"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Input Area */}
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
              <p className="text-xs text-gray-400 mb-3">
                Der AI Assistant verwendet nur Inhalte aus dem gewählten Studiengang. iCal-Dateien für Stundenplan und Prüfungen werden zusätzlich verarbeitet.
              </p>
              <div className="relative flex items-center gap-3 bg-white/5 backdrop-blur-xl border-2 border-white/10 focus-within:border-white rounded-2xl px-2 py-2 transition-all shadow-lg shadow-black/20">
                <input
                  type="file"
                  ref={fileInputRef}
                  onChange={handleFileSelect}
                  accept=".pdf"
                  multiple
                  className="hidden"
                />

                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="flex-shrink-0 p-3 hover:bg-white/10 rounded-xl transition text-gray-400 hover:text-white"
                  title="Datei hochladen"
                >
                  <Paperclip className="w-5 h-5" />
                </button>

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
                  <div className="absolute inset-0 bg-white blur-lg opacity-50"></div>
                  <button
                    type="submit"
                    disabled={!inputText.trim() && attachedFiles.length === 0}
                    className="relative flex-shrink-0 p-3 bg-gradient-to-br from-white to-gray-200 text-black rounded-xl hover:shadow-lg hover:shadow-white/50 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                  >
                    <Send className="w-5 h-5" />
                  </button>
                </div>
              </div>
            </form>

            {attachmentError && (
              <p className="text-xs text-red-400 text-center mt-3">
                {attachmentError}
              </p>
            )}
            <p className="text-xs text-gray-500 text-center mt-3">
              JKU AI Assistant kann Fehler machen. Überprüfen Sie wichtige Informationen.
            </p>
          </div>
        </div>
      </div>
    </div>
    </>
  );
}
