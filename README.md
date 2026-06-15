# SmartLedger

**A Student Expense Intelligence Dashboard** — import transactions, let AI categorize them, and understand where your money goes.

---

## About

SmartLedger is a personal finance web app built for college students who want clarity on their spending without the overhead of a full banking tool. Upload a CSV export from your bank, and SmartLedger handles the rest: it parses your transactions, detects recurring subscriptions, and — most importantly — **automatically categorizes every expense using AI**.

### Automatic Expense Categorization

The standout feature is the AI-powered categorization pipeline built on **OpenAI GPT-4o-mini**. When you import transactions or add one manually, SmartLedger sends each uncategorized transaction's description and vendor to the model, which returns the best-fit category from your personal category list. You can accept or reject each suggestion individually, or batch-accept all pending suggestions at once. This eliminates the tedious manual work of labeling hundreds of bank transactions.

---


## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, Django 5.2, Django REST Framework |
| Database | MySQL |
| AI | OpenAI API |
| Frontend | Bootstrap 5, Chart.js, Django Templates, Vanilla JS |
| Authentication | Django built-in auth |

---

## System Architecture

```
┌─────────────────────────────────────────────────────┐
│                      Browser                        │
│         (Bootstrap 5 + Chart.js + Vanilla JS)       │
└────────────────────────┬────────────────────────────┘
                         │  HTTP
          ┌──────────────┴──────────────┐
          │                             │
          ▼                             ▼
  ┌───────────────┐           ┌─────────────────┐
  │  Django Views │           │  REST API Views  │
  │  (HTML/SSR)   │           │  (JSON endpoints)│
  └───────┬───────┘           └────────┬────────┘
          │                            │
          └──────────┬─────────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │     Services Layer    │
         │                       │
         │  ┌─────────────────┐  │
         │  │  csv_service    │  │  ← CSV parsing, duplicate detection
         │  ├─────────────────┤  │
         │  │  ai_service     │──┼──────────────► OpenAI API
         │  ├─────────────────┤  │                (GPT-4o-mini)
         │  │ dashboard_      │  │
         │  │   service       │  │  ← Aggregations, chart data
         │  ├─────────────────┤  │
         │  │ subscription_   │  │
         │  │   service       │  │  ← Recurring pattern detection
         │  └─────────────────┘  │
         └───────────┬───────────┘
                     │
                     ▼
          ┌──────────────────────┐
          │    MySQL Database    │
          │                      │
          │  User               │
          │  Category           │
          │  Transaction        │
          │  ImportHistory      │
          └──────────────────────┘
```

### Key Design Decisions

- **Services layer** (`core/services/`) isolates business logic from views — each service module owns one domain (CSV, AI, dashboard, subscriptions)
- **Normalized vendor names** stored on every transaction enable accurate grouping for subscription detection and vendor analytics
- **Amounts always positive** — the `transaction_type` field (income/expense) carries the sign, keeping aggregation queries simple
- **Per-user data scoping** — every query is filtered by `request.user`; categories and transactions are never shared across accounts
