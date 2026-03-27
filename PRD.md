# SmartLedger Product Requirements Document (PRD)

## Product Overview

College students often struggle to track and understand their spending habits. While bank statements provide raw transaction data, they lack structured insights, categorization, and meaningful analysis.

Most existing tools are either overly complex financial software or basic trackers that do not provide actionable insights. Students need a lightweight platform that allows them to:

- Import and manage financial transactions
- Automatically categorize expenses
- Identify recurring subscriptions
- Analyze major vendors and spending trends
- Query and filter transactions easily

The Student Expense Intelligence Dashboard addresses this gap by providing a simple, centralized platform where students can upload transaction data, manage expenses, and gain insights into their spending behavior.

---

# Technology Solution Statement

The system will be implemented as a full-stack financial analytics web application that enables users to ingest, manage, and analyze transaction data.

The platform will expose REST APIs for transaction ingestion, categorization, subscription detection, and analytics. Users will interact with the system through a web-based dashboard that displays insights such as category distribution, vendor spending, and trends over time.

The backend will process uploaded CSV data, apply categorization and subscription detection logic, store records in a relational database, and provide endpoints for querying and filtering data.

The architecture is designed to demonstrate strong backend engineering, structured database design, and interactive frontend visualization while remaining simple and practical.

---

# Business Functions and Functional Requirements

SmartLedger will support the following core business functions.

---

## 1. User Authentication and Account Management

### Description

The system must allow users to securely manage their personal financial data.

### Functional Requirements

The system shall:

- Allow users to register accounts
- Allow users to log in securely
- Allow users to log out
- Ensure all financial data is scoped per user
- Store passwords securely using hashing

---

## 2. Transaction Management

### Description

Users must be able to import and manage their financial transactions.

### Functional Requirements

The system shall:

- Allow users to upload transaction data via CSV files
- Parse CSV files and extract transaction records
- Validate required fields before storing
- Store transaction data including:
  - date
  - description
  - vendor
  - amount
  - category
- Allow users to view transactions in a table
- Allow users to edit and delete transactions
- Display transactions in a paginated format
- Detect basic duplicate transactions (date + amount + description)

---

## 3. Automatic Expense Categorization

### Description

Transactions should be categorized automatically to provide meaningful insights, but must ask the user first to either accept or deny the category suggestion.

### Functional Requirements

The system shall:

- Automatically assign categories based on vendor or keywords
- Support default categories such as:
  - Revenue (income)
  - Rent
  - Food & Dining
  - Groceries
  - Transportation
  - Entertainment
  - Shopping
  - Utilities
  - Subscriptions
  - Miscellaneous
- Allow users to manually override categories
- Store categories in the database

---

## 4. Subscription Identification

### Description

The system must detect recurring expenses that are likely subscriptions.

### Functional Requirements

The system shall:

- Identify repeated transactions from the same vendor
- Detect recurring patterns (e.g., monthly charges)
- Flag transactions as subscriptions
- Display detected subscriptions in the dashboard

### Detection Algorithm

The system shall automatically detect subscriptions using the following logic:

- Group expense transactions by normalized vendor name.
- For each vendor group with 2 or more transactions, compare consecutive transaction dates.
- If any consecutive gap falls within 20–45 days, all transactions from that vendor are flagged as `is_subscription = True`.
- Detection runs automatically after every CSV import.
- Users can also trigger detection on-demand via a "Detect Subscriptions" action on the transactions page.
- The `is_subscription` flag is stored on the Transaction record and can be used as a filter.

### Example

- Netflix monthly charge
- Spotify subscription
- Gym membership

---

## 5. Dashboard and Financial Insights

### Description

The dashboard serves as the central interface for users to view and understand their financial data. It consolidates key insights such as vendor spending, category distribution, subscriptions, and spending trends into a single, easy-to-use view.

### Functional Requirements

The system shall:

- Display total spending for a selected time period
- Display spending breakdown by category
- Display monthly spending trends over time
- Normalize vendor names (lowercase, trimmed) for accurate grouping
- Calculate and display top vendors by total spending
- Identify and display likely subscription-based transactions
- Display recent transactions
- Allow users to filter dashboard insights by date range

---

## 6. Transaction Search and Filtering

### Description

Users must be able to efficiently query and filter their transactions.

### Functional Requirements

Users shall be able to filter transactions by:

- Category
- Vendor (partial match)
- Date range
- Amount range
- Subscription flag

Example queries:

- Show transactions where category = Travel
- Show transactions greater than $100
- Show transactions from last month
- Support sorting by date and amount
- Provide fast query responses

---

## 7. Date Input Format

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
MySQL Database
    ↓
External AI API (OpenAI)
    ↓
AWS Infrastructure
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

- MySQL

Primary entities:

- User:
  - id
  - email
  - password

- Transaction:
  - id
  - user_id
  - date
  - description
  - vendor
  - normalized_vendor (auto-derived: lowercase, whitespace-collapsed, indexed for grouping)
  - amount (always stored as positive; sign indicated by transaction_type)
  - transaction_type (income or expense)
  - category (FK to Category, nullable)
  - ai_suggested_category (FK to Category, nullable — stores pending AI suggestion)
  - is_subscription (boolean, set by detection algorithm)

- Category:
  - id
  - name
  - type (income or expense — must match transaction_type of linked transactions)

- ImportHistory:
  - id
  - user_id
  - filename
  - uploaded_at
  - total_rows
  - imported_count
  - duplicate_count
  - invalid_count
  - error_details (JSON — list of row-level validation errors)

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

- Unit tests must be written for core business logic: duplicate detection, financial calculations, category assignment, form validation, vendor normalization, import history, and access control.
- Integration tests must cover: CSV export filter behavior, CSV upload creates ImportHistory, safe redirect validation, batch accept behavior.
- Django's built-in test framework (`python manage.py test`) is used for all automated tests.
- Each feature step should include a manual QA checklist confirming all functional requirements work end-to-end before moving to the next step.

---

# Deployment

- **Primary target:** Local development environment.
- The application must run locally using `python manage.py runserver` with a locally hosted database.
- The project should be structured to support future deployment to a cloud platform (e.g., Railway, Heroku, or a VPS) with minimal configuration changes.
- Environment-specific settings (database credentials, API keys) must be stored in environment variables or a `.env` file and never committed to source control.
- The system will be deployed on AWS in future.
  - Responsibilities:

    - Host backend application (EC2 / Elastic Beanstalk)
    - Host frontend
    - Manage MySQL database (RDS or local instance)
    - Handle deployment and scaling

---

# Development Roadmap

Each step below represents a discrete, vertically complete feature slice — from models and backend logic through to UI and tests.

| Step | Feature | Status |
|------|---------|--------|
| 1 | **Project Setup & User Authentication** — Django project scaffolding, user registration, login/logout, password hashing, per-user data scoping | ✅ Done |
| 2 | **Transaction Management** — Transaction model, add/edit/delete, CSV upload and parsing, duplicate detection, paginated list, CSV export | ✅ Done |
| 3 | **Automatic Expense Categorization** — Category model with income/expense types, default categories seeded on registration, AI suggestions via OpenAI GPT-4o-mini, per-row and batch accept/deny flow, manual override | ✅ Done |
| 4 | **Import History** — ImportHistory model, track every CSV upload with row counts and error details, import history list and detail views | ✅ Done |
| 5 | **Dashboard & Financial Insights** — Total spending, category breakdown (pie chart), monthly trends (bar chart), top vendors, recent transactions, date range filtering | ✅ Done |
| 6 | **Transaction Search & Filtering** — Filter by category, vendor, date range, amount range, transaction type, subscription flag; sort by date and amount | ✅ Done |
| 7 | **Date Input Standardization** — `DateTextInput` widget enforcing YYYY-MM-DD format across all date fields; inline validation errors | ✅ Done |
| 8 | **Subscription Identification** — `is_subscription` field, auto-detection on CSV import, on-demand detect action, subscription badge in transaction list, subscription filter, subscriptions card on dashboard | 🔄 In Progress |