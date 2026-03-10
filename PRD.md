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

The backend services will process transaction data, store records in a relational database, and expose endpoints for querying financial information. The platform will also support CSV-based transaction ingestion to simplify importing financial records.

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
- Detect and flag duplicate transactions during file upload (matched on date + amount + description) and prompt the user before importing. Duplicate detection is checked against all existing transactions for the logged-in user.
- Users shall be able to upload CSV files containing transaction data. The backend shall parse the uploaded file and extract transaction records. The system shall validate each record before storing it. Parsed transactions shall be inserted into the database.
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
  - vendor/payee
  - category
  - transaction type (income or expense)
  - status (pending or cleared)
- Allow users to edit and delete transactions.
- Display transactions in a table format.
- Allow transactions to be filtered by:
  - date range
  - category
  - transaction type
  - vendor
  - amount
  - status
- Allow transactions to be sorted by date, amount, and category.

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

SmartLedger will include an AI-assisted feature that suggests categories for financial transactions.

### Functional Requirements

The system shall:

- Send transaction descriptions to the OpenAI API using the `gpt-4o-mini` model. The API key is stored in the `OPENAI_API_KEY` environment variable.
- Receive category suggestions from the AI service.
- Display the suggested category to the user.
- Allow the user to accept or modify the suggestion.
- Store both the AI-suggested category and the final user-selected category.
- Support batch categorization: when a file is uploaded, suggest categories for all uncategorized transactions in a single operation.
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
- Display recent transactions.
- Display uncategorized transactions requiring review.
- Display expenses grouped by category.
- Display monthly summaries of income and expenses.
- Allow users to filter reports by date range.
- Allow users to export financial reports as CSV files.
- Top vendors by total spend

### Example Dashboard Metrics

The dashboard may include:

- Total Income
- Total Expenses
- Net Cash Flow
- Expense Breakdown by Category
- Monthly Income vs Expense Chart
- Recent Transactions
- Pie chart for category distribution
- Bar chart for top vendors
- Line chart for spending trends over time

---

## 6. Transaction Search and Filtering

### Description

The system shall allow users to search and filter transactions.

### Functional Requirements

Users shall be able to filter transactions by:

- Category
- Vendor
- Date range
- Amount thresholds

Example queries:

- Show transactions where category = Travel
- Show transactions greater than $100
- Show transactions from last month

---

## 7. Vendor Insights

### Description

The system shall provide analytics on vendor spending patterns.

### Functional Requirements

The system shall generate insights including:

- Top vendors by total spending
- Total spend per vendor
- Number of transactions per vendor

---

# Non-Functional Requirements

## Performance

- Transaction and dashboard pages should load within 2 seconds under normal conditions.

## Security

- Passwords must be encrypted using secure hashing.
- User data must be protected and isolated per account.
- Authentication must be required for all financial data access.
- All forms must include CSRF protection.

## Usability

- The user interface must be simple and intuitive.
- Forms must provide inline validation feedback.
- The UI must be responsive and usable on mobile browsers.

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
Django REST Framework
    ↓
MySQL Database
    ↓ 
External AI API
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
MySQL Database

Django Views → External AI API (for category suggestions)
```

---

# Technology Stack

## Frontend Layer

Technologies:

- HTML5
- CSS3
- Bootstrap
- JavaScript
- Django Template Engine
- Chart.js (for analytics visualizations)

Responsibilities:

- Render user interface
- Display transaction tables
- Submit user forms
- Dashboard visualization
- Filtering and search functionality
- Show AI category suggestions

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
- Expose a REST API endpoint for AI category suggestions (AJAX)
- Handle file uploads (CSV)
- Manage transactions and categories
- Perform business logic and financial calculations
- Serve filtered transaction data
- Integrate with AI API
- Enforce security and authentication

---

## Database Layer

Technology:

- MySQL

Primary entities:

- User
- Transaction
- Category

### Key Field Notes

**Transaction:**
- `id`
- `user`: FK to the logged-in user (all queries scoped to this)
- `date`
- `description`
- `amount`: stored as Decimal (10, 2) in USD
- `vendor`
- `transaction_type`: income or expense (auto-derived from CSV amount sign)
- `status`: pending or cleared
- `category`: FK to Category (nullable — unset until user confirms)
- `ai_suggested_category`: FK to Category, the category suggested by the AI (nullable)
- `created_at`, `updated_at`

---

## AI Integration Layer

Technology:

- External AI API (e.g., OpenAI API)

Responsibilities:

- Analyze transaction descriptions
- Suggest transaction categories
- Return recommendations to the backend

The AI system functions only as an assistant and does not automatically modify financial data without user confirmation. The backend must handle API errors gracefully and allow all workflows to proceed without AI assistance if the service is unavailable.

---

# Testing Requirements

- Unit tests must be written for core business logic: transaction duplicate detection, financial report calculations, and category assignment logic.
- Each feature step should include a manual QA checklist confirming all functional requirements work end-to-end before moving to the next step.
- Django's built-in test framework (`python manage.py test`) will be used for automated tests.

---

# Deployment

- **Primary target:** Local development environment.
- The application must run locally using `python manage.py runserver` with a locally hosted MySQL instance.
- The project should be structured to support future deployment to a cloud platform (e.g., Railway, Heroku, or a VPS) with minimal configuration changes.
- Environment-specific settings (database credentials, API keys, email settings) must be stored in environment variables or a `.env` file and never committed to source control.

---

# Build Roadmap

SmartLedger will be built incrementally. Each step below is independently buildable and testable. Complete and validate each step before moving to the next.

---

## Step 1 — Project Setup

**Goal:** Get a working Django project connected to MySQL with a base UI shell.

**Deliverables:**
- Django project (`smartLedger`) with a `core` app created
- MySQL database configured and connected via environment variables
- `requirements.txt` with all initial dependencies:
  - `django`, `djangorestframework`, `mysqlclient`, `openai`, `python-dotenv`
- `.env` file for secrets (DB credentials, secret key) — never committed
- `TEMPLATES['DIRS']` set to a top-level `templates/` folder
- `base.html` — Bootstrap 5 navbar, flash messages, content block
- Homepage view returning HTTP 200
- `python manage.py migrate` runs clean

**Test:** Run `python manage.py migrate` successfully. Load the homepage at `http://127.0.0.1:8000/` and confirm it returns HTTP 200 with the Bootstrap navbar visible.

---

## Step 2 — User Authentication

**Goal:** Users can register, log in, log out, reset their password, and edit their profile.

**Deliverables:**
- Register view with `RegisterForm` (username, email, password1, password2)
- Login and logout views using Django's built-in auth system
- Password reset flow using Django's built-in password reset views (email sent to console via `console` email backend)
- Profile edit page (first name, last name, email)
- `post_save` signal on `User` wired in `core/apps.py` — seeds default categories for new users (used in Step 3)
- All routes protected by `@login_required` except `/register/` and `/login/`
- Navbar shows logged-in username and a logout link

**Test:** Register a new account → log in → update profile → log out → use "Forgot Password" (check terminal for reset link) → reset password → log back in.

---

## Step 3 — Transaction Categories

**Goal:** Users can manage the categories used to label transactions.

**Deliverables:**
- `Category` model: `user` (FK), `name`, `type` (income / expense), `created_at`
- CRUD DRF views: list, create, edit, delete — all scoped to `request.user`
- Default categories seeded per user on registration via `post_save` signal:
  - Revenue (income), Consulting (income)
  - Software (expense), Utilities (expense), Office Supplies (expense), Meals (expense), Travel (expense), Other (expense)
- Categories from other users are never visible or accessible

**Test:** Register two separate accounts. Confirm each has the default categories. Create a custom category on account 1, edit it, delete it. Confirm account 2 cannot see account 1's categories.

---

## Step 4 — Transaction Management

**Goal:** Users can manually log transactions and bulk-import them via CSV.

**Deliverables:**
- `Transaction` model with all fields: `user`, `date`, `description`, `amount` (Decimal 10,2), `vendor`, `transaction_type`, `status`, `category` (FK nullable), `ai_suggested_category` (FK nullable), `created_at`, `updated_at`
- CRUD DRF views: list, add, edit, delete — all scoped to `request.user`
- Transaction list with:
  - Filters: date range, category, transaction type, status, vendor
  - Sort: date, amount, category
- CSV upload flow:
  1. Upload form accepts a `.csv` file
  2. Backend parses the file expecting headers: `Date`, `Description`, `Amount`, `Vendor`
  3. Negative `Amount` → `transaction_type = expense`; positive → `income`
  4. Duplicate detection: flag rows where `date + amount + description` matches an existing transaction for the user
  5. Preview page shows all rows with duplicate warnings
  6. User confirms → non-duplicate rows are imported

**Test:** Add a transaction manually. Upload a CSV file. Re-upload the same CSV → all rows flagged as duplicates on the preview page. Apply each filter and confirm results. Sort by date, amount, and category.

---

## Step 5 — AI Category Suggestions

**Goal:** Users can get AI-suggested categories for transactions.

**Deliverables:**
- `core/services/ai_service.py`:
  - `suggest_category(description, available_categories)` → returns a category name string or `None`
  - `batch_suggest(transactions, available_categories)` → returns `{transaction_id: category_name}`
  - All exceptions caught gracefully — never crashes the app
- DRF API endpoints:
  - `POST /api/suggest-category/` — single suggestion, called via AJAX from the transaction form
  - `POST /api/batch-suggest/` — batch suggestion, called via AJAX from the CSV preview/import page
- Transaction add/edit form: "Suggest Category" button that calls the single endpoint and pre-fills the category dropdown
- CSV post-import page: "Suggest Categories" button that calls the batch endpoint and populates suggestions for user review and confirmation
- `OPENAI_API_KEY` loaded from `.env`
- If the API is unavailable or returns an error: display a friendly inline message, do not block the form

**Test:** Add a transaction → click "Suggest Category" → verify the category dropdown is pre-filled. Remove the API key from `.env` → confirm a graceful error message appears and the form is still usable. Upload a CSV → use "Suggest Categories" → confirm batch suggestions populate correctly.

---

## Step 6 — Financial Dashboard, Reports, and Vendor Insights

**Goal:** Provide users with actionable insights into their financial activity.

**Deliverables:**
- Dashboard page (`/dashboard/`) showing:
  - **KPI cards:** Total Income, Total Expenses, Net Cash Flow (income − expenses)
  - **Uncategorized alert:** count of transactions with no category, with a link to filter them
  - **Recent transactions:** last 10 transactions in a table
  - **Pie chart:** expense breakdown by category (Chart.js)
  - **Bar/line chart:** monthly income vs expenses (Chart.js)
  - **Bar chart:** top 5 vendors by total spend (Chart.js)
  - **Date range filter:** optional filter applied to all KPI and chart calculations (default: all-time)
- CSV export: export the currently filtered transaction list as a downloadable `.csv` file

**Test:** Upload a set of transactions across multiple categories and vendors. Verify dashboard KPI totals match the raw data. Apply a date filter and confirm totals update. Check that the category pie chart, monthly chart, and vendor chart all reflect the data. Export to CSV and verify the file contents. Confirm uncategorized transactions are flagged with the correct count.

---

# Out of Scope

The following features are noted for potential future development and are not included in this build:

- Invoice management
- Customer management
- Multi-currency support
- Cloud deployment (the project structure supports it via `.env` configuration)
