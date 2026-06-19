import { useRef, type ChangeEvent } from 'react';
import { TrendingUp, BookOpen, AlertCircle } from 'lucide-react';

interface StudyProgressData {
  ects_total: number;
  passed: number;
  failed: number;
  total: number;
  grade_average?: number;
}

interface StudyProgressViewProps {
  data: StudyProgressData | null;
  isLoading: boolean;
  onUpload: (file: File) => Promise<void>;
}

export function StudyProgressView({ data, isLoading, onUpload }: StudyProgressViewProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      await onUpload(file);
      event.target.value = '';
    }
  };

  if (isLoading) {
    return (
      <div className="p-4 bg-white/5 border border-white/10 rounded-xl">
        <p className="text-xs text-gray-400">Laden...</p>
      </div>
    );
  }

  const renderUploadButton = () => (
    <div className="pt-3 border-t border-white/10">
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,.csv"
        onChange={handleFileChange}
        className="hidden"
      />
      <button
        type="button"
        onClick={handleUploadClick}
        className="w-full inline-flex items-center justify-center gap-2 px-3 py-2 bg-white/10 hover:bg-white/15 border border-white/10 rounded-xl text-sm font-medium text-white transition"
      >
        <BookOpen className="w-4 h-4 text-teal-300" />
        Studienerfolg hochladen
      </button>
      <p className="text-[11px] text-gray-400 mt-2">PDF oder CSV mit den KUSSS-Studienerfolgdaten hochladen.</p>
    </div>
  );

  if (!data) {
    return (
      <div className="p-4 bg-white/5 border border-white/10 rounded-xl space-y-4">
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <AlertCircle className="w-4 h-4" />
          <span>Keine Daten vorhanden</span>
        </div>
        {renderUploadButton()}
      </div>
    );
  }

  return (
    <div className="p-4 bg-gradient-to-br from-teal-500/20 to-cyan-500/10 border border-teal-400/30 rounded-xl space-y-4">
      {/* Überschrift */}
      <div className="flex items-center gap-2">
        <TrendingUp className="w-5 h-5 text-teal-400" />
        <h3 className="text-sm font-semibold text-white">Dein Studienfortschritt</h3>
      </div>

      {/* Statistiken Grid */}
      <div className="grid grid-cols-2 gap-3">
        {/* ECTS */}
        <div className="bg-white/5 rounded-lg p-3 border border-white/10 min-w-0">
          <p className="text-xs text-gray-400 mb-1 break-words">ECTS (bestanden)</p>
          <p className="text-lg font-bold text-teal-300">{data.ects_total.toFixed(1)}</p>
        </div>

        {/* Durchschnitt */}
        <div className="bg-white/5 rounded-lg p-3 border border-white/10 min-w-0">
          <p className="text-xs text-gray-400 mb-1 break-words">Notendurchschnitt</p>
          <p className="text-lg font-bold text-teal-300">
            {data.grade_average ? data.grade_average.toFixed(1) : 'N/A'}
          </p>
        </div>

        {/* Einträge gesamt */}
        <div className="bg-white/5 rounded-lg p-3 border border-white/10 min-w-0">
          <p className="text-xs text-gray-400 mb-1 break-words">Einträge Gesamt</p>
          <p className="text-lg font-bold text-white">{data.total}</p>
        </div>

        {/* Nicht bestanden */}
        <div className="bg-white/5 rounded-lg p-3 border border-white/10 min-w-0">
          <p className="text-xs text-gray-400 mb-1 break-words">Nicht bestanden</p>
          <p className={`text-lg font-bold ${data.failed > 0 ? 'text-red-400' : 'text-green-400'}`}>
            {data.failed}
          </p>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs">
          <span className="text-gray-400">Erfolgsquote</span>
          <span className="text-teal-300 font-semibold">
            {data.total > 0 ? Math.round((data.passed / data.total) * 100) : 0}%
          </span>
        </div>
        <div className="w-full h-1.5 bg-white/10 rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-teal-400 to-cyan-400 transition-all"
            style={{
              width: `${data.total > 0 ? (data.passed / data.total) * 100 : 0}%`,
            }}
          />
        </div>
      </div>

      {/* Upload Button */}
      <div className="pt-3 border-t border-white/10">
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.csv"
          onChange={handleFileChange}
          className="hidden"
        />
        <button
          type="button"
          onClick={handleUploadClick}
          className="w-full inline-flex items-center justify-center gap-2 px-3 py-2 bg-white/10 hover:bg-white/15 border border-white/10 rounded-xl text-sm font-medium text-white transition"
        >
          <BookOpen className="w-4 h-4 text-teal-300" />
          Studienerfolg hochladen
        </button>
        <p className="text-[11px] text-gray-400 mt-2">PDF oder CSV mit den KUSSS-Studienerfolgdaten hochladen.</p>
      </div>
    </div>
  );
}
