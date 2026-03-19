# SmartLedger Product Requirements Document (PRD)

## Product Overview

Freelancers, small businesses, and individuals often struggle to track and analyze their financial transactions efficiently. While bank statements and spreadsheets provide raw transaction data, they lack tools for structured analysis, categorization, and financial insights.

Most existing solutions are either overly complex accounting software or simple expense trackers that do not provide meaningful analytics. Users need a lightweight platform that allows them to:

- Import and manage financial transactions
- Automatically categorize expenses
- Analyze spending patterns
- Identify major vendors and spending trends
- Query and filter transactions easily

SmartLedger addresses this gap by providing a centralized platform where users can upload financial data, manage transactions, and gain actionable insights through dashboards and analytics.

---

# Technology Solution Statement

SmartLedger will be implemented as a **fullstack financial analytics platform** that enables users to ingest, manage, and analyze transaction data through a web-based interface.

The system will provide APIs for transaction ingestion, categorization, and analytics queries. Users will interact with the system through a frontend dashboard that displays financial insights such as spending trends, category distributions, and vendor analytics.

The backend services will process transaction data, store records in a relational database, and expose endpoints for querying financial information. The platform also supports CSV-based transaction ingestion to simplify importing financial records.

The architecture is designed to demonstrate scalable backend services, structured database design, and interactive data visualization.

---

# Business Functions and Functional Requirements

SmartLedger will support the following core business functions.

---

## 1. User Authentication and Account Management

### Description

The system must allow users to securely create accounts and manage their financial data.

### Functional Requirements

The system shall:

- Allow new users to register accounts.
- Allow existing users to log in securely.
- Allow users to log out of the system.
- Ensure user financial data is isolated and accessible only by the account owner.
- Allow users to update their profile information.
- Use secure password hashing for authentication.

---

## 2. Transaction Management

### Description

Users must be able to track financial transactions such as expenses and income.

### Functional Requirements

The system shall:

- Allow users to manually add financial transactions.
- Allow users to upload transaction data through CSV files.
- Detect and flag duplicate transactions during file upload (matched on date + amount + normalized description). Duplicate detection is checked against all existing transactions for the logged-in user and also within the same CSV file.
- Users shall be able to upload CSV files containing transaction data. The backend shall parse the uploaded file and extract transaction records. The system shall validate each record before storing it. Valid, non-duplicate rows are inserted into the database immediately after upload. A summary (ImportHistory) is created for every upload.
- The expected CSV format uses fixed column headers: `Date`, `Description`, `Amount`, `Vendor`. A negative `Amount` value automatically sets the transaction type to `expense`; a positive value sets it to `income`. Example:

  ```
  Date,Description,Amount,Vendor
  2024-01-15,AWS Invoice,-120.00,Amazon
  2024-01-16,Client Payment,5000.00,Acme Corp
  ```

- Store transaction information including:
  - date
  - description
  - amount
  - vendor / payee
  - normalized_vendor (lowercased, whitespace-collapsed vendor used for grouping)
  - category
  - transaction type (income or expense)
- Allow users to edit and delete transactions.
- Display transactions in a paginated table (25 rows per page).
- Allow transactions to be filtered by:
  - date range (`date_from`, `date_to`) — cross-field validation rejects `date_from > date_to`
  - category
  - transaction type
  - vendor (partial, case-insensitive match)
  - amount range (`amount_min`, `amount_max`) — cross-field validation rejects `amount_min > amount_max`
- Allow transactions to be sorted by date, amount, and category.
- Preserve active filter and page state across edit and delete flows (via a `back` query parameter). Back URLs are validated to be local paths only — protocol-relative or external URLs are rejected.

---

## 3. Transaction Categorization

### Description

Transactions must be categorized so that financial reports can be generated and expenses can be tracked effectively.

### Functional Requirements

The system shall:

- Allow users to create and manage transaction categories.
- Store a `type` on each category indicating whether it applies to income or expenses.
- Allow users to assign categories to transactions.
- Store categories in the database.
- Seed default categories per user at registration time (triggered via Django's `post_save` signal on the `User` model). Each user gets their own isolated copy of the defaults:
  - Revenue (income)
  - Consulting (income)
  - Software (expense)
  - Utilities (expense)
  - Office Supplies (expense)
  - Meals (expense)
  - Travel (expense)
  - Other (expense)
- Allow transactions to be filtered by category.
- Use categories when generating financial summaries.

---

## 4. AI-Powered Transaction Category Suggestions

### Description

SmartLedger includes an AI-assisted feature that suggests categories for financial transactions.

### Functional Requirements

The system shall:

- Send transaction descriptions to the OpenAI API using the `gpt-4o-mini` model. The API key is stored in the `OPENAI_API_KEY` environment variable.
- Receive category suggestions from the AI service.
- Store the AI-suggested category on the transaction in the `ai_suggested_category` field.
- Display the suggested category inline in the transaction list with Accept and Change buttons per row.
- Allow the user to accept a suggestion row-by-row using the per-row Accept button. Accepting sets `category = ai_suggested_category` for that transaction.
- Allow the user to change a suggestion by clicking Change, which opens the transaction edit form.
- Provide a per-row "Suggest" button for uncategorized transactions that have no existing suggestion — calls the AI for that single transaction and stores the result.
- Provide a "Suggest All Uncategorized" button on the transactions page that:
  - Runs AI suggestions in batch for all uncategorized transactions (no category, no existing suggestion) for the logged-in user.
  - Saves results to `ai_suggested_category` on each transaction.
  - Updates the UI inline without a page reload.
- Provide a "Batch Accept Suggestions" button on the transactions page that:
  - Accepts all existing AI suggestions at once for the current user.
  - Only affects transactions where `category` is null and `ai_suggested_category` is not null.
  - Does NOT generate new suggestions.
  - Does NOT overwrite transactions that already have a category.
  - Shows a flash message with the count of transactions updated.
  - Redirects back to the transaction list preserving the current filter state.
- Provide a "Suggest" button on the transaction add/edit form that calls the AI for the current description/vendor and pre-fills the category dropdown.
- Handle AI API failures gracefully — if the API is unavailable or returns an error, display a user-friendly message and allow the user to categorize manually without disruption.

The AI feature will assist users but will not automatically override user decisions.

---

## 5. Financial Reports and Dashboard

### Description

SmartLedger must provide financial summaries that help users understand their spending patterns, income trends, and overall financial health.

The dashboard acts as the central overview page of the application.

### Functional Requirements

The system shall:

- Display a financial dashboard summarizing key metrics.
- Show total income for a selected date range.
- Show total expenses for a selected date range.
- Display net cash flow (income minus expenses).
- Display recent transactions (last 10).
- Display uncategorized transactions requiring review (all-time count, always visible).
- Display expenses grouped by category.
- Display monthly summaries of income and expenses.
- Allow users to filter reports by date range.
- Allow users to export financial reports as CSV files, respecting any active filters.
- Display top 5 vendors by total spend, grouped by `normalized_vendor` so that vendor name variants (e.g. "Amazon", "AMAZON", " amazon ") count as a single vendor.

### Example Dashboard Metrics

The dashboard may include:

- Total Income
- Total Expenses
- Net Cash Flow
- Expense Breakdown by Category (doughnut chart)
- Monthly Income vs Expense Chart (grouped bar chart)
- Spending Trend over time (line chart)
- Top Vendors by Spend (horizontal bar chart)
- Recent Transactions table

---

## 6. Transaction Search and Filtering

### Description

The system shall allow users to search and filter transactions.

### Functional Requirements

Users shall be able to filter transactions by:

- Category
- Vendor
- Date range (with validation that start ≤ end)
- Amount range (with validation that min ≤ max)

Example queries:

- Show transactions where category = Travel
- Show transactions greater than $100
- Show transactions from last month

---

## 7. Vendor Insights

### Description

The system shall provide analytics on vendor spending patterns.

### Functional Requirements

The system shall:

- Normalize vendor names on save: strip leading/trailing whitespace, collapse internal whitespace, and lowercase. This is stored in the `normalized_vendor` field and used for grouping.
- Group vendor analytics by `normalized_vendor` so variants like "Amazon", "AMAZON", and " Amazon " are treated as the same vendor.
- Display top vendors by total spending on the dashboard.

---

## 8. Import History

### Description

Every CSV upload creates a permanent record so users can audit what was imported.

### Functional Requirements

The system shall:

- Create an `ImportHistory` record for every CSV upload, storing:
  - `filename`
  - `uploaded_at`
  - `total_rows` (all data rows in the file)
  - `imported_count` (rows successfully imported)
  - `duplicate_count` (rows skipped as duplicates)
  - `invalid_count` (rows skipped due to parse errors)
  - `error_details` (list of `{row_num, errors}` for each invalid row)
- Provide an Import History list page showing all past uploads for the logged-in user.
- Provide an Import History detail page showing the full breakdown for a specific upload.
- Scope import history strictly to the logged-in user — users cannot access another user's history.
- Link to Import History from the Transactions dropdown in the navbar.

---

## 9. Audit Logging

### Description

The system must maintain an audit trail of significant user actions for accountability and traceability.

### Functional Requirements

The system shall create an `AuditLog` entry for each of the following actions:

| Action | Trigger | Transaction FK |
|---|---|---|
| `import` | Successful CSV upload (at least one row imported) | None (bulk) |
| `edit` | Transaction saved via edit form | Set to the edited transaction |
| `delete` | Transaction deleted | None (SET_NULL after deletion) |
| `ai_accepted` | Single-row AI suggestion accepted via Accept button | Set to the accepted transaction |
| `ai_accepted` | Batch Accept Suggestions completed | None (bulk); metadata includes `batch: true`, `count`, `transaction_ids` |

Each log entry stores: `user`, `transaction` (nullable FK), `action`, `metadata` (JSON), `created_at`.

---

## 10. Date Input Format

### Description

All date inputs across the application use a single, consistent typed format.

### Functional Requirements

The system shall:

- Use `type="text"` inputs (not browser date pickers) for all date fields.
- Accept only the format `YYYY-MM-DD` in all date fields throughout the app (dashboard filter, transaction filter, transaction add/edit form).
- Display a `YYYY-MM-DD` placeholder on all date inputs.
- Reject any other format (e.g. `MM/DD/YYYY`, `DD-MM-YYYY`) with a user-friendly validation error.
- Apply this format consistently via a shared `DateTextInput` widget and `input_formats=['%Y-%m-%d']` on all `DateField` instances.

---

# Non-Functional Requirements

## Performance

- Transaction and dashboard pages should load within 2 seconds under normal conditions.

## Security

- Passwords must be encrypted using secure hashing.
- User data must be protected and isolated per account.
- Authentication must be required for all financial data access.
- All forms must include CSRF protection.
- Back-redirect URLs must be validated to be local paths only. Protocol-relative URLs (e.g. `//evil.com`) and absolute external URLs are rejected; the app falls back to the transaction list.

## Usability

- The user interface must be simple and intuitive.
- Forms must provide inline validation feedback.
- The UI must be responsive and usable on mobile browsers.
- Filter forms must validate cross-field constraints (date range direction, amount range direction) and show clear error messages.

## Scalability

- The database design must support increasing numbers of users and transactions.

## Reliability

- The application must handle third-party API failures (AI service) without crashing or blocking core functionality.

## Currency

- All monetary values are stored and displayed in USD. Multi-currency is out of scope.

---

# High-Level System Design

SmartLedger follows a **three-layer web application architecture**.

```
User Browser
    ↓
Django Views + REST Framework
    ↓
SQLite / MySQL Database
    ↓
External AI API (OpenAI)
```

---

## System Architecture Overview

```
Web Browser (Frontend)
    ↓
Django Views and Business Logic
    ↓
Django ORM
    ↓
Database

Django Views → External AI API (for category suggestions)
```

---

# Technology Stack

## Frontend Layer

Technologies:

- HTML5
- CSS3
- Bootstrap 5
- Bootstrap Icons
- JavaScript (vanilla, no framework)
- Django Template Engine
- Chart.js (for analytics visualizations)

Responsibilities:

- Render user interface
- Display transaction tables
- Submit user forms
- Dashboard visualization
- Filtering and search functionality
- Show AI category suggestions inline
- Per-row and batch AI accept actions via fetch API (no page reload)

---

## Backend Layer

Technologies:

- Python
- Django REST Framework
- Django ORM
- Django Authentication System

Responsibilities:

- Process HTTP requests
- Serve server-rendered HTML pages via Django Templates
- Expose REST API endpoints for AI category suggestions (AJAX)
- Handle file uploads (CSV)
- Manage transactions, categories, import history, and audit logs
- Perform business logic and financial calculations
- Serve filtered transaction data
- Integrate with AI API
- Enforce security and authentication

---

## Database Layer

Technology:

- SQLite (development) / MySQL (production target)

Primary entities:

- User
- Transaction
- Category
- AuditLog
- ImportHistory

### Key Field Notes

**Transaction:**
- `id`
- `user`: FK to the logged-in user (all queries scoped to this)
- `date`
- `description`
- `amount`: stored as Decimal (10, 2) in USD
- `vendor`
- `normalized_vendor`: lowercased, whitespace-collapsed vendor (auto-set on save, indexed)
- `transaction_type`: income or expense (auto-derived from CSV amount sign)
- `category`: FK to Category (nullable — unset until user confirms)
- `ai_suggested_category`: FK to Category, the category suggested by the AI (nullable)
- `created_at`, `updated_at`

**AuditLog:**
- `id`
- `user`: FK to User (SET_NULL on delete)
- `transaction`: FK to Transaction, nullable (SET_NULL on delete)
- `action`: one of `import`, `edit`, `delete`, `ai_accepted`
- `metadata`: JSON field for action-specific context
- `created_at`

**ImportHistory:**
- `id`
- `user`: FK to User
- `filename`
- `uploaded_at`
- `total_rows`, `imported_count`, `duplicate_count`, `invalid_count`
- `error_details`: JSON list of `{row_num, errors}` per invalid row

---

## AI Integration Layer

Technology:

- OpenAI API (`gpt-4o-mini` model)

Responsibilities:

- Analyze transaction descriptions and vendor names
- Suggest transaction categories from the user's category list
- Return recommendations to the backend for storage and user review

The AI system functions only as an assistant and does not automatically modify financial data without user confirmation. The backend must handle API errors gracefully and allow all workflows to proceed without AI assistance if the service is unavailable.

---

# Testing Requirements

- Unit tests must be written for core business logic: duplicate detection, financial calculations, category assignment, form validation, vendor normalization, audit logging, import history, and access control.
- Integration tests must cover: CSV export filter behavior, CSV upload creates ImportHistory, safe redirect validation, batch accept behavior.
- Django's built-in test framework (`python manage.py test`) is used for all automated tests.
- Each feature step should include a manual QA checklist confirming all functional requirements work end-to-end before moving to the next step.

---

# Deployment

- **Primary target:** Local development environment.
- The application must run locally using `python manage.py runserver` with a locally hosted database.
- The project should be structured to support future deployment to a cloud platform (e.g., Railway, Heroku, or a VPS) with minimal configuration changes.
- Environment-specific settings (database credentials, API keys) must be stored in environment variables or a `.env` file and never committed to source control.

---

# Build Roadmap

SmartLedger is built incrementally. Each step below is independently buildable and testable.

---

## Step 1 — Project Setup

**Goal:** Get a working Django project connected to a database with a base UI shell.

**Deliverables:**
- Django project (`smartLedger`) with a `core` app created
- Database configured and connected via environment variables
- `requirements.txt` with all initial dependencies
- `.env` file for secrets — never committed
- `base.html` — Bootstrap 5 navbar, flash messages, content block
- Homepage view returning HTTP 200
- `python manage.py migrate` runs clean

---

## Step 2 — User Authentication

**Goal:** Users can register, log in, log out, and edit their profile.

**Deliverables:**
- Register view with `RegisterForm`
- Login and logout views using Django's built-in auth system
- Password reset flow (email sent to console)
- Profile edit page
- `post_save` signal seeds default categories for new users
- All routes protected by `@login_required` except `/register/` and `/login/`

---

## Step 3 — Transaction Categories

**Goal:** Users can manage the categories used to label transactions.

**Deliverables:**
- `Category` model with user scoping, type (income/expense), default seeding
- CRUD views for categories, scoped to `request.user`

---

## Step 4 — Transaction Management

**Goal:** Users can manually log transactions and bulk-import them via CSV.

**Deliverables:**
- `Transaction` model with all fields
- CRUD views for transactions
- CSV upload with duplicate detection, ImportHistory creation, and error reporting
- Transaction list with filters, sorting, and pagination

---

## Step 5 — AI Category Suggestions

**Goal:** Users can get AI-suggested categories for transactions.

**Deliverables:**
- `core/services/ai_service.py` with `suggest_category` and `batch_suggest`
- Per-row Suggest button on transaction list
- "Suggest All Uncategorized" batch button on transaction list
- Suggest button on transaction add/edit form
- Graceful error handling when AI is unavailable

---

## Step 6 — Financial Dashboard and Vendor Insights

**Goal:** Provide users with actionable insights into their financial activity.

**Deliverables:**
- Dashboard with KPI cards, charts (doughnut, bar, line), top vendors, recent transactions
- Date range filter on dashboard
- CSV export of filtered transactions
- Vendor normalization (`normalized_vendor` field) for consistent grouping

---

## Step 7 — Preserve Filter and Page State

**Goal:** Navigating to edit/delete and returning preserves the user's active filter and page.

**Deliverables:**
- `back` query parameter threaded through edit and delete flows
- `_safe_back()` helper validates local-path-only redirects (rejects external and protocol-relative URLs)
- Pagination links preserve filter query string

---

## Step 8 — Import Error Reporting and Import History

**Goal:** Users can review what happened after each CSV upload.

**Deliverables:**
- `ImportHistory` model with full upload statistics and per-row error details
- Import History list page and detail page
- Link in Transactions navbar dropdown
- Access control: users can only see their own import history

---

## Step 9 — Audit Logging

**Goal:** Maintain a traceable audit trail for all significant data changes.

**Deliverables:**
- `AuditLog` model with `action`, `user`, `transaction` FK, `metadata`
- Audit entries created for: edit, delete, CSV import, single AI accept, batch AI accept

---

## Step 10 — UI and Workflow Improvements

**Goal:** Improve date input consistency and add bulk AI acceptance.

**Deliverables:**
- Replace all browser date pickers with typed text inputs in `YYYY-MM-DD` format via shared `DateTextInput` widget
- Cross-field filter validation: `date_from > date_to` and `amount_min > amount_max` are rejected with clear messages
- "Batch Accept Suggestions" button: accepts all existing AI suggestions at once for the current user, logs a single audit entry, redirects back preserving filter state

---

# Out of Scope

The following features are noted for potential future development and are not included in this build:

- Invoice management
- Customer management
- Multi-currency support
- Transaction status (pending / cleared) — removed; all imported transactions are considered final
- Cloud deployment (the project structure supports it via `.env` configuration)
