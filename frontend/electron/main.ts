import { app, BrowserWindow, Tray, Menu, nativeImage, nativeTheme } from 'electron';
import type { NativeImage } from 'electron';
import path from 'path';
import { spawn, ChildProcess } from 'child_process';
import { appendFileSync, existsSync, readFileSync, writeFileSync } from 'fs';
import http from 'http';

let mainWindow: BrowserWindow | null;
let pythonProcess: ChildProcess | null = null;
let tray: Tray | null = null;
let isQuitting = false;
let startHidden = false;

const isDev = process.env.NODE_ENV === 'development';
const LAUNCH_AT_LOGIN_ARG = '--hidden';

type DesktopPrefs = {
    launchOnStartup: boolean;
};

function desktopPrefsPath(): string {
    return path.join(app.getPath('userData'), 'desktop-prefs.json');
}

function readDesktopPrefs(): DesktopPrefs {
    try {
        const raw = readFileSync(desktopPrefsPath(), 'utf8');
        const parsed = JSON.parse(raw) as Partial<DesktopPrefs>;
        return {
            // Default on so scheduled sync / auto OTP keep working after reboot.
            launchOnStartup: parsed.launchOnStartup !== false,
        };
    } catch {
        return { launchOnStartup: true };
    }
}

function writeDesktopPrefs(prefs: DesktopPrefs) {
    try {
        writeFileSync(desktopPrefsPath(), JSON.stringify(prefs, null, 2), 'utf8');
    } catch (error: any) {
        logToDesktop(`Failed to write desktop prefs: ${error?.message || error}`);
    }
}

function applyLaunchOnStartup(enabled: boolean) {
    if (!app.isPackaged) {
        return;
    }
    app.setLoginItemSettings({
        openAtLogin: enabled,
        openAsHidden: true,
        path: process.execPath,
        args: enabled ? [LAUNCH_AT_LOGIN_ARG] : [],
    });
    writeDesktopPrefs({ launchOnStartup: enabled });
    logToDesktop(`Launch on startup ${enabled ? 'enabled' : 'disabled'}`);
}

function ensureLaunchOnStartupConfigured() {
    if (!app.isPackaged) {
        logToDesktop('Dev mode: skip login-item registration');
        return;
    }
    const prefs = readDesktopPrefs();
    applyLaunchOnStartup(prefs.launchOnStartup);
}

function launchedFromLogin(): boolean {
    if (process.argv.includes(LAUNCH_AT_LOGIN_ARG)) {
        return true;
    }
    try {
        const login = app.getLoginItemSettings();
        return Boolean(login.wasOpenedAtLogin || login.wasOpenedAsHidden);
    } catch {
        return false;
    }
}

function rebuildTrayMenu() {
    if (!tray) {
        return;
    }
    const launchOnStartup = app.isPackaged
        ? readDesktopPrefs().launchOnStartup
        : false;

    const contextMenu = Menu.buildFromTemplate([
        {
            label: 'Open Dashboard',
            click: () => {
                if (mainWindow) {
                    mainWindow.show();
                    mainWindow.focus();
                } else {
                    createWindow();
                }
            }
        },
        {
            label: 'Launch at startup',
            type: 'checkbox',
            checked: launchOnStartup,
            enabled: app.isPackaged,
            click: (item) => {
                applyLaunchOnStartup(item.checked);
                rebuildTrayMenu();
            }
        },
        { type: 'separator' },
        {
            label: 'Quit',
            click: () => {
                isQuitting = true;
                app.quit();
            }
        }
    ]);

    tray.setContextMenu(contextMenu);
}

function trayAssetCandidates(fileName: string): string[] {
    return [
        path.join(__dirname, 'assets', fileName),
        path.join(__dirname, '..', 'electron', 'assets', fileName),
        path.join(process.resourcesPath, 'assets', fileName),
    ];
}

function loadTrayImage(fileName: string): NativeImage | null {
    for (const candidate of trayAssetCandidates(fileName)) {
        if (!existsSync(candidate)) {
            continue;
        }
        const image = nativeImage.createFromPath(candidate);
        if (!image.isEmpty()) {
            logToDesktop(`Loaded tray icon from ${candidate}`);
            return image;
        }
    }
    return null;
}

function buildFallbackTrayIcon(forDarkTaskbar: boolean): NativeImage {
    // Tiny procedural bitmap so a missing asset never yields an invisible tray.
    const size = 32;
    const buf = Buffer.alloc(size * size * 4);
    const cx = (size - 1) / 2;
    const cy = (size - 1) / 2 + 1;
    const outer = size * 0.38;
    const inner = size * 0.22;
    const [fr, fg, fb] = forDarkTaskbar ? [236, 244, 248] : [30, 41, 54];
    const [sr, sg, sb] = forDarkTaskbar ? [20, 28, 36] : [255, 255, 255];

    for (let y = 0; y < size; y++) {
        for (let x = 0; x < size; x++) {
            const dx = x - cx;
            const dy = y - cy;
            const dist = Math.sqrt(dx * dx + dy * dy);
            const i = (y * size + x) * 4;
            const onRing = dist <= outer && dist >= inner;
            const onBar = y >= 3 && y <= 7 && x >= 10 && x <= 21;
            if (onRing || onBar) {
                const edge = onRing && (dist > outer - 1.2 || dist < inner + 1.2);
                buf[i] = edge ? sr : fr;
                buf[i + 1] = edge ? sg : fg;
                buf[i + 2] = edge ? sb : fb;
                buf[i + 3] = 255;
            }
        }
    }

    return nativeImage.createFromBitmap(buf, { width: size, height: size });
}

function resolveTrayIcon(): NativeImage {
    // Prefer the brand-blue mark: readable on both dark and light Windows taskbars.
    // Theme-specific glyphs remain as fallbacks.
    const forDarkTaskbar = nativeTheme.shouldUseDarkColors || nativeTheme.shouldUseInvertedColorScheme;
    const preferred = [
        'tray-accent-32.png',
        'tray-accent.png',
        ...(forDarkTaskbar
            ? ['tray-for-dark-taskbar-32.png', 'tray-for-dark-taskbar.png']
            : ['tray-for-light-taskbar-32.png', 'tray-for-light-taskbar.png']),
    ];

    for (const name of preferred) {
        const image = loadTrayImage(name);
        if (image) {
            const size = process.platform === 'win32' ? 16 : 22;
            return image.resize({ width: size, height: size, quality: 'best' });
        }
    }

    logToDesktop('Tray assets missing; using procedural fallback icon');
    return buildFallbackTrayIcon(forDarkTaskbar);
}

function syncTrayIcon() {
    if (!tray) {
        return;
    }
    tray.setImage(resolveTrayIcon());
}

function createTray() {
    const icon = resolveTrayIcon();
    tray = new Tray(icon);
    tray.setToolTip('Cracked Oura');
    rebuildTrayMenu();

    nativeTheme.on('updated', () => {
        syncTrayIcon();
    });

    tray.on('double-click', () => {
        if (mainWindow) {
            mainWindow.show();
            mainWindow.focus();
        }
    });
}

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1280,
        height: 800,
        webPreferences: {
            nodeIntegration: true,
            contextIsolation: false, // For simple IPC now, can harden later
        },
        backgroundColor: '#0f1115', // Match our dark theme
        show: false, // Don't show until ready
        title: 'Cracked Oura',
    });

    const devUrl = 'http://localhost:5188';
    // Production UI is served by the bundled backend on port 8000 (same origin for /api/*).
    const prodUrl = process.env.CRACKED_OURA_UI_URL || 'http://127.0.0.1:8000/';

    if (isDev) {
        logToDesktop(`Loading DEV URL: ${devUrl}`);
        mainWindow.loadURL(devUrl);
        // mainWindow.webContents.openDevTools();
    } else {
        logToDesktop(`Loading PROD URL: ${prodUrl}`);
        mainWindow.loadURL(prodUrl).catch(err => {
            logToDesktop(`FAILED to load URL: ${err.message}`);
        });
    }

    mainWindow.once('ready-to-show', () => {
        logToDesktop("Window ready to show");
        if (startHidden) {
            logToDesktop("Started at login; keeping window hidden in tray");
            return;
        }
        mainWindow?.show();
    });

    // Debug Renderer Crashes
    mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDescription) => {
        logToDesktop(`PAGE LOAD FAILED: ${errorCode} - ${errorDescription}`);
    });

    mainWindow.webContents.on('render-process-gone', (event, details) => {
        logToDesktop(`Renderer Process GONE. Reason: ${details.reason}`);
    });

    // HIDE instead of close
    mainWindow.on('close', (event) => {
        if (!isQuitting) {
            event.preventDefault();
            mainWindow?.hide();
            return false;
        }
    });

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

function waitForBackendReady(timeoutMs = 20000): Promise<void> {
    const start = Date.now();

    return new Promise((resolve, reject) => {
        const attempt = () => {
            const request = http.get('http://127.0.0.1:8000/', (response) => {
                response.resume();
                if (response.statusCode === 200) {
                    resolve();
                    return;
                }
                retry(new Error(`Backend UI readiness check returned ${response.statusCode}`));
            });

            request.on('error', (error) => retry(error));
            request.setTimeout(1500, () => request.destroy(new Error('Backend readiness check timed out')));
        };

        const retry = (error: Error) => {
            if (Date.now() - start >= timeoutMs) {
                reject(error);
                return;
            }
            setTimeout(attempt, 500);
        };

        attempt();
    });
}

function getPythonPath(): string {
    if (!isDev) {
        // Production: Backend is bundled inside the app
        // In macOS .app: Contents/Resources/backend/backend
        // In Windows/Linux: resources/backend/backend(.exe)
        const possiblePath = path.join(process.resourcesPath, 'backend', 'backend');
        // On Windows it might have .exe extension, but child_process.spawn handles it if we don't specify extension? 
        // Best to check specific platform or try specific paths.
        if (process.platform === 'win32') {
            return path.join(process.resourcesPath, 'backend', 'backend.exe');
        }
        return possiblePath;
    }

    // Development: Use local venv
    // Check standard locations
    const venvRoot = path.join(__dirname, '../../backend/venv');
    const binPath = path.join(venvRoot, 'bin', 'python'); // Mac/Linux
    const scriptsPath = path.join(venvRoot, 'Scripts', 'python.exe'); // Windows

    // We can't easily check file existence synchronously in specific setups without 'fs', 
    // but we can try to rely on platform.
    if (process.platform === 'win32') {
        return scriptsPath;
    }
    return binPath;
}

// Debug logging helper
function logToDesktop(message: string) {
    try {
        const logPath = path.join(app.getPath('documents'), 'cracked_oura_electron_debug.log');
        const timestamp = new Date().toISOString();
        appendFileSync(logPath, `[${timestamp}] ${message}\n`);
    } catch (e) {
        console.error("Failed to write to log file", e);
    }
}

function startPythonBackend() {
    const exePath = getPythonPath();
    console.log('Starting Backend from:', exePath);
    logToDesktop(`Attempting to start backend from: ${exePath}`);

    if (isDev) {
        logToDesktop("Running in DEV mode");
        // Run with uvicorn via python -m
        pythonProcess = spawn(exePath, [
            '-m', 'uvicorn',
            'backend.src.api.main:app',
            '--host', '127.0.0.1',
            '--port', '8000',
            '--reload'
        ], {
            cwd: path.join(__dirname, '../../'),
            stdio: 'inherit'
        });
    } else {
        logToDesktop("Running in PROD mode");
        // Production: Run the compiled executable directly

        if (!existsSync(exePath)) {
            logToDesktop(`CRITICAL ERROR: Backend executable NOT FOUND at ${exePath}`);
        } else {
            logToDesktop(`Backend executable confirmed at ${exePath}`);
        }

        try {
            // It starts uvicorn internally (if main.py calls uvicorn.run)
            pythonProcess = spawn(exePath, [], {
                cwd: path.dirname(exePath), // Run from its own directory to find dependencies/relative files
                stdio: ['ignore', 'pipe', 'pipe'], // Capture stdout/stderr
                env: { ...process.env, PORT: '8000' } // Pass port if needed
            });
            logToDesktop(`Backend process spawned with PID: ${pythonProcess ? pythonProcess.pid : 'NULL'}`);
        } catch (spawnError: any) {
            logToDesktop(`CRITICAL SPAWN ERROR: ${spawnError.message}`);
        }
    }

    if (pythonProcess) {
        // Capture Standard Output
        if (pythonProcess.stdout) {
            pythonProcess.stdout.on('data', (data) => {
                logToDesktop(`[STDOUT] ${data.toString().trim()}`);
            });
        }

        // Capture Standard Error (Critical for startup crashes)
        if (pythonProcess.stderr) {
            pythonProcess.stderr.on('data', (data) => {
                logToDesktop(`[STDERR] ${data.toString().trim()}`);
            });
        }

        pythonProcess.on('error', (err) => {
            console.error('Failed to start Python backend:', err);
            logToDesktop(`Backend Process ERROR: ${err.message}`);
        });

        pythonProcess.on('close', (code) => {
            console.log(`Python backend exited with code ${code}`);
            logToDesktop(`Backend Process EXITED with code: ${code}`);
        });
    } else {
        logToDesktop("pythonProcess is undefined after attempt!");
    }
}

app.on('ready', async () => {
    ensureLaunchOnStartupConfigured();
    startHidden = launchedFromLogin();
    logToDesktop(`App ready (packaged=${app.isPackaged}, startHidden=${startHidden})`);
    startPythonBackend();
    try {
        await waitForBackendReady();
        logToDesktop('Backend ready. Opening desktop window.');
    } catch (error: any) {
        logToDesktop(`Backend readiness check failed: ${error?.message || error}`);
    }
    createWindow();
    createTray();
});

app.on('window-all-closed', () => {
    // Do NOT quit. We want to stay alive in the tray.
    if (process.platform !== 'darwin') {
        // On Windows/Linux we might want to quit if tray is not used, 
        // but here we ARE using tray, so we stay alive.
        // app.quit(); 
    }
});

app.on('activate', () => {
    if (mainWindow === null) {
        createWindow();
    } else {
        mainWindow.show();
    }
});

app.on('before-quit', () => {
    isQuitting = true;
});

app.on('will-quit', () => {
    if (pythonProcess) {
        pythonProcess.kill();
    }
});
