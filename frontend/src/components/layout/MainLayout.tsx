import { AppSidebar } from "./AppSidebar";
import { Button } from "@/components/ui/button";
import {
    Sparkles,
    Calendar as CalendarIcon,
    ChevronLeft,
    ChevronRight,
    BedDouble,
    Activity,
    BrainCircuit,
    Footprints,
    PanelRightOpen,
    Settings2,
} from "lucide-react";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { format, isToday } from "date-fns";
import { cn } from "@/lib/utils";
import type { SyncFreshness } from "@/lib/api";
import { syncIndicatorTone, syncStatusHeadline } from "@/lib/sync-display";
import type { Dashboard } from "@/types";
import { ModeToggle } from "@/components/mode-toggle";

interface MainLayoutProps {
    children: React.ReactNode;
    data?: any;
    isDataLoading?: boolean;
    rightPanel?: React.ReactNode;
    onChatToggle?: () => void;
    isChatOpen?: boolean;
    selectedDate?: Date;
    onDateChange?: (date: Date | undefined) => void;
    onSettingsClick?: () => void;
    headerActions?: React.ReactNode;

    // Connection Health
    connectionStatus?: 'connected' | 'disconnected' | 'checking';
    syncInfo?: {
        status: string;
        lastRun: string | null;
        nextRun: string | null;
        freshness: SyncFreshness | null;
    };
    onRetryConnection?: () => void;

    // Dashboard Props
    dashboards: Dashboard[];
    activeDashboardId: string;
    onDashboardSelect: (id: string) => void;
    onDashboardAdd: () => void;
    onDashboardDelete: (id: string) => void;
    onDashboardRename: (id: string, newName: string) => void;

    // Navigation
    activeView?: 'dashboard' | 'chat-page';
    onChatPageSelect?: () => void;
}

export function MainLayout({
    children,
    data,
    isDataLoading,
    rightPanel,
    onChatToggle,
    isChatOpen,
    selectedDate = new Date(),
    onDateChange,
    onSettingsClick,
    headerActions,
    connectionStatus,
    syncInfo,
    onRetryConnection,
    dashboards,
    activeDashboardId,
    onDashboardSelect,
    onDashboardAdd,
    onDashboardDelete,
    onDashboardRename,
    activeView,
    onChatPageSelect
}: MainLayoutProps) {
    const activeDashboardName = dashboards.find(d => d.id === activeDashboardId)?.name || "Dashboard";
    const summaryCards = [
        {
            label: "Sleep",
            value: data?.sleep?.score ?? "--",
            unit: data?.sleep?.score != null ? "/100" : "",
            tone: "from-[#1f6feb] to-[#73a7ff]",
            icon: BedDouble,
            skeletonWidth: "w-16",
        },
        {
            label: "Readiness",
            value: data?.readiness?.score ?? "--",
            unit: data?.readiness?.score != null ? "/100" : "",
            tone: "from-[#178f5f] to-[#6de2a6]",
            icon: BrainCircuit,
            skeletonWidth: "w-16",
        },
        {
            label: "Activity",
            value: data?.activity?.score ?? "--",
            unit: data?.activity?.score != null ? "/100" : "",
            tone: "from-[#d9485f] to-[#ff9f7a]",
            icon: Activity,
            skeletonWidth: "w-16",
        },
        {
            label: "Steps",
            value: data?.activity?.steps?.toLocaleString?.() ?? data?.activity?.steps ?? "--",
            unit: "",
            tone: "from-[#7b5cff] to-[#c49eff]",
            icon: Footprints,
            skeletonWidth: "w-24",
        },
    ];

    return (
        <div className="flex h-screen w-full overflow-hidden bg-[radial-gradient(circle_at_top_left,_rgba(255,255,255,0.08),_transparent_22%),linear-gradient(180deg,_hsl(var(--background))_0%,_hsl(var(--background-soft))_100%)] text-foreground">
            {/* Left Sidebar */}
            <AppSidebar
                onSettingsClick={onSettingsClick}
                dashboards={dashboards}
                activeDashboardId={activeDashboardId}
                onDashboardSelect={onDashboardSelect}
                onDashboardAdd={onDashboardAdd}
                onDashboardDelete={onDashboardDelete}
                onDashboardRename={onDashboardRename}
                activeView={activeView}
                onChatPageSelect={onChatPageSelect}
            />

            {/* Main Content Area */}
            <div className="flex-1 flex flex-col min-w-0">
                {/* Header */}
                <header className="sticky top-0 z-[100] border-b border-white/[0.04] bg-[#050505]/80 backdrop-blur-2xl px-8 py-6">
                    <div className="flex items-start justify-between gap-6">
                        <div className="min-w-0 space-y-4">
                            <div className="flex flex-col gap-1">
                                <div className="flex items-center gap-3">
                                    <h1 className="font-['Space_Grotesk',sans-serif] text-3xl font-medium tracking-tight text-white/95">
                                        {activeDashboardName}
                                    </h1>
                                    <div className="flex items-center gap-2 mt-1">
                                        <span className="rounded-full bg-white/[0.03] border border-white/[0.05] px-2.5 py-0.5 text-[10px] font-medium tracking-wider text-white/40 uppercase">
                                            {activeView === 'chat-page' ? "Advisor" : "Dashboard"}
                                        </span>
                                        {syncInfo && (
                                            <span
                                                className="inline-flex items-center gap-1.5 px-2 py-0.5 text-[11px] text-white/40"
                                                title={syncStatusHeadline(
                                                    { status: syncInfo.status, message: undefined, last_run: syncInfo.lastRun },
                                                    syncInfo.freshness,
                                                )}
                                            >
                                                <span className={cn(
                                                    "h-1.5 w-1.5 rounded-full",
                                                    syncIndicatorTone(syncInfo.status, syncInfo.freshness) === 'busy'
                                                        ? "bg-amber-400/80 animate-pulse"
                                                        : syncIndicatorTone(syncInfo.status, syncInfo.freshness) === 'error'
                                                            ? "bg-rose-500/80"
                                                            : syncIndicatorTone(syncInfo.status, syncInfo.freshness) === 'fresh'
                                                                ? "bg-emerald-400/80 shadow-[0_0_8px_rgba(52,211,153,0.4)]"
                                                                : syncIndicatorTone(syncInfo.status, syncInfo.freshness) === 'stale'
                                                                    ? "bg-amber-400/80"
                                                                    : "bg-white/20",
                                                )} />
                                                {syncStatusHeadline(
                                                    { status: syncInfo.status, message: undefined, last_run: syncInfo.lastRun },
                                                    syncInfo.freshness,
                                                )}
                                            </span>
                                        )}
                                    </div>
                                </div>
                            </div>

                            <div className="flex flex-wrap gap-3">
                                {summaryCards.map((card) => {
                                    const Icon = card.icon;
                                    return (
                                        <div
                                            key={card.label}
                                            className="min-w-[155px] rounded-2xl border border-white/8 bg-white/5 px-4 py-3 shadow-[0_12px_40px_rgba(0,0,0,0.18)]"
                                        >
                                            <div className="flex items-center justify-between gap-3">
                                                <div>
                                                    <p className="text-[11px] uppercase tracking-[0.24em] text-[hsl(var(--muted-foreground))]">
                                                        {card.label}
                                                    </p>
                                                    <div className="mt-2 flex items-end gap-1">
                                                        {isDataLoading ? (
                                                            <div className={cn("h-7 rounded-md bg-white/15 animate-pulse", card.skeletonWidth)} />
                                                        ) : (
                                                            <>
                                                                <span className="font-['Space_Grotesk',sans-serif] text-2xl font-semibold text-white">
                                                                    {card.value}
                                                                </span>
                                                                {card.unit && (
                                                                    <span className="pb-1 text-xs text-[hsl(var(--muted-foreground))]">
                                                                        {card.unit}
                                                                    </span>
                                                                )}
                                                            </>
                                                        )}
                                                    </div>
                                                </div>
                                                <div className={cn("rounded-2xl bg-gradient-to-br p-3 text-white shadow-lg", card.tone)}>
                                                    <Icon className="h-4 w-4" />
                                                </div>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>

                        <div className="flex shrink-0 flex-col items-end gap-4">
                            <div className="flex items-center gap-2">
                                {headerActions}
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={onSettingsClick}
                                    className="gap-2 border-white/10 bg-white/5 text-white hover:bg-white/10"
                                >
                                    <Settings2 className="h-4 w-4" />
                                    Settings
                                </Button>
                                <ModeToggle />
                                <Button
                                    variant={isChatOpen ? "secondary" : "outline"}
                                    size="sm"
                                    onClick={onChatToggle}
                                    className={cn(
                                        "gap-2 border-white/10 text-white",
                                        isChatOpen ? "bg-white text-black hover:bg-white/90" : "bg-white/5 hover:bg-white/10",
                                    )}
                                >
                                    {isChatOpen ? <PanelRightOpen className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />}
                                    {isChatOpen ? "Close Advisor" : "Open Advisor"}
                                </Button>
                            </div>

                            <div className="rounded-2xl border border-white/8 bg-black/20 p-2 shadow-[0_12px_36px_rgba(0,0,0,0.22)]">
                                <div className="flex items-center gap-1">
                            <Button
                                variant="outline"
                                size="icon"
                                className="h-10 w-10 border-white/10 bg-white/5 text-white hover:bg-white/10"
                                onClick={() => {
                                    if (onDateChange && selectedDate) {
                                        const prevDay = new Date(selectedDate);
                                        prevDay.setDate(prevDay.getDate() - 1);
                                        onDateChange(prevDay);
                                    }
                                }}
                            >
                                <ChevronLeft className="h-4 w-4" />
                            </Button>

                            <Button
                                variant="outline"
                                size="sm"
                                className={cn(
                                    "h-10 border-white/10 bg-white/5 text-white hover:bg-white/10",
                                    selectedDate && isToday(selectedDate) && "opacity-40 hover:bg-white/5"
                                )}
                                disabled={!!(selectedDate && isToday(selectedDate))}
                                onClick={() => onDateChange?.(new Date())}
                            >
                                Today
                            </Button>

                            <Popover>
                                <PopoverTrigger asChild>
                                    <Button
                                        variant={"outline"}
                                        className={cn(
                                            "h-10 w-[260px] justify-start border-white/10 bg-white/5 text-left font-normal text-white hover:bg-white/10",
                                            !selectedDate && "text-muted-foreground"
                                        )}
                                    >
                                        <CalendarIcon className="mr-2 h-4 w-4" />
                                        {selectedDate ? format(selectedDate, "PPP") : <span>Pick a date</span>}
                                    </Button>
                                </PopoverTrigger>
                                <PopoverContent className="w-auto p-0" align="start">
                                    <Calendar
                                        mode="single"
                                        selected={selectedDate}
                                        onSelect={onDateChange}
                                        initialFocus
                                    />
                                </PopoverContent>
                            </Popover>

                            <Button
                                variant="outline"
                                size="icon"
                                className="h-10 w-10 border-white/10 bg-white/5 text-white hover:bg-white/10"
                                onClick={() => {
                                    if (onDateChange && selectedDate) {
                                        const nextDay = new Date(selectedDate);
                                        nextDay.setDate(nextDay.getDate() + 1);
                                        onDateChange(nextDay);
                                    }
                                }}
                            >
                                <ChevronRight className="h-4 w-4" />
                            </Button>
                                </div>
                                <p className="px-2 pt-2 text-right text-[11px] uppercase tracking-[0.24em] text-[hsl(var(--muted-foreground))]">
                                    Focus date
                                </p>
                            </div>
                        </div>
                    </div>
                </header>

                {/* Dashboard Content */}
                <div className="flex-1 flex overflow-hidden">
                    <main className="flex-1 overflow-auto px-6 pb-6 pt-5 relative">
                        {connectionStatus === 'disconnected' && (
                            <div className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3">
                                <div className="flex items-center gap-3">
                                    <div className="h-2.5 w-2.5 rounded-full bg-red-500 animate-pulse" />
                                    <p className="text-sm text-red-300">
                                        Backend is unreachable. The dashboard cannot load data.
                                    </p>
                                </div>
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={onRetryConnection}
                                    className="shrink-0 border-red-500/20 text-red-300 hover:bg-red-500/20 hover:text-red-200"
                                >
                                    Retry
                                </Button>
                            </div>
                        )}
                        {children}
                    </main>

                    {/* Persistent Right Panel */}
                    {rightPanel}
                </div>
            </div>
        </div>
    );
}
