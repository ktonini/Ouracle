import { useState } from 'react';
import { HealthSidebar } from './HealthSidebar';
import { TopDateBar } from './TopDateBar';
import { ContextRail } from './ContextRail';
import { SettingsPanel } from '@/components/dashboard/SettingsPanel';
import { WidgetEditorPanel } from '@/components/dashboard/WidgetEditorPanel';
import { ChatPanel } from '@/components/dashboard/ChatPanel';
import { TodayView } from '@/components/views/TodayView';
import { SleepView } from '@/components/views/SleepView';
import { ReadinessView } from '@/components/views/ReadinessView';
import { ActivityView } from '@/components/views/ActivityView';
import { ResilienceView } from '@/components/views/ResilienceView';
import { TrendsView } from '@/components/views/TrendsView';
import { ExplorerView } from '@/components/views/ExplorerView';
import { JournalView } from '@/components/views/JournalView';
import { AIAnalystView } from '@/components/views/AIAnalystView';
import { DashboardGrid } from '@/components/dashboard/DashboardGrid';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import { buildDaySummary } from '@/lib/day-summary';
import { format } from 'date-fns';
import { Check, Edit2, PanelRightOpen, Plus, RefreshCw, Sparkles } from 'lucide-react';
import type { Message, ChatThread } from '@/hooks/useChat';
import type { AppView } from '@/types/app-view';
import type { Dashboard, WidgetInstance } from '@/types';

interface AppShellProps {
  activeView: AppView;
  onViewChange: (view: AppView) => void;
  selectedDate: Date;
  onDateChange: (date: Date) => void;
  connectionStatus: 'connected' | 'disconnected' | 'checking';
  syncStatus: { status: string; lastRun: string | null; freshness?: import('@/lib/api').SyncFreshness | null } | null;
  onRetryConnection: () => void;
  data: any;

  dashboards: Dashboard[];
  activeDashboardId: string;
  onDashboardSelect: (id: string) => void;
  onDashboardAdd: () => void;
  onDashboardDelete: (id: string) => void;
  onDashboardRename: (id: string, name: string) => void;
  widgets: WidgetInstance[];
  layout: any[];
  isEditing: boolean;
  setIsEditing: (isEditing: boolean) => void;
  startEditingWidget: (widget?: WidgetInstance) => void;
  deleteWidget: (id: string) => void;
  updateEditingWidget: (w: WidgetInstance) => void;
  editingWidget: WidgetInstance | undefined;
  saveEditingWidget: () => void;
  cancelEditingWidget: () => void;
  activePanel: string;
  setActivePanel: (p: 'none' | 'settings' | 'editor' | 'chat') => void;
  updateActiveDashboard: (updates: Partial<Dashboard>) => void;

  threads: ChatThread[];
  activeThreadId: string | null;
  messages: Message[];
  isLoading: boolean;
  sendMessage: (msg: string) => void;
  onStopGeneration: () => void;
  clearActiveThread: () => void;
  createThread: () => Promise<string>;
  deleteThread: (id: string) => Promise<void>;
  switchThread: (id: string) => void;
  onNavigateToAi: () => void;
}

export function AppShell({
  activeView,
  onViewChange,
  selectedDate,
  onDateChange,
  connectionStatus,
  syncStatus,
  onRetryConnection,
  data,
  dashboards,
  activeDashboardId,
  onDashboardSelect,
  onDashboardAdd,
  onDashboardDelete,
  onDashboardRename,
  widgets,
  layout,
  isEditing,
  setIsEditing,
  startEditingWidget,
  deleteWidget,
  updateEditingWidget,
  editingWidget,
  saveEditingWidget,
  cancelEditingWidget,
  activePanel,
  setActivePanel,
  updateActiveDashboard,
  threads,
  activeThreadId,
  messages,
  isLoading,
  sendMessage,
  onStopGeneration,
  clearActiveThread,
  createThread,
  deleteThread,
  switchThread,
}: AppShellProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [isSyncingNow, setIsSyncingNow] = useState(false);

  const summary = data ? buildDaySummary(data, format(selectedDate, 'yyyy-MM-dd')) : null;
  const hour = new Date().getHours();
  const timeOfDay = hour < 12 ? 'morning' : hour < 17 ? 'afternoon' : 'evening';

  const handleAiPrompt = (prompt: string) => {
    onViewChange('ai');
    sendMessage(prompt);
  };

  const handleLayoutChange = (newLayout: any[]) => {
    updateActiveDashboard({ layout: newLayout });
  };

  const handleSync = async () => {
    if (isSyncingNow) return;
    setIsSyncingNow(true);
    try {
      await api.requestExport();
    } catch {
      setActivePanel('settings');
    } finally {
      onRetryConnection();
      setIsSyncingNow(false);
    }
  };

  const activeDashboardName = dashboards.find(d => d.id === activeDashboardId)?.name ?? 'Dashboard';

  const renderDashboardView = () => (
    <div className="p-6 md:p-8 space-y-4 max-w-7xl mx-auto animate-fadeIn">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-serif text-3xl text-white tracking-wide">{activeDashboardName}</h1>
          <p className="text-sm text-white/40 mt-1">Custom dashboard workspace</p>
        </div>
        <div className="flex items-center gap-2">
          {isEditing && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => startEditingWidget()}
              className="gap-2 border-white/[0.08] bg-white/[0.04] text-white/70 hover:bg-white/[0.08] hover:text-white"
            >
              <Plus className="h-3.5 w-3.5" />
              Add Widget
            </Button>
          )}
          <Button
            variant={isEditing ? 'default' : 'outline'}
            size="sm"
            onClick={() => {
              if (isEditing && activePanel === 'editor') {
                setActivePanel('none');
              }
              setIsEditing(!isEditing);
            }}
            className="gap-2 border-white/[0.08] bg-white/[0.04] text-white/70 hover:bg-white/[0.08] hover:text-white"
          >
            {isEditing ? <Check className="h-3.5 w-3.5" /> : <Edit2 className="h-3.5 w-3.5" />}
            {isEditing ? 'Done Editing' : 'Edit Layout'}
          </Button>
        </div>
      </div>

      <DashboardGrid
        widgets={widgets}
        layout={layout}
        isEditing={isEditing}
        onLayoutChange={handleLayoutChange}
        onEditWidget={startEditingWidget}
        onDeleteWidget={deleteWidget}
        onWidgetChange={updateEditingWidget}
        data={data}
        selectedDate={selectedDate}
      />
    </div>
  );

  const renderView = () => {
    switch (activeView) {
      case 'today':
        return <TodayView onNavigate={onViewChange} timeOfDay={timeOfDay} />;
      case 'sleep':
        return <SleepView />;
      case 'readiness':
        return <ReadinessView />;
      case 'activity':
        return <ActivityView />;
      case 'resilience':
        return <ResilienceView />;
      case 'trends':
        return <TrendsView />;
      case 'explorer':
        return <ExplorerView />;
      case 'journal':
        return <JournalView />;
      case 'dashboards':
      case 'dashboard-manager':
        return renderDashboardView();
      case 'ai':
        return (
          <AIAnalystView
            threads={threads}
            activeThreadId={activeThreadId}
            messages={messages}
            isLoading={isLoading}
            onSend={sendMessage}
            onClear={clearActiveThread}
            onCreateThread={createThread}
            onDeleteThread={deleteThread}
            onSwitchThread={switchThread}
            onStopGeneration={onStopGeneration}
          />
        );
      default:
        return <TodayView onNavigate={onViewChange} timeOfDay={timeOfDay} />;
    }
  };

  const showContextRail = ['today', 'sleep', 'readiness', 'activity', 'resilience'].includes(activeView);

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-foreground relative">
      {/* Atmospheric Background */}
      <div
        className="absolute inset-0 bg-cover bg-center bg-no-repeat bg-fade pointer-events-none"
        style={{
          backgroundImage: `url('./images/oura-bg-${timeOfDay === 'morning' || timeOfDay === 'afternoon' ? 'day' : 'night'}.jpg')`,
        }}
      />
      <div className="absolute inset-0 app-atmosphere-overlay pointer-events-none" />

      {/* Sidebar */}
      <div className="relative z-10">
        <HealthSidebar
          activeView={activeView}
          onViewChange={onViewChange}
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
          onSettingsClick={() => setActivePanel(activePanel === 'settings' ? 'none' : 'settings')}
          syncStatus={syncStatus}
          onSync={handleSync}
          isSyncing={isSyncingNow || syncStatus?.status === 'Processing'}
          battery={summary?.battery ?? null}
          batteryTimestamp={summary?.batteryTimestamp ?? null}
          dashboards={dashboards}
          activeDashboardId={activeDashboardId}
          onDashboardSelect={onDashboardSelect}
          onDashboardAdd={onDashboardAdd}
          onDashboardDelete={onDashboardDelete}
          onDashboardRename={onDashboardRename}
        />
      </div>

      {/* Main Area */}
      <div className="relative z-10 flex-1 flex flex-col min-w-0">
        {/* Top Bar */}
        <TopDateBar
          selectedDate={selectedDate}
          onDateChange={onDateChange}
          syncStatus={syncStatus ?? undefined}
          connectionStatus={connectionStatus}
          rightActions={
            <>
              <Button
                variant={activePanel === 'chat' ? 'secondary' : 'outline'}
                size="sm"
                onClick={() => setActivePanel(activePanel === 'chat' ? 'none' : 'chat')}
                className="gap-2 border-white/[0.08] bg-white/[0.04] text-white/70 hover:bg-white/[0.08] hover:text-white"
              >
                {activePanel === 'chat' ? <PanelRightOpen className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}
                {activePanel === 'chat' ? 'Close Analyst' : 'Analyst Panel'}
              </Button>
            </>
          }
        />

        {/* Content */}
        <div className="flex-1 flex overflow-hidden">
          <main className="flex-1 overflow-auto relative">
            {connectionStatus === 'disconnected' && (
              <div className="sticky top-0 z-20 mx-6 mt-4 flex items-center justify-between gap-3 rounded-xl border border-living-coral/25 bg-living-coral/10 px-4 py-3 backdrop-blur-xl">
                <div className="flex items-center gap-3">
                  <span className="h-2.5 w-2.5 rounded-full bg-living-coral pulse-dot" />
                  <p className="text-sm text-living-coral/90">
                    Backend is unreachable. Data, sync, settings, and AI analysis may not work.
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={onRetryConnection}
                  className="gap-2 shrink-0 border-living-coral/30 bg-living-coral/10 text-living-coral hover:bg-living-coral/20"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  Retry
                </Button>
              </div>
            )}
            {renderView()}
          </main>

          {/* Context Rail */}
          {showContextRail && summary && (
            <ContextRail
              summary={summary}
              battery={summary.battery}
              batteryTimestamp={summary.batteryTimestamp}
              timeline={summary.timeline}
              onAiPrompt={handleAiPrompt}
            />
          )}
        </div>
      </div>

      {/* Side Panels */}
      {activePanel === 'settings' && (
        <div className="relative z-20">
          <SettingsPanel onClose={() => setActivePanel('none')} />
        </div>
      )}
      {activePanel === 'chat' && (
        <div className="relative z-20">
          <ChatPanel
            onClose={() => setActivePanel('none')}
            threads={threads}
            activeThreadId={activeThreadId}
            messages={messages}
            isLoading={isLoading}
            onSend={sendMessage}
            onCreateThread={createThread}
            onDeleteThread={deleteThread}
            onSwitchThread={switchThread}
            onStopGeneration={onStopGeneration}
          />
        </div>
      )}
      {activePanel === 'editor' && (
        <div className="relative z-20">
          <WidgetEditorPanel
            onClose={cancelEditingWidget}
            onSave={saveEditingWidget}
            onChange={updateEditingWidget}
            widget={editingWidget}
          />
        </div>
      )}
    </div>
  );
}
