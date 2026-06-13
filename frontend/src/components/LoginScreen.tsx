import { useState } from 'react';
import { ArrowRight, Sparkles } from 'lucide-react';

interface LoginScreenProps {
  onLogin: (username: string) => void;
}

export function LoginScreen({ onLogin }: LoginScreenProps) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (username.trim()) {
      onLogin(username);
    }
  };

  return (
    <div className="size-full flex items-center justify-center bg-gradient-to-br from-[#0a0a0a] via-[#1a1a1a] to-[#0f1f15] relative overflow-hidden">
      {/* Animated Background Elements */}
      <div className="absolute inset-0 overflow-hidden">
        <div className="absolute top-20 left-20 w-96 h-96 bg-white/20 rounded-full blur-3xl animate-pulse"></div>
        <div className="absolute bottom-20 right-20 w-96 h-96 bg-white/10 rounded-full blur-3xl animate-pulse" style={{ animationDelay: '1s' }}></div>
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-white/5 rounded-full blur-3xl"></div>
      </div>

      {/* Grid Pattern */}
      <div className="absolute inset-0 opacity-[0.03]">
        <svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <pattern id="futuristicGrid" width="80" height="80" patternUnits="userSpaceOnUse">
              <path d="M 80 0 L 0 0 0 80" fill="none" stroke="#ffffff" strokeWidth="1"/>
              <circle cx="0" cy="0" r="2" fill="#ffffff" opacity="0.5"/>
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#futuristicGrid)" />
        </svg>
      </div>

      {/* Login Card */}
      <div className="relative z-10 w-full max-w-md mx-4">
        <div className="bg-white/5 backdrop-blur-2xl rounded-3xl border border-white/10 shadow-2xl p-8 relative overflow-hidden">
          {/* Card Glow Effect */}
          <div className="absolute inset-0 bg-gradient-to-br from-white/10 via-transparent to-transparent opacity-50"></div>

          <div className="relative z-10">
            {/* Logo */}
            <div className="flex justify-center mb-8">
              <div className="relative w-32 h-32 flex items-center justify-center">
                <img src="/src/imports/image-1.png" alt="JKU Logo" className="w-full h-full object-contain opacity-90" />
              </div>
            </div>

            {/* Title */}
            <div className="text-center mb-8">
              <h1 className="text-3xl font-bold text-white mb-2 flex items-center justify-center gap-2">
                JKU AI Assistant
                <Sparkles className="w-6 h-6 text-white" />
              </h1>
              <p className="text-gray-400">Willkommen in der Zukunft des Lernens</p>
            </div>

            {/* Form */}
            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label htmlFor="username" className="block text-sm font-medium text-gray-300 mb-2">
                  Benutzername
                </label>
                <input
                  id="username"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full px-4 py-3.5 bg-white/5 border border-white/10 rounded-xl text-white placeholder:text-gray-500 focus:ring-2 focus:ring-white focus:border-transparent outline-none transition-all backdrop-blur-xl"
                  placeholder="k12345678"
                  required
                />
              </div>

              <div className="flex items-center text-sm">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" className="w-4 h-4 rounded border-white/20 bg-white/5 text-white focus:ring-white" />
                  <span className="text-gray-400">Angemeldet bleiben</span>
                </label>
              </div>

              <button
                type="submit"
                className="relative w-full bg-gradient-to-r from-white to-gray-200 text-black py-3.5 rounded-xl font-medium group overflow-hidden transition-all hover:shadow-lg hover:shadow-white/50"
              >
                <div className="absolute inset-0 bg-gradient-to-r from-gray-100 to-white opacity-0 group-hover:opacity-100 transition-opacity"></div>
                <span className="relative flex items-center justify-center gap-2">
                  Anmelden
                  <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
                </span>
              </button>
            </form>

            <div className="mt-6 text-center text-sm text-gray-400">
              Neu hier?{' '}
              <a href="#" className="text-white hover:text-gray-300 font-medium transition">
                Account erstellen
              </a>
            </div>
          </div>
        </div>

        <p className="text-center text-gray-500 text-xs mt-6">
          © 2026 Johannes Kepler Universität Linz
        </p>
      </div>
    </div>
  );
}
