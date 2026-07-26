<div align="center">
  <img src="frontend/public/icon.png" alt="Cracked Oura Logo" width="128">
  <h1>Cracked Oura</h1>
  <p><b>Free application that gives you full access to your Oura ring data.</b></p>
  
  [![GitHub release](https://img.shields.io/github/v/release/EIrno/Cracked-Oura?label=Latest%20Release)](https://github.com/EIrno/Cracked-Oura/releases/latest)
  ![Status](https://img.shields.io/badge/Status-Alpha-red)
</div>

---

### Pay for the ring, not for the app that is not even that good
Oura ring paywalls the data behind a subscription, but luckily you can export your data from Oura and import it to Cracked Oura.

**Cracked Oura** is an open-source desktop application that gives you a local dashboard for Oura ring data you already own or export. Metrics live in a SQLite database on your machine.

**Key benefits**
- **No Oura app subscription required** to browse data you have imported or synced into the local database.
- **Privacy first:** Data stays on your computer unless you export it or explicitly enable features (e.g. mobile sync, cloud LLM).
- **Deeper views:** Trends, baselines, contributor breakdowns, and analysis tools beyond a single-day summary.

<img width="1470" height="916" alt="Cracked Oura front page" src="https://github.com/user-attachments/assets/cda629a9-5072-4a5f-9e5d-6ddb3873c0f0" />

---

## What this app does (and does not)

| Does | Does not |
|------|----------|
| Imports Oura **data exports** (ZIP) or automates export requests via your Oura login | Replace the Oura ring firmware, cloud account, or official mobile app |
| Stores and queries metrics locally (sleep, readiness, activity, workouts, etc.) | Guarantee parity with every chart or feature in the paid Oura app |
| Shows **Today**, **Sleep**, **Readiness**, and **Activity** views with scores, contributors (with 7-day sparklines), baselines, and guidance | Provide medical advice; insights are informational only |
| Customizable dashboard widgets and layout editor | Require an Oura subscription for **viewing data you already exported** |
| Optional **Android companion** sync from desktop ([docs](docs/android-mobile-sync.md)) | Send your health data to our servers (there are none) |
| Experimental **AI analyst** (local or API LLM, your choice) | Ship as a notarized/signed product on all platforms yet (see [Troubleshooting](#troubleshooting)) |

> **Data source:** You need Oura export data in the local DB—either from [membership.ouraring.com/data-export](https://membership.ouraring.com/data-export) or from the in-app automation flow after signing in. Without data, views show empty states.

> **Not affiliated with Oura Health Oy.** This is an independent open-source project. Use at your own risk.

---

## Features

### Oura ring data without subscription
Browse sleep, readiness, and activity from your **local database**—no ongoing Oura app subscription required for that. Thanks to EU data portability, you can export from Oura and import here, or use in-app automation after login.

**Automation** requests exports from Oura and imports them into SQLite. **Manual import** works from a ZIP at [membership.ouraring.com/data-export](https://membership.ouraring.com/data-export).

### Contributor insights (Sleep / Readiness / Activity)
Per-domain contributor cards show each factor’s score, status, short explanation, and a **7-day sparkline**. On detail views, the lowest-scoring “pay attention” contributor is highlighted as a hero card; **Today** uses compact chips with links into the full breakdown.

<img width="1470" height="916" alt="Cracked Oura automation" src="https://github.com/user-attachments/assets/8aa42539-f014-4254-8885-9d6dfabf13b2" />
<img width="1470" height="916" alt="Cracked Oura logn term charts" src="https://github.com/user-attachments/assets/6cbd5345-d81e-4000-ade0-a0ea4e21508c" />


### Desktop Dashboard that can be customized
View your Sleep, Readiness, and Activity scores, etc in a desktop dashboards that is at least as good as the official Oura dashboard. The dashboards can be customized to show the data that you want to see. 

<img width="1470" height="916" alt="Cracked Oura widget editor" src="https://github.com/user-attachments/assets/39103072-e176-4b13-86df-95eaacdd3ac1" />
<img width="1470" height="916" alt="Cracked Oura layout editor" src="https://github.com/user-attachments/assets/43925f97-9d94-48aa-8b26-36a096499c0c" />

### AI Health Analyst
Oura's own AI advisor is quite limited. It does not have access to your historical data and cannot answer questions about your health trends, because it has only a few days of data available. 

Cracked Oura can leverage local LLMs to analyze your health data and provide insights. 

> [!NOTE]
> This feature is still experimental, not documented, and under development and will be improved in the future. 

<img width="1470" height="916" alt="Cracked Oura advisor" src="https://github.com/user-attachments/assets/e9ce6ac2-60da-486f-a01f-8cd03dce6337" />

---

## Getting Started

### Installation
1.  **Download** the latest release for your operating system:
    -   [**GitHub Releases**](https://github.com/dancingmadkefka/Cracked-Oura/releases) — Windows installer (`.exe`) is built automatically for each version tag
    -   macOS `.dmg` / Linux packages — build from source until CI supports them ([releasing guide](docs/RELEASING.md))

2.  **Install & Run** the application.
3.  **Login** to your Oura account when prompted to sync your historical data.


> [!NOTE]
> Most of the features are still experimental and under development and will be improved in the future. 

### Troubleshooting

> **"App is damaged and can't be opened"** (macOS)
> This is a known Gatekeeper issue because the app is not notarized by Apple.
> To fix, move the app to your `Applications` folder and run this in Terminal:
> ```bash
> sudo xattr -cr "/Applications/Cracked Oura.app"
> ```

> [!NOTE]
> This project is not affiliated with, associated with, or endorsed by Oura Health Oy. Use at your own risk.

---

## For Developers

We welcome contributions.

### Tech Stack
-   **Frontend:** Electron, React, TypeScript, Tailwind
-   **Backend:** Python, FastAPI, SQLite
-   **Mobile:** Kotlin, Jetpack Compose, Room, DataStore, Retrofit

### Android Mobile Sync

This repo now includes:

- A token-protected mobile sync API on the desktop/backend side
- A native Android client under [`android-mobile/`](android-mobile)

Setup and usage are documented in [`docs/android-mobile-sync.md`](docs/android-mobile-sync.md).

### Automatic local OTP recovery

For a local-only, deterministic Thunderbird/Betterbird OTP flow that resumes Oura login without copy/paste, see [`docs/automatic-local-otp-recovery.md`](docs/automatic-local-otp-recovery.md).

### Build from Source

**macOS / Linux:**
```bash
# 1. Clone Repository
git clone https://github.com/EIrno/Cracked-Oura.git
cd Cracked-Oura

# 2. Setup Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install pyinstaller

# 3. Setup Frontend
cd ../frontend
npm install
npm run dev
```

**Windows (PowerShell):**
```powershell
# 1. Clone Repository
git clone https://github.com/EIrno/Cracked-Oura.git
cd Cracked-Oura

# 2. Setup Backend
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install pyinstaller

# 3. Setup Frontend
cd ..\frontend
npm install
npm run dev
```
If you're using Command Prompt, activate the environment with:
```bat
venv\Scripts\activate.bat
```

### Build for Production
Creates a desktop installer. The UI is built with Vite, bundled into the Python backend via PyInstaller, then packaged with Electron Builder:

```bash
cd frontend
npm run build
# Installer output: frontend/dist/ (e.g. Cracked Oura Setup 0.2.0.exe on Windows)
# macOS: .dmg · Windows: NSIS .exe · Linux: AppImage / .deb
```

> On Windows, quit any running Cracked Oura instance before rebuilding so output files are not locked.

### Publishing a release

See **[docs/RELEASING.md](docs/RELEASING.md)** for tagging, CI automation, and manual upload steps.
