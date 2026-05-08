# Warranty Attribution & Customer Intelligence Flow

```text
                    ┌──────────────────────┐
                    │  Customer Purchases  │
                    │  Product on Flipkart │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ QR Warranty Form     │
                    │ (Google Sheets)      │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ Invoice Upload       │
                    │ (Google Drive Link)  │
                    └──────────┬───────────┘
                               │
                               ▼
               ┌────────────────────────────┐
               │ Incremental Sync Engine    │
               │ (FastAPI + APScheduler)    │
               └──────────┬─────────────────┘
                          │
                          ▼
               ┌────────────────────────────┐
               │ Drive File Reader          │
               │ In-Memory Streaming        │
               └──────────┬─────────────────┘
                          │
                          ▼
               ┌────────────────────────────┐
               │ Gemini AI OCR Engine       │
               │ Invoice Understanding      │
               └──────────┬─────────────────┘
                          │
                          ▼
               ┌────────────────────────────┐
               │ Structured Extraction      │
               │ JSON + SQLite Storage      │
               └──────────┬─────────────────┘
                          │
          ┌───────────────┴────────────────┐
          ▼                                ▼
┌────────────────────┐        ┌────────────────────┐
│ Shopify Orders     │        │ Matching Engine    │
│ Google Sheets      │        │ Email/Phone/Fuzzy  │
└──────────┬─────────┘        └──────────┬─────────┘
           │                              │
           └──────────────┬───────────────┘
                          ▼
               ┌────────────────────────────┐
               │ Customer Intelligence DB   │
               └──────────┬─────────────────┘
                          ▼
               ┌────────────────────────────┐
               │ React Analytics Dashboard  │
               │ KPIs + Charts + Segments   │
               └────────────────────────────┘

```
