import csv
import io
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime


DATE_FORMATS = ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%m-%d-%Y']
REQUIRED_HEADERS = {'Date', 'Description', 'Amount', 'Vendor'}


def _normalize_description(text):
    """Lowercase, strip, and collapse repeated whitespace for comparison."""
    return re.sub(r'\s+', ' ', (text or '').strip().lower())


def parse_csv(file):
    """
    Parse an uploaded CSV file with headers: Date, Description, Amount, Vendor.
    Returns a list of row dicts. Each row has an 'errors' list; valid rows have
    'date' (date object), 'amount' (Decimal, always positive), and 'transaction_type'.
    """
    content_bytes = file.read()
    try:
        content = content_bytes.decode('utf-8-sig')  # handles BOM from Excel
    except UnicodeDecodeError:
        content = content_bytes.decode('latin-1')

    reader = csv.DictReader(io.StringIO(content))
    headers = set(reader.fieldnames or [])
    missing = REQUIRED_HEADERS - headers
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")

    rows = []
    for i, row in enumerate(reader, start=2):
        errors = []

        # Parse date
        date_str = row.get('Date', '').strip()
        parsed_date = None
        for fmt in DATE_FORMATS:
            try:
                parsed_date = datetime.strptime(date_str, fmt).date()
                break
            except ValueError:
                continue
        if parsed_date is None:
            errors.append(f'Invalid date "{date_str}" — use YYYY-MM-DD or MM/DD/YYYY')

        # Parse amount
        amount_str = row.get('Amount', '').strip().replace(',', '')
        parsed_amount = None
        transaction_type = None
        try:
            raw = Decimal(amount_str)
            transaction_type = Transaction.EXPENSE if raw < 0 else Transaction.INCOME
            parsed_amount = abs(raw)
        except InvalidOperation:
            errors.append(f'Invalid amount "{amount_str}"')

        description = row.get('Description', '').strip()
        vendor = row.get('Vendor', '').strip()

        if not description:
            errors.append('Description is empty')

        rows.append({
            'row_num': i,
            'date': parsed_date,
            'date_str': date_str,
            'description': description,
            'amount': parsed_amount,
            'amount_str': amount_str,
            'vendor': vendor,
            'transaction_type': transaction_type,
            'errors': errors,
            'is_duplicate': False,
        })

    return rows


def detect_duplicates(rows, user):
    """
    Mark rows as duplicate if:
    - a transaction with the same (date, amount, normalized_description) already
      exists for this user in the database, OR
    - an earlier row in this CSV upload has the same (date, amount, normalized_description).
    """
    from core.models import Transaction

    # Build a set of (date, amount, normalized_description) from the DB
    existing = {
        (date, amount, _normalize_description(description))
        for date, amount, description in
        Transaction.objects.filter(user=user).values_list('date', 'amount', 'description')
    }

    seen_in_csv = set()

    for row in rows:
        if not row['errors'] and row['date'] and row['amount'] is not None:
            key = (row['date'], row['amount'], _normalize_description(row['description']))
            if key in existing or key in seen_in_csv:
                row['is_duplicate'] = True
            else:
                seen_in_csv.add(key)

    return rows


def serialize_rows(rows):
    """Convert parsed rows to JSON-safe dicts for session storage."""
    result = []
    for row in rows:
        result.append({
            'row_num': row['row_num'],
            'date': row['date'].isoformat() if row['date'] else None,
            'date_str': row['date_str'],
            'description': row['description'],
            'amount': str(row['amount']) if row['amount'] is not None else None,
            'amount_str': row['amount_str'],
            'vendor': row['vendor'],
            'transaction_type': row['transaction_type'],
            'errors': row['errors'],
            'is_duplicate': row['is_duplicate'],
        })
    return result


# Needed for the type constants — import lazily to avoid circular import
from core.models import Transaction
