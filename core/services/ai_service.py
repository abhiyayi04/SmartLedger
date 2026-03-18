import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def suggest_category(description, vendor, available_categories, transaction_type=None):
    """
    Suggest a category name for a transaction using OpenAI.

    available_categories: list of dicts with 'name' and 'type' keys.
    transaction_type: optional 'income' or 'expense' — if provided, only categories
                      whose type matches are considered.
    Returns the matched category name string, or None if unavailable/no match.
    """
    if not settings.OPENAI_API_KEY:
        return None

    # Filter to matching type if provided
    if transaction_type:
        candidates = [c for c in available_categories if c.get('type') == transaction_type]
    else:
        candidates = list(available_categories)

    if not candidates:
        return None

    valid_names = {c['name'] for c in candidates}
    cat_list_str = ', '.join(c['name'] for c in candidates)

    prompt = (
        f"Transaction description: {description}\n"
        f"Vendor: {vendor or 'unknown'}\n\n"
        f"Available categories: {cat_list_str}\n\n"
        "Which category fits best? Reply with only the category name from the list above, nothing else."
    )

    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.OPENAI_API_KEY)

        response = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {
                    'role': 'system',
                    'content': (
                        'You are a financial transaction categorization assistant. '
                        'Given a transaction description and vendor, pick the most appropriate '
                        'category from the provided list. Respond with only the category name, '
                        'exactly as it appears in the list.'
                    ),
                },
                {'role': 'user', 'content': prompt},
            ],
            max_tokens=30,
            temperature=0,
        )

        suggested = response.choices[0].message.content.strip()
        return suggested if suggested in valid_names else None

    except Exception as exc:
        logger.warning('AI category suggestion failed: %s', exc)
        return None


def batch_suggest(rows, available_categories):
    """
    Suggest categories for multiple transactions.

    rows: list of dicts with 'index' (str/int), 'description', 'vendor',
          and optionally 'transaction_type'.
    Returns: dict {str(index): category_name} for rows that got a match.
    """
    results = {}
    for row in rows:
        name = suggest_category(
            row.get('description', ''),
            row.get('vendor', ''),
            available_categories,
            transaction_type=row.get('transaction_type'),
        )
        if name:
            results[str(row['index'])] = name
    return results
