import { Button } from '@/components/ui/button';
import { Calendar as CalendarIcon, ChevronLeft, ChevronRight } from 'lucide-react';
import { Calendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { format } from 'date-fns';
import { cn } from '@/lib/utils';
import { ModeToggle } from '@/components/mode-toggle';
import type { SyncFreshness } from '@/lib/api';
import { syncIndicatorTone, syncStatusHeadline } from '@/lib/sync-display';

interface TopDateBarProps {
  selectedDate: Date;
  onDateChange: (date: Date) => void;
  syncStatus?: { status: string; lastRun: string | null; freshness?: SyncFreshness | null };
  connectionStatus?: 'connected' | 'disconnected' | 'checking';
  rightActions?: React.ReactNode;
  className?: string;
}

export function TopDateBar({ selectedDate, onDateChange, syncStatus, connectionStatus, rightActions, className }: TopDateBarProps) {
  return (
    <header className={cn(
      'glass-nav h-14 px-6 flex items-center justify-between select-none flex-shrink-0',
      className
    )}>
      {/* Left: Date Navigator */}
      <div className="flex items-center gap-5">
        {/* Date Navigator Pill */}
        <div className="flex items-center gap-1 glass-tab rounded-lg p-0.5">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 rounded-md text-white/40 hover:bg-white/[0.08] hover:text-white"
            onClick={() => {
              const prev = new Date(selectedDate);
              prev.setDate(prev.getDate() - 1);
              onDateChange(prev);
            }}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>

          <Popover>
            <PopoverTrigger asChild>
              <div className="flex items-center gap-2 px-2 py-1 text-xs font-medium text-white/70 cursor-pointer hover:text-white transition-colors">
                <CalendarIcon className="w-3.5 h-3.5 text-enso-blue" />
                <span>{format(selectedDate, 'MMM d, yyyy')}</span>
              </div>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <Calendar
                mode="single"
                selected={selectedDate}
                onSelect={(d) => d && onDateChange(d)}
                initialFocus
              />
            </PopoverContent>
          </Popover>

          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 rounded-md text-white/40 hover:bg-white/[0.08] hover:text-white"
            onClick={() => {
              const next = new Date(selectedDate);
              next.setDate(next.getDate() + 1);
              onDateChange(next);
            }}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>

          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2.5 ml-1 text-[11px] font-semibold glass-tab text-enso-blue hover:text-white rounded-lg"
            onClick={() => onDateChange(new Date())}
          >
            Today
          </Button>
        </div>
      </div>

      {/* Right: Sync Status */}
      <div className="flex items-center gap-4 shrink-0">
        {connectionStatus && (
          <div className="flex items-center gap-2 text-[11px] text-white/35">
            <span className={cn(
              'w-1.5 h-1.5 rounded-full',
              connectionStatus === 'checking' ? 'bg-score-yellow pulse-dot' :
              connectionStatus === 'connected' ? 'bg-score-green pulse-dot' :
              'bg-living-coral'
            )} />
            {connectionStatus === 'checking' ? 'Checking backend' :
              connectionStatus === 'connected' ? 'Backend online' : 'Backend offline'}
          </div>
        )}
        {syncStatus && (
          <div className="flex items-center gap-2 text-[11px] text-white/35">
            <span className={cn(
              'w-1.5 h-1.5 rounded-full',
              syncIndicatorTone(syncStatus.status, syncStatus.freshness ?? null) === 'busy'
                ? 'bg-score-yellow pulse-dot'
                : syncIndicatorTone(syncStatus.status, syncStatus.freshness ?? null) === 'error'
                  ? 'bg-living-coral'
                  : syncIndicatorTone(syncStatus.status, syncStatus.freshness ?? null) === 'fresh'
                    ? 'bg-score-green pulse-dot'
                    : syncIndicatorTone(syncStatus.status, syncStatus.freshness ?? null) === 'stale'
                      ? 'bg-score-yellow'
                      : 'bg-white/20',
            )} />
            {syncStatusHeadline(
              { status: syncStatus.status, last_run: syncStatus.lastRun },
              syncStatus.freshness ?? null,
            )}
          </div>
        )}
        {rightActions}
        <ModeToggle />
      </div>
    </header>
  );
}
