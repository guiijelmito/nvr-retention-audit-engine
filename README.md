# NVR Retention & Continuous Recording Audit Engine

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Playwright](https://img.shields.io/badge/Playwright-Automation-green.svg)](https://playwright.dev/python/)
[![Status](https://img.shields.io/badge/Status-In%20Development-yellow.svg)]()

Automated enterprise-grade solution engineered to audit multi-channel Network Video Recorders (NVRs) across educational facilities, ensuring strict compliance with non-stop (continuous) recording policies, hardware degradation detection, and automated cloud reporting.

---

## Key Features

- **Pre-Flight Connectivity Check:** Fast-fails unreachable NVR units via lightweight HTTP tests before executing heavy historical scans.
- **Strict Daily Sequential Non-Stop Verification:** Iterates linearly up to 730 days backwards with multi-layered validations to eliminate false positives commonly introduced by wide-block heuristics.
- **Session & Token Leak Mitigation:** Implements rigorous `try...finally` blocks ensuring immediate token closure (`action=close`) on proprietary NVR firmware APIs, protecting device resources.
- **Automated Visual Evidence Capture:** Uses Playwright in headless mode to securely interact with NVR web GUIs, automate authentication, navigate search menus, select historical calendar periods, and snapshot full-page compliance proofs.
- **Cloud Integration & Matrix Sync:** Dynamically structures audit outputs into horizontal matrices and syncs compliance data with Google Sheets via `gspread` and a service account.
- **Automated Ticket Creation:** Opens, documents, and closes service tickets on the 7LAN helpdesk for each audited unit via Playwright automation.
- **Environment-Driven Configuration:** Decouples environment secrets using `python-dotenv` while externalizing unit topologies and authentication credentials.

---

## Tech Stack

- **Language:** Python 3.10+
- **Automation:** Playwright for Python
- **HTTP / Auth:** `requests` with HTTP Digest Authentication (NVR proprietary APIs)
- **Cloud Sync:** `gspread`, `google-auth` (Google Sheets)
- **Data Handling:** `pandas`
- **Environment Management:** `python-dotenv`

---

## Installation & Setup

### 1. Clone the repository

```bash
git clone <repository-url>
cd <repository-name>
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Configure environment variables

Create a `.env` file in the root directory based on `.env.example`:

```env
NVR_USUARIO=
NVR_SENHA=
LAN7_USER=
LAN7_PASS=
LAN7_URL=
LAN7_CLIENTE=
LAN7_SOLICITANTE=
PASTA_EVIDENCIAS=
```

### 5. Add local reference files (not versioned)

Place the following files in the project root — both are git-ignored due to sensitive content:

- `escolas.json` — mapping of school units to their NVR IP addresses.
- `credenciais.json` — Google Cloud service account credentials, required for Google Sheets sync.

---

## Usage

Run the full audit pipeline:

```bash
python main.py
```

---

## Project Structure

```
├── main.py                # Application entry point
├── nvr_audit.py            # Core audit engine: connectivity checks and daily non-stop verification
├── nvr_capture.py           # Playwright module for GUI interaction and evidence screenshots
├── cloud_sync.py             # Google Sheets synchronization and report updating
├── ticket_automation.py       # 7LAN service desk ticket automation
├── config.py                   # Environment loading, path resolution, and logging setup
├── escolas.json                 # School units and NVR IP mapping (git-ignored)
├── credenciais.json              # Google service account credentials (git-ignored)
├── requirements.txt               # Explicit dependencies manifest
├── .env                             # Sensitive credentials (git-ignored)
├── .env.example                      # Template for environment variables
├── .gitignore                         # Excludes venv, .env, credentials, and local data files
└── README.md                           # Project documentation
```

---

## License

This project is proprietary software developed for **Verth Tecnologia**.
