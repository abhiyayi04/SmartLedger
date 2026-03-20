import csv
import io
import logging
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime

logger = logging.getLogger(__name__)

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
    filename = getattr(file, 'name', None)
    byte_size = getattr(file, 'size', None)
    logger.info("parse_csv started filename=%s byte_size=%s", filename, byte_size)

    content_bytes = file.read()
    try:
        content = content_bytes.decode('utf-8-sig')  # handles BOM from Excel
        logger.info("parse_csv decoded encoding=utf-8-sig filename=%s", filename)
    except UnicodeDecodeError:
        content = content_bytes.decode('latin-1')
        logger.info("parse_csv decoded encoding=latin-1 filename=%s", filename)

    reader = csv.DictReader(io.StringIO(content))
    headers = set(reader.fieldnames or [])
    logger.info("parse_csv headers=%s filename=%s", sorted(headers), filename)

    missing = REQUIRED_HEADERS - headers
    if missing:
        logger.warning("parse_csv missing required headers=%s filename=%s", sorted(missing), filename)
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

        # Parse amount — supports plain numbers, $-prefixed, and (negative) accounting notation
        amount_str = row.get('Amount', '').strip()
        parsed_amount = None
        transaction_type = None
        try:
            normalized = amount_str.replace(',', '').replace('$', '').strip()
            negative = False
            if normalized.startswith('(') and normalized.endswith(')'):
                normalized = normalized[1:-1].strip()
                negative = True
            raw = Decimal(normalized)
            if negative:
                raw = -raw
            from core.models import Transaction as _Tx
            transaction_type = _Tx.EXPENSE if raw < 0 else _Tx.INCOME
            parsed_amount = abs(raw)
        except InvalidOperation:
            errors.append(f'Invalid amount "{amount_str}"')

        description = row.get('Description', '').strip()
        vendor = row.get('Vendor', '').strip()

        if not description:
            errors.append('Description is empty')

        if errors:
            logger.warning(
                "parse_csv row_error row_num=%s invalid_date=%s invalid_amount=%s empty_description=%s",
                i,
                parsed_date is None,
                parsed_amount is None,
                not description,
            )

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

    error_row_count = sum(1 for r in rows if r['errors'])
    valid_row_count = len(rows) - error_row_count
    logger.info(
        "parse_csv completed filename=%s total_rows=%s valid_rows=%s error_rows=%s",
        filename, len(rows), valid_row_count, error_row_count,
    )
    return rows


def detect_duplicates(rows, user):
    """
    Mark rows as duplicate if:
    - a transaction with the same (date, amount, normalized_description) already
      exists for this user in the database, OR
    - an earlier row in this CSV upload has the same (date, amount, normalized_description).
    """
    from core.models import Transaction

    logger.info("detect_duplicates started user_id=%s input_row_count=%s", user.id, len(rows))

    # Build a set of (date, amount, normalized_description) from the DB
    existing = {
        (date, amount, _normalize_description(description))
        for date, amount, description in
        Transaction.objects.filter(user=user).values_list('date', 'amount', 'description')
    }

    logger.info("detect_duplicates existing_db_transaction_count=%s user_id=%s", len(existing), user.id)

    seen_in_csv = set()
    skipped_count = 0
    db_duplicate_count = 0
    csv_duplicate_count = 0

    for row in rows:
        if not row['errors'] and row['date'] and row['amount'] is not None:
            key = (row['date'], row['amount'], _normalize_description(row['description']))
            if key in existing:
                row['is_duplicate'] = True
                db_duplicate_count += 1
            elif key in seen_in_csv:
                row['is_duplicate'] = True
                csv_duplicate_count += 1
            else:
                seen_in_csv.add(key)
        else:
            skipped_count += 1

    total_duplicates = db_duplicate_count + csv_duplicate_count
    logger.info(
        "detect_duplicates completed user_id=%s skipped_rows=%s db_duplicates=%s csv_duplicates=%s total_duplicates=%s",
        user.id, skipped_count, db_duplicate_count, csv_duplicate_count, total_duplicates,
    )
    return rows

