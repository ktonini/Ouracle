import { DashboardProvider, useDashboard } from "@/contexts/DashboardContext";
import { AppShell } from "@/components/layout/AppShell";
import { useChat } from "@/hooks/useChat";
import type { AppView } from "@/types/app-view";

function DashboardApp() {
  const {
    dashboards,
    activeDashboardId,
    setActiveDashboardId,
    addDashboard,
    deleteDashboard,
    renameDashboard,
    widgets,
    layout,
    updateActiveDashboard,
    isEditing,
    setIsEditing,
    activePanel,
    setActivePanel,
    activeView,
    setActiveView,
    startEditingWidget,
    editingWidget,
    updateEditingWidget,
    saveEditingWidget,
    cancelEditingWidget,
    deleteWidget,
    selectedDate,
    setSelectedDate,
    data,
    connectionStatus,
    syncInfo,
    retryConnection,
  } = useDashboard();

  const {
    threads,
    activeThreadId,
    messages,
    isLoading,
    createThread,
    deleteThread,
    switchThread,
    sendMessage,
    stopGeneration,
    clearActiveThread,
  } = useChat();

  const syncStatus = syncInfo
    ? { status: syncInfo.status, lastRun: syncInfo.lastRun, freshness: syncInfo.freshness }
    : null;

  return (
    <AppShell
      activeView={activeView}
      onViewChange={(view: AppView) => setActiveView(view)}
      selectedDate={selectedDate}
      onDateChange={(date: Date) => setSelectedDate(date)}
      connectionStatus={connectionStatus}
      syncStatus={syncStatus}
      onRetryConnection={retryConnection}

      dashboards={dashboards}
      activeDashboardId={activeDashboardId}
      onDashboardSelect={(id: string) => {
        setActiveDashboardId(id);
        setActiveView('dashboards');
      }}
      onDashboardAdd={addDashboard}
      onDashboardDelete={deleteDashboard}
      onDashboardRename={renameDashboard}

      widgets={widgets}
      layout={layout}
      isEditing={isEditing}
      setIsEditing={setIsEditing}
      startEditingWidget={startEditingWidget}
      deleteWidget={deleteWidget}
      updateEditingWidget={updateEditingWidget}
      editingWidget={editingWidget}
      saveEditingWidget={saveEditingWidget}
      cancelEditingWidget={cancelEditingWidget}
      updateActiveDashboard={updateActiveDashboard}

      activePanel={activePanel}
      setActivePanel={(p) => setActivePanel(p as 'none' | 'settings' | 'editor' | 'chat')}

      threads={threads}
      activeThreadId={activeThreadId}
      messages={messages}
      isLoading={isLoading}
      sendMessage={sendMessage}
      onStopGeneration={stopGeneration}
      clearActiveThread={clearActiveThread}
      createThread={createThread}
      deleteThread={deleteThread}
      switchThread={switchThread}
      onNavigateToAi={() => setActiveView('ai')}

      data={data}
    />
  );
}

function App() {
  return (
    <DashboardProvider>
      <DashboardApp />
    </DashboardProvider>
  );
}

export default App;
