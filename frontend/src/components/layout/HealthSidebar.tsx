import { useState } from 'react';
import {
  LayoutDashboard,
  HeartPulse,
  Moon,
  Flame,
  ShieldAlert,
  TrendingUp,
  Compass,
  BookOpen,
  Sparkles,
  Sliders,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  MoonStar,
  Plus,
  MoreVertical,
  Trash2,
  Edit2,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Input } from '@/components/ui/input';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import type { AppView } from '@/types/app-view';
import type { Dashboard } from '@/types';
interface NavItem {
  id: AppView;
  label: string;
  icon: React.ElementType;
  section?: 'main' | 'bottom';
  badge?: string;
}

const NAV_ITEMS: NavItem[] = [
  { id: 'today', label: 'Dashboard', icon: LayoutDashboard, section: 'main' },
  { id: 'readiness', label: 'Readiness', icon: HeartPulse, section: 'main' },
  { id: 'sleep', label: 'Sleep', icon: Moon, section: 'main' },
  { id: 'activity', label: 'Activity', icon: Flame, section: 'main' },
  { id: 'resilience', label: 'Stress & Resilience', icon: ShieldAlert, section: 'main' },
  { id: 'trends', label: 'Trends', icon: TrendingUp, section: 'main' },
  { id: 'explorer', label: 'Explorer', icon: Compass, section: 'main', badge: 'NEW' },
  { id: 'journal', label: 'Tags & Journal', icon: BookOpen, section: 'main' },
  { id: 'ai', label: 'AI Analyst', icon: Sparkles, section: 'main', badge: 'NEW' },
];

interface HealthSidebarProps {
  activeView: AppView;
  onViewChange: (view: AppView) => void;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  onSettingsClick?: () => void;
  className?: string;
  syncStatus?: { status: string; lastRun: string | null } | null;
  onSync?: () => void;
  isSyncing?: boolean;

  // Dashboard management
  dashboards?: Dashboard[];
  activeDashboardId?: string;
  onDashboardSelect?: (id: string) => void;
  onDashboardAdd?: () => void;
  onDashboardDelete?: (id: string) => void;
  onDashboardRename?: (id: string, name: string) => void;
}

export function HealthSidebar({
  activeView,
  onViewChange,
  collapsed = false,
  onToggleCollapse,
  onSettingsClick,
  className,
  syncStatus,
  onSync,
  isSyncing = false,
  dashboards = [],
  activeDashboardId,
  onDashboardSelect,
  onDashboardAdd,
  onDashboardDelete,
  onDashboardRename,
}: HealthSidebarProps) {
  const [restMode, setRestMode] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');

  const handleStartEdit = (dashboard: Dashboard) => {
    setEditingId(dashboard.id);
    setEditName(dashboard.name);
  };

  const handleSaveEdit = () => {
    if (editingId && editName.trim() && onDashboardRename) {
      onDashboardRename(editingId, editName.trim());
    }
    setEditingId(null);
  };

  const showDashboards = dashboards.length > 0 && onDashboardSelect;

  return (
    <div className={cn(
      'glass-sidebar flex flex-col h-screen select-none shrink-0 text-white/40 transition-[width] duration-200',
      collapsed ? 'w-16' : 'w-64',
      className
    )}>
      {/* Brand Header */}
      <div className="p-4 flex items-center gap-3 border-b border-white/[0.06]">
        <div className="w-9 h-9 rounded-full bg-white flex items-center justify-center shadow-lg shadow-white/10 flex-shrink-0">
          <span className="text-oura-black font-bold text-base">Ō</span>
        </div>
        {!collapsed && (
          <div>
            <h1 className="font-serif text-lg font-semibold tracking-wide text-white leading-tight">ŌURA</h1>
            <p className="text-[10px] text-white/30 tracking-wider uppercase font-medium">Desktop OS</p>
          </div>
        )}
      </div>

      {/* User Profile Card */}
      {!collapsed && (
      <div className="mx-3 my-3 glass-card rounded-2xl p-3">
        <div className="flex items-center gap-2.5">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-helsinki to-enso-blue flex items-center justify-center flex-shrink-0 shadow-lg">
            <span className="text-white font-bold text-sm">U</span>
          </div>
          <div className="min-w-0">
            <p className="text-white text-sm font-semibold truncate">User</p>
            <p className="text-white/30 text-[11px] truncate">Local export data</p>
          </div>
        </div>
        {/* Ring connection status */}
        <div className="flex items-center justify-between mt-3 pt-3 border-t border-white/[0.06]">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-score-green pulse-dot" />
            <span className="text-white/35 text-[11px] font-medium">
              Export Data
            </span>
          </div>
        </div>
        <div className="flex items-center justify-between mt-1.5">
          <span className="text-white/25 text-[10px]">
            {syncStatus?.lastRun ? `Last sync: ${syncStatus.lastRun}` : 'No sync yet'}
          </span>
          <button
            onClick={onSync}
            disabled={isSyncing}
            className="text-white/40 hover:text-white transition-colors cursor-pointer"
          >
            <RefreshCw className={cn('w-3 h-3', isSyncing && 'animate-spin text-enso-blue')} />
          </button>
        </div>
      </div>
      )}

      {/* Main Navigation */}
      <ScrollArea className="flex-1">
        <div className="px-2 py-1 space-y-0.5">
          {NAV_ITEMS.filter(n => n.section === 'main').map((item) => {
            const Icon = item.icon;
            const isActive = activeView === item.id;
            return (
              <button
                key={item.id}
                onClick={() => onViewChange(item.id)}
                className={cn(
                  'w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 cursor-pointer',
                  collapsed && 'justify-center px-2',
                  isActive
                    ? 'glass-tab text-white shadow-sm'
                    : 'text-white/35 hover:text-white/65 hover:bg-white/[0.03]'
                )}
              >
                <div className="flex items-center gap-3 truncate">
                  <Icon className={cn('w-4 h-4 shrink-0', isActive && 'text-enso-blue')} />
                  {!collapsed && <span className="truncate">{item.label}</span>}
                </div>
                {!collapsed && item.badge && (
                  <span className="text-[10px] bg-living-coral/90 text-white px-1.5 py-0.5 rounded-md font-semibold tracking-wide">
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}

          {/* Custom Dashboards Section */}
          {!collapsed && showDashboards && (
            <div className="mt-4">
              <p className="px-3 text-[10px] font-semibold tracking-widest text-white/25 uppercase mb-1.5">
                Dashboards
              </p>
              <div className="space-y-0.5">
                {dashboards.map((dashboard) => (
                  <div key={dashboard.id} className="group relative flex items-center">
                    {editingId === dashboard.id ? (
                      <div className="flex items-center w-full px-2">
                        <Input
                          value={editName}
                          onChange={(e) => setEditName(e.target.value)}
                          onBlur={handleSaveEdit}
                          onKeyDown={(e) => e.key === 'Enter' && handleSaveEdit()}
                          autoFocus
                          className="h-7 text-xs bg-white/5 border-white/10 text-white rounded-md"
                        />
                      </div>
                    ) : (
                      <button
                        className={cn(
                          'w-full flex items-center gap-3 px-3 py-2 rounded-xl text-sm font-medium transition-all',
                          activeDashboardId === dashboard.id
                            ? 'glass-tab text-white shadow-sm'
                            : 'text-white/35 hover:text-white/65 hover:bg-white/[0.03]'
                        )}
                        onClick={() => onDashboardSelect?.(dashboard.id)}
                      >
                        <LayoutDashboard className="w-4 h-4 shrink-0" />
                        <span className="truncate flex-1 text-left">{dashboard.name}</span>
                      </button>
                    )}

                    {!editingId && (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <button className="absolute right-1 h-7 w-7 rounded-lg text-white/30 hover:bg-white/8 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                            <MoreVertical className="h-3.5 w-3.5" />
                          </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem onClick={() => handleStartEdit(dashboard)}>
                            <Edit2 className="h-3.5 w-3.5 mr-2" />
                            Rename
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            className="text-destructive focus:text-destructive"
                            onClick={() => onDashboardDelete?.(dashboard.id)}
                            disabled={dashboards.length <= 1}
                          >
                            <Trash2 className="h-3.5 w-3.5 mr-2" />
                            Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    )}
                  </div>
                ))}
                {onDashboardAdd && (
                  <button
                    className="w-full flex items-center gap-3 px-3 py-2 rounded-xl text-sm font-medium text-white/30 hover:text-white/65 hover:bg-white/[0.03] transition-all"
                    onClick={onDashboardAdd}
                  >
                    <Plus className="w-4 h-4 shrink-0" />
                    <span>Add Dashboard</span>
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </ScrollArea>

      {/* Bottom Actions */}
      <div className="p-3 border-t border-white/[0.06] space-y-3">
        {/* Rest Mode Toggle */}
        {!collapsed && (
        <div className="glass-tab rounded-xl p-2.5 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className={cn(
              'w-7 h-7 rounded-lg flex items-center justify-center',
              restMode ? 'bg-helsinki/40 text-enso-blue' : 'bg-white/[0.05] text-white/30'
            )}>
              <MoonStar className="w-3.5 h-3.5" />
            </div>
            <div>
              <div className="text-xs font-medium text-white">Rest Mode</div>
              <div className="text-[10px] text-white/30">{restMode ? 'Prioritizing Sleep' : 'Standard Focus'}</div>
            </div>
          </div>
          <button
            onClick={() => setRestMode(!restMode)}
            className={cn(
              'w-9 h-5 flex items-center rounded-full p-0.5 transition-colors cursor-pointer',
              restMode ? 'bg-helsinki' : 'bg-white/[0.12]'
            )}
          >
            <div className={cn(
              'bg-white w-4 h-4 rounded-full shadow-md transform transition-transform duration-200',
              restMode ? 'translate-x-4' : 'translate-x-0'
            )} />
          </button>
        </div>
        )}

        {/* Settings Footer */}
        <div className={cn('flex items-center justify-between px-1', collapsed && 'justify-center')}>
          {!collapsed && (
          <div className="flex items-center gap-2.5 truncate">
            <div className="w-7 h-7 rounded-full bg-gradient-to-br from-helsinki to-enso-blue flex items-center justify-center font-semibold text-xs text-white shrink-0">
              U
            </div>
            <div className="truncate">
              <div className="text-xs font-medium text-white/70 truncate">User</div>
            </div>
          </div>
          )}
          {onSettingsClick && (
            <button
              onClick={onSettingsClick}
              className="p-1.5 hover:bg-white/[0.06] rounded-lg text-white/30 hover:text-white/70 transition-colors cursor-pointer"
              title="Settings"
            >
              <Sliders className="w-4 h-4" />
            </button>
          )}
        </div>

        {onToggleCollapse && (
          <button
            onClick={onToggleCollapse}
            className="h-8 w-full rounded-lg text-white/30 hover:bg-white/[0.04] hover:text-white/60 flex items-center justify-center cursor-pointer"
          >
            {collapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronLeft className="h-3.5 w-3.5" />}
          </button>
        )}
      </div>
    </div>
  );
}
