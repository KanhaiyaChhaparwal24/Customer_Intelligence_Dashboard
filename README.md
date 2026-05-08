# 🧳 LuggageIQ — Customer Intelligence Dashboard

> A smart analytics system that automatically reads your warranty registrations and Shopify orders, reads customer invoices from Google Drive, and gives you a live dashboard showing who your customers are, where they came from, and who converted from Flipkart to your own website.

---

![Dashboard Preview](dash.png)

---

## 🤔 What Problem Does This Solve?

Your brand sells luggage on **Flipkart** and your own **D2C website (Shopify)**.

Customers who buy from Flipkart register their warranty using a QR code — and they upload their invoice as a photo or PDF to Google Drive.

You also have your Shopify order data in a separate Google Sheet.

**The question is:** *How many Flipkart buyers eventually came to your website and bought again? Who are the loyal repeat customers? Which products sell most? Which cities? What's your actual D2C revenue?*

This dashboard answers all of that — automatically, every 30 minutes, without any manual effort.

---

## 🔄 How It Works — The Complete Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        EVERY 30 MINUTES                         │
└─────────────────────────────────────────────────────────────────┘

         Google Sheets (Warranty Tab)
                    │
                    ▼
         Read only NEW rows (skip already processed)
                    │
                    ▼
         Each row has a customer's Google Drive link
         (could be a photo, PDF, or a whole folder)
                    │
                    ▼
         Open the Drive file — read it in memory
         (never saved to disk)
                    │
                    ▼
         Send to Gemini AI Vision (OCR)
         → Extract: name, email, phone, product,
           order ID, invoice date, city, amount, platform
                    │
                    ▼
         Save structured data to local database
                    │
                    ▼
         Google Sheets (Shopify Tab)
         → Read all D2C orders
                    │
                    ▼
         Match Flipkart customers ↔ Shopify customers
         (by email or phone number)
                    │
                    ▼
         Segment into:
         🟣 Converted (bought on both)
         🔵 Flipkart Only
         🟠 D2C Only
                    │
                    ▼
         Dashboard updates automatically
```

---

## 🏗️ Architecture (Simple Version)

```
┌─────────────────────────────────────────────────────────┐
│                     YOUR COMPUTER                        │
│                                                          │
│  ┌──────────────┐      ┌────────────────────────────┐   │
│  │   FRONTEND   │◄────►│       BACKEND (Python)     │   │
│  │  React App   │      │       FastAPI Server        │   │
│  │  Port 5173   │      │       Port 8000             │   │
│  └──────────────┘      └─────────────┬──────────────┘   │
│                                      │                   │
│                              ┌───────▼──────┐            │
│                              │   SQLite DB   │            │
│                              │  (local file) │            │
│                              └───────────────┘            │
└─────────────────────────────────────────────────────────┘
         │                          │
         ▼                          ▼
   Google Sheets              Gemini AI API
   Google Drive               (OCR Processing)
```

**Frontend** = What you see in the browser (charts, tables, KPI cards)

**Backend** = The brain — reads Google data, processes invoices, runs matching, exposes an API

**Database** = Stores all extracted invoice data and processed file IDs locally

**Scheduler** = Runs in the background, triggers a fresh sync every 30 minutes automatically

---

## 📊 What the Dashboard Shows

### Tab 1 — Overview
The main page with everything at a glance:

| Card | What it tells you |
|---|---|
| Flipkart Buyers | How many unique customers registered warranty (came from Flipkart) |
| D2C Customers | How many unique customers ordered from your website |
| Converted | Customers who did BOTH — bought on Flipkart AND your website |
| Conversion Rate | % of Flipkart buyers who came back to D2C |
| Total D2C Revenue | Sum of all Shopify orders |
| Avg Order Value | Average amount per D2C order |
| Repeat Customers | D2C customers who ordered more than once |
| Pending OCRs | Invoices waiting to be read |
| Failed OCRs | Invoices that couldn't be read (you can retry) |

**Charts included:**
- Customer segmentation donut (Converted vs FK-only vs D2C-only)
- Warranty registrations by month
- D2C revenue by month
- Top 10 products
- Top 10 cities (split Flipkart vs D2C)
- Size distribution
- Colour distribution
- Payment methods

### Tab 2 — Converted Customers
A table of every customer who bought on Flipkart AND came back to your website.
You can click **"View Journey"** to see their timeline: Flipkart purchase → D2C orders.

### Tab 3 — Flipkart Only
Customers who registered warranty but haven't bought from your D2C site yet.
These are your **retargeting audience**.

### Tab 4 — D2C Only
Customers who found you directly without going through Flipkart first.

### Tab 5 — All Customers
Every single customer in one unified searchable table with colour-coded source badges.

### Tab 6 — Invoice Processing
A live log of every invoice file that was processed — success, failed, or pending.
You can retry failed invoices with one click.

---

## 🔌 What It Connects To

| Service | What it does |
|---|---|
| **Google Sheets** | Reads warranty registrations (Tab 1) and Shopify orders (Tab 2) |
| **Google Drive** | Opens invoice files linked in the sheet — images, PDFs, folders |
| **Gemini AI (Vision)** | Reads the invoice image/PDF and extracts all the data |
| **SQLite** | Stores all extracted data locally on your machine |

---

## 🧠 Smart Features

### ✅ Never Re-Processes the Same Invoice
Every Drive file has a unique ID. Once processed, it's saved — next sync skips it completely. Even if the same file appears in multiple rows or refreshes, it's only OCR'd once.

### ✅ Only Reads New Rows
The system remembers the last sheet row it processed. On every sync, it only reads rows after that — so a sheet with 10,000 rows doesn't slow things down at all.

### ✅ Handles Both File and Folder Links
If a customer uploaded one image → reads that file.
If they uploaded a whole folder → reads all files in the folder.

### ✅ Column Name Flexibility
If your sheet uses "Mobile" instead of "Phone", or "Invoice Link" instead of "Invoice Upload" — it still works. The system fuzzy-matches column names automatically.

### ✅ Customer Matching
Matches Flipkart customers to Shopify customers using:
1. Exact email match
2. Exact phone number match
3. Name similarity (fuzzy match) as a fallback

### ✅ Duplicate Detection
If the same invoice or order ID appears twice, it's flagged automatically.

---

## 🚀 How to Start

### First Time Only
You'll need to sign into Google once. A browser window will pop up automatically when you start the backend.

### Every Time

**Terminal 1 — Start the Backend:**
```bash
cd e:\Coding\dashborad
.\venv\Scripts\python -m uvicorn main:app --host 0.0.0.0 --port 8000 --app-dir backend
```

**Terminal 2 — Start the Frontend:**
```bash
cd e:\Coding\dashborad\frontend
npm run dev
```

**Then open:** http://localhost:5173

---

## 📁 Project Structure (Simple)

```
dashborad/
│
├── backend/                  ← Python FastAPI server
│   ├── main.py               ← Server entry point
│   ├── config.py             ← All settings (reads .env)
│   ├── database.py           ← Database tables
│   ├── auth.py               ← Google login
│   ├── scheduler.py          ← Auto-sync every 30 min
│   ├── services/
│   │   ├── sheets_service.py ← Reads Google Sheets
│   │   ├── drive_service.py  ← Opens Drive files
│   │   ├── ocr_service.py    ← Gemini AI invoice reader
│   │   ├── sync_service.py   ← Puts it all together
│   │   └── analytics_service.py ← Calculates KPIs & charts
│   └── api/
│       ├── dashboard.py      ← Data endpoints for frontend
│       └── invoices.py       ← Sync & retry controls
│
├── frontend/                 ← React web app
│   └── src/
│       ├── pages/            ← 6 dashboard tabs
│       ├── components/       ← Charts, tables, cards
│       └── utils/            ← API calls, formatting
│
├── database/
│   └── intelligence.db       ← Local SQLite database (auto-created)
│
├── credentials.json          ← Google OAuth credentials
├── token.json                ← Auto-created after first login
├── .env                      ← Your API keys & settings
└── dash.png                  ← Dashboard screenshot
```

---

## ⚙️ Settings (.env file)

```env
GEMINI_API_KEY=your_gemini_key_here
GOOGLE_SHEET_NAME=Customer Data Sources Sample Structure
SYNC_INTERVAL_MINUTES=30
MAX_OCR_CONCURRENCY=3        # How many invoices to read at once
OCR_RETRY_LIMIT=3            # How many times to retry a failed invoice
ENABLE_DEBUG_DOWNLOADS=false # Keep false in production
```

---

## 🎯 Expected Output

When real data is loaded (actual warranty registrations + Shopify orders):

- Each Flipkart customer's invoice will be read and extracted
- You'll see real numbers in the KPI cards
- Charts will show your top cities, products, and revenue trends
- Converted Customers tab shows who crossed from Flipkart to D2C
- Invoice Processing tab shows every file with its status

**Currently** — the sheet has sample/header data only, so all cards show `—`. Once real data is added to the Google Sheet, the next auto-sync (or click "Sync Now") will populate everything.

---

## 🔐 Security Notes

- Your Gemini API key **never** leaves the backend server
- Invoice files are **never saved** to your computer — read in memory, processed, deleted
- Google login token is stored locally in `token.json` — never shared

---

*Built for production-scale use — designed to handle thousands of rows and hundreds of invoice files without breaking a sweat.*
