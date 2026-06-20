import { useRef, type ChangeEvent } from 'react';
import { CalendarClock, Upload, MapPin, AlertCircle } from 'lucide-react';

export interface ScheduleEvent {
  id: string;
  title: string;
  date: string;
  time: string;
  location?: string;
  start: string; // ISO, fuer Sortierung/Filterung
}

interface ScheduleViewProps {
  events: ScheduleEvent[];
  isLoading: boolean;
  onUpload: (file: File) => Promise<void>;
}

export function ScheduleView({ events, isLoading, onUpload }: ScheduleViewProps) {
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

  // Nur kommende Termine, die naechsten 5.
  const now = Date.now();
  const upcoming = events
    .filter((e) => new Date(e.start).getTime() >= now)
    .slice(0, 5);

  const renderUploadButton = () => (
    <div className="pt-3 border-t border-white/10">
      <input
        ref={fileInputRef}
        type="file"
        accept=".ics,.ical"
        onChange={handleFileChange}
        className="hidden"
      />
      <button
        type="button"
        onClick={handleUploadClick}
        className="w-full inline-flex items-center justify-center gap-2 px-3 py-2 bg-white/10 hover:bg-white/15 border border-white/10 rounded-xl text-sm font-medium text-white transition"
      >
        <Upload className="w-4 h-4 text-indigo-300" />
        Stundenplan (iCal) hochladen
      </button>
      <p className="text-[11px] text-gray-400 mt-2">KUSSS-iCal-Datei (.ics) mit deinen Terminen hochladen.</p>
    </div>
  );

  if (isLoading) {
    return (
      <div className="p-4 bg-white/5 border border-white/10 rounded-xl">
        <p className="text-xs text-gray-400">Laden...</p>
      </div>
    );
  }

  if (events.length === 0) {
    return (
      <div className="p-4 bg-white/5 border border-white/10 rounded-xl space-y-4">
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <AlertCircle className="w-4 h-4" />
          <span>Kein Stundenplan vorhanden</span>
        </div>
        {renderUploadButton()}
      </div>
    );
  }

  return (
    <div className="p-4 bg-gradient-to-br from-indigo-500/20 to-blue-500/10 border border-indigo-400/30 rounded-xl space-y-4">
      <div className="flex items-center gap-2">
        <CalendarClock className="w-5 h-5 text-indigo-400" />
        <h3 className="text-sm font-semibold text-white">Naechste Termine</h3>
      </div>

      <div className="space-y-2">
        {upcoming.length === 0 && (
          <p className="text-xs text-gray-400">Keine kommenden Termine.</p>
        )}
        {upcoming.map((e) => (
          <div key={e.id} className="bg-white/5 rounded-lg p-2.5 border border-white/10">
            <p className="text-sm font-medium text-white truncate">{e.title}</p>
            <p className="text-xs text-indigo-200">{e.date}, {e.time}</p>
            {e.location && (
              <p className="text-[11px] text-gray-400 flex items-center gap-1">
                <MapPin className="w-3 h-3" /> {e.location}
              </p>
            )}
          </div>
        ))}
      </div>

      {renderUploadButton()}
    </div>
  );
}
