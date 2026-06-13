import { Clock, Upload, X, Calendar, AlertCircle } from 'lucide-react';
import { useRef } from 'react';

interface ExamEvent {
  id: string;
  title: string;
  date: string;
  time: string;
  location?: string;
  daysUntil?: number;
}

interface ExamsViewProps {
  examsFile: File | null;
  examEvents: ExamEvent[];
  onFileUpload: (file: File) => void;
  onClose: () => void;
}

export function ExamsView({ examsFile, examEvents, onFileUpload, onClose }: ExamsViewProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file && (file.name.endsWith('.ics') || file.name.endsWith('.ical'))) {
      onFileUpload(file);
    }
  };

  const getUrgencyColor = (daysUntil?: number) => {
    if (!daysUntil) return { bg: 'bg-white/10', text: 'text-gray-400', icon: 'text-white' };
    if (daysUntil <= 7) return { bg: 'bg-red-500/20', text: 'text-red-400', icon: 'text-red-400' };
    if (daysUntil <= 14) return { bg: 'bg-yellow-500/20', text: 'text-yellow-400', icon: 'text-yellow-400' };
    return { bg: 'bg-white/10', text: 'text-gray-400', icon: 'text-white' };
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-white/10 backdrop-blur-xl border border-white/20 rounded-3xl max-w-2xl w-full max-h-[90vh] overflow-hidden flex flex-col p-8 relative">
        <button
          onClick={onClose}
          className="absolute top-6 right-6 p-2 hover:bg-white/10 rounded-xl transition"
        >
          <X className="w-5 h-5 text-gray-300" />
        </button>

        <div className="flex items-center gap-3 mb-6">
          <div className="p-3 bg-white/10 rounded-xl">
            <Clock className="w-6 h-6 text-white" />
          </div>
          <h2 className="text-2xl font-semibold text-white">Prüfungstermine</h2>
        </div>

        {!examsFile ? (
          <div className="text-center py-12">
            <div className="mb-6 flex justify-center">
              <div className="p-6 bg-white/5 rounded-2xl">
                <Upload className="w-12 h-12 text-gray-400" />
              </div>
            </div>
            <h3 className="text-xl font-semibold text-white mb-3">
              Keine Prüfungstermine vorhanden
            </h3>
            <p className="text-gray-400 mb-6 max-w-md mx-auto">
              Laden Sie Ihre iCal-Datei (.ics) hoch, damit der JKU AI Assistant Ihre Prüfungstermine verwalten kann.
            </p>

            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileSelect}
              accept=".ics,.ical"
              className="hidden"
            />

            <button
              onClick={() => fileInputRef.current?.click()}
              className="px-6 py-3 bg-gradient-to-br from-white to-gray-200 text-black rounded-xl hover:shadow-lg hover:shadow-white/50 transition-all font-medium inline-flex items-center gap-2"
            >
              <Upload className="w-5 h-5" />
              iCal-Datei hochladen
            </button>
          </div>
        ) : (
          <div className="flex-1 overflow-hidden flex flex-col">
            <div className="bg-white/5 border border-white/10 rounded-2xl p-6 mb-6">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-white/10 rounded-lg">
                    <Calendar className="w-5 h-5 text-white" />
                  </div>
                  <div>
                    <p className="text-white font-medium">{examsFile.name}</p>
                    <p className="text-sm text-gray-400">
                      {(examsFile.size / 1024).toFixed(2)} KB
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="text-sm text-gray-400 hover:text-white transition"
                >
                  Ändern
                </button>
              </div>
            </div>

            <h3 className="text-lg font-semibold text-white mb-4">Alle Prüfungen</h3>

            {/* Exams List - KI Schnittstelle */}
            <div className="flex-1 overflow-y-auto space-y-3">
              {examEvents.length > 0 ? (
                examEvents.map((exam) => {
                  const colors = getUrgencyColor(exam.daysUntil);
                  return (
                    <div
                      key={exam.id}
                      className="bg-white/5 border border-white/10 rounded-xl p-4 hover:bg-white/10 transition"
                    >
                      <div className="flex items-start gap-3">
                        <div className={`p-2 ${colors.bg} rounded-lg`}>
                          <AlertCircle className={`w-4 h-4 ${colors.icon}`} />
                        </div>
                        <div className="flex-1">
                          <p className="text-white font-medium mb-1">{exam.title}</p>
                          <p className="text-sm text-gray-400">{exam.date}, {exam.time}</p>
                          {exam.location && (
                            <p className="text-sm text-gray-500">{exam.location}</p>
                          )}
                          {exam.daysUntil !== undefined && (
                            <div className={`mt-2 inline-block px-2 py-1 ${colors.bg} ${colors.text} text-xs rounded-lg`}>
                              In {exam.daysUntil} Tagen
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })
              ) : (
                <div className="text-center py-8">
                  <p className="text-gray-400">
                    Keine Prüfungstermine gefunden.
                  </p>
                  <p className="text-sm text-gray-500 mt-2">
                    Der AI Assistant wird die iCal-Datei verarbeiten.
                  </p>
                </div>
              )}
            </div>

            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileSelect}
              accept=".ics,.ical"
              className="hidden"
            />
          </div>
        )}
      </div>
    </div>
  );
}
