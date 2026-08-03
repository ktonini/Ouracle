"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const electron_1 = require("electron");
const path_1 = __importDefault(require("path"));
const child_process_1 = require("child_process");
const fs_1 = require("fs");
const http_1 = __importDefault(require("http"));
let mainWindow;
let pythonProcess = null;
let tray = null;
let isQuitting = false;
let startHidden = false;
const isDev = process.env.NODE_ENV === 'development';
const LAUNCH_AT_LOGIN_ARG = '--hidden';
// Prevent duplicate tray instances from repeated startup entries or manual launches.
const gotSingleInstanceLock = electron_1.app.requestSingleInstanceLock();
if (gotSingleInstanceLock) {
    electron_1.app.on('second-instance', (_event, commandLine) => {
        // A duplicate hidden login launch should simply exit without disturbing the tray app.
        if (commandLine.includes(LAUNCH_AT_LOGIN_ARG)) {
            return;
        }
        if (mainWindow) {
            if (mainWindow.isMinimized()) {
                mainWindow.restore();
            }
            mainWindow.show();
            mainWindow.focus();
        }
    });
}
function desktopPrefsPath() {
    return path_1.default.join(electron_1.app.getPath('userData'), 'desktop-prefs.json');
}
function readDesktopPrefs() {
    try {
        const raw = (0, fs_1.readFileSync)(desktopPrefsPath(), 'utf8');
        const parsed = JSON.parse(raw);
        return {
            // Default on so scheduled sync / auto OTP keep working after reboot.
            launchOnStartup: parsed.launchOnStartup !== false,
        };
    }
    catch {
        return { launchOnStartup: true };
    }
}
function writeDesktopPrefs(prefs) {
    try {
        (0, fs_1.writeFileSync)(desktopPrefsPath(), JSON.stringify(prefs, null, 2), 'utf8');
    }
    catch (error) {
        logToDesktop(`Failed to write desktop prefs: ${error?.message || error}`);
    }
}
function applyLaunchOnStartup(enabled) {
    if (!electron_1.app.isPackaged) {
        return;
    }
    electron_1.app.setLoginItemSettings({
        openAtLogin: enabled,
        openAsHidden: true,
        path: process.execPath,
        args: enabled ? [LAUNCH_AT_LOGIN_ARG] : [],
    });
    writeDesktopPrefs({ launchOnStartup: enabled });
    logToDesktop(`Launch on startup ${enabled ? 'enabled' : 'disabled'}`);
}
function ensureLaunchOnStartupConfigured() {
    if (!electron_1.app.isPackaged) {
        logToDesktop('Dev mode: skip login-item registration');
        return;
    }
    const prefs = readDesktopPrefs();
    applyLaunchOnStartup(prefs.launchOnStartup);
}
function launchedFromLogin() {
    if (process.argv.includes(LAUNCH_AT_LOGIN_ARG)) {
        return true;
    }
    try {
        const login = electron_1.app.getLoginItemSettings();
        return Boolean(login.wasOpenedAtLogin || login.wasOpenedAsHidden);
    }
    catch {
        return false;
    }
}
function rebuildTrayMenu() {
    if (!tray) {
        return;
    }
    const launchOnStartup = electron_1.app.isPackaged
        ? readDesktopPrefs().launchOnStartup
        : false;
    const contextMenu = electron_1.Menu.buildFromTemplate([
        {
            label: 'Open Dashboard',
            click: () => {
                if (mainWindow) {
                    mainWindow.show();
                    mainWindow.focus();
                }
                else {
                    createWindow();
                }
            }
        },
        {
            label: 'Launch at startup',
            type: 'checkbox',
            checked: launchOnStartup,
            enabled: electron_1.app.isPackaged,
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
                electron_1.app.quit();
            }
        }
    ]);
    tray.setContextMenu(contextMenu);
}
function trayAssetCandidates(fileName) {
    return [
        path_1.default.join(__dirname, 'assets', fileName),
        path_1.default.join(__dirname, '..', 'electron', 'assets', fileName),
        path_1.default.join(process.resourcesPath, 'assets', fileName),
    ];
}
function loadTrayImage(fileName) {
    for (const candidate of trayAssetCandidates(fileName)) {
        if (!(0, fs_1.existsSync)(candidate)) {
            continue;
        }
        const image = electron_1.nativeImage.createFromPath(candidate);
        if (!image.isEmpty()) {
            logToDesktop(`Loaded tray icon from ${candidate}`);
            return image;
        }
    }
    return null;
}
function buildFallbackTrayIcon(forDarkTaskbar) {
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
    return electron_1.nativeImage.createFromBitmap(buf, { width: size, height: size });
}
function resolveTrayIcon() {
    // Prefer the brand-blue mark: readable on both dark and light Windows taskbars.
    // Theme-specific glyphs remain as fallbacks.
    const forDarkTaskbar = electron_1.nativeTheme.shouldUseDarkColors || electron_1.nativeTheme.shouldUseInvertedColorScheme;
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
    tray = new electron_1.Tray(icon);
    tray.setToolTip('Cracked Oura');
    rebuildTrayMenu();
    electron_1.nativeTheme.on('updated', () => {
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
    mainWindow = new electron_1.BrowserWindow({
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
    }
    else {
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
function waitForBackendReady(timeoutMs = 20000) {
    const start = Date.now();
    return new Promise((resolve, reject) => {
        const attempt = () => {
            const request = http_1.default.get('http://127.0.0.1:8000/', (response) => {
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
        const retry = (error) => {
            if (Date.now() - start >= timeoutMs) {
                reject(error);
                return;
            }
            setTimeout(attempt, 500);
        };
        attempt();
    });
}
function getPythonPath() {
    if (!isDev) {
        // Production: Backend is bundled inside the app
        // In macOS .app: Contents/Resources/backend/backend
        // In Windows/Linux: resources/backend/backend(.exe)
        const possiblePath = path_1.default.join(process.resourcesPath, 'backend', 'backend');
        // On Windows it might have .exe extension, but child_process.spawn handles it if we don't specify extension? 
        // Best to check specific platform or try specific paths.
        if (process.platform === 'win32') {
            return path_1.default.join(process.resourcesPath, 'backend', 'backend.exe');
        }
        return possiblePath;
    }
    // Development: Use local venv
    // Check standard locations
    const venvRoot = path_1.default.join(__dirname, '../../backend/venv');
    const binPath = path_1.default.join(venvRoot, 'bin', 'python'); // Mac/Linux
    const scriptsPath = path_1.default.join(venvRoot, 'Scripts', 'python.exe'); // Windows
    // We can't easily check file existence synchronously in specific setups without 'fs', 
    // but we can try to rely on platform.
    if (process.platform === 'win32') {
        return scriptsPath;
    }
    return binPath;
}
// Debug logging helper
function logToDesktop(message) {
    try {
        const logPath = path_1.default.join(electron_1.app.getPath('documents'), 'cracked_oura_electron_debug.log');
        const timestamp = new Date().toISOString();
        (0, fs_1.appendFileSync)(logPath, `[${timestamp}] ${message}\n`);
    }
    catch (e) {
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
        pythonProcess = (0, child_process_1.spawn)(exePath, [
            '-m', 'uvicorn',
            'backend.src.api.main:app',
            '--host', '127.0.0.1',
            '--port', '8000',
            '--reload'
        ], {
            cwd: path_1.default.join(__dirname, '../../'),
            stdio: 'inherit'
        });
    }
    else {
        logToDesktop("Running in PROD mode");
        // Production: Run the compiled executable directly
        if (!(0, fs_1.existsSync)(exePath)) {
            logToDesktop(`CRITICAL ERROR: Backend executable NOT FOUND at ${exePath}`);
        }
        else {
            logToDesktop(`Backend executable confirmed at ${exePath}`);
        }
        try {
            // It starts uvicorn internally (if main.py calls uvicorn.run)
            pythonProcess = (0, child_process_1.spawn)(exePath, [], {
                cwd: path_1.default.dirname(exePath), // Run from its own directory to find dependencies/relative files
                stdio: ['ignore', 'pipe', 'pipe'], // Capture stdout/stderr
                env: { ...process.env, PORT: '8000' } // Pass port if needed
            });
            logToDesktop(`Backend process spawned with PID: ${pythonProcess ? pythonProcess.pid : 'NULL'}`);
        }
        catch (spawnError) {
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
    }
    else {
        logToDesktop("pythonProcess is undefined after attempt!");
    }
}
electron_1.app.on('ready', async () => {
    // A stale singleton lock can survive an unclean shutdown. Only treat a
    // second launch as a duplicate when the existing app actually serves the
    // local backend; otherwise let this instance recover and take over.
    if (!gotSingleInstanceLock) {
        try {
            await waitForBackendReady(5000);
            logToDesktop('Another Cracked Oura instance is active; exiting this duplicate.');
            electron_1.app.quit();
            return;
        }
        catch {
            logToDesktop('Stale Cracked Oura instance lock detected; taking over.');
        }
    }
    ensureLaunchOnStartupConfigured();
    startHidden = launchedFromLogin();
    logToDesktop(`App ready (packaged=${electron_1.app.isPackaged}, startHidden=${startHidden})`);
    startPythonBackend();
    try {
        await waitForBackendReady();
        logToDesktop('Backend ready. Opening desktop window.');
    }
    catch (error) {
        logToDesktop(`Backend readiness check failed: ${error?.message || error}`);
    }
    createWindow();
    createTray();
});
electron_1.app.on('window-all-closed', () => {
    // Do NOT quit. We want to stay alive in the tray.
    if (process.platform !== 'darwin') {
        // On Windows/Linux we might want to quit if tray is not used, 
        // but here we ARE using tray, so we stay alive.
        // app.quit(); 
    }
});
electron_1.app.on('activate', () => {
    if (mainWindow === null) {
        createWindow();
    }
    else {
        mainWindow.show();
    }
});
electron_1.app.on('before-quit', () => {
    isQuitting = true;
});
electron_1.app.on('will-quit', () => {
    if (pythonProcess) {
        pythonProcess.kill();
    }
});
