import datetime
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse

from .models import Category, Transaction
from .forms import TransactionForm
from .services.csv_service import detect_duplicates


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(username='testuser', password='testpass123'):
    return User.objects.create_user(username=username, password=password)


def make_category(user, name='TestCat', cat_type='expense'):
    # Use get_or_create to handle default categories already seeded by signal
    cat, _ = Category.objects.get_or_create(user=user, name=name, defaults={'type': cat_type})
    return cat


def make_transaction(user, **kwargs):
    defaults = dict(
        date='2024-01-15',
        description='Test transaction',
        amount=Decimal('100.00'),
        vendor='ACME',
        transaction_type=Transaction.EXPENSE,
    )
    defaults.update(kwargs)
    return Transaction.objects.create(user=user, **defaults)


# ---------------------------------------------------------------------------
# 1. Duplicate detection
# ---------------------------------------------------------------------------

class DuplicateDetectionTests(TestCase):
    def setUp(self):
        self.user = make_user()
        make_transaction(
            self.user,
            date='2024-01-15',
            description='AWS Invoice',
            amount=Decimal('120.00'),
            vendor='Amazon',
        )

    def _row(self, date='2024-01-15', description='AWS Invoice', amount='120.00', vendor='Amazon'):
        from datetime import date as dt
        import datetime
        return {
            'date': datetime.date.fromisoformat(date),
            'description': description,
            'amount': Decimal(amount),
            'vendor': vendor,
            'transaction_type': Transaction.EXPENSE,
            'errors': [],
            'is_duplicate': False,
            'row_num': 2,
        }

    def test_exact_match_flagged_as_duplicate(self):
        rows = [self._row()]
        result = detect_duplicates(rows, self.user)
        self.assertTrue(result[0]['is_duplicate'])

    def test_different_amount_not_duplicate(self):
        rows = [self._row(amount='999.00')]
        result = detect_duplicates(rows, self.user)
        self.assertFalse(result[0]['is_duplicate'])

    def test_different_description_not_duplicate(self):
        rows = [self._row(description='Something Else')]
        result = detect_duplicates(rows, self.user)
        self.assertFalse(result[0]['is_duplicate'])

    def test_different_date_not_duplicate(self):
        rows = [self._row(date='2024-02-01')]
        result = detect_duplicates(rows, self.user)
        self.assertFalse(result[0]['is_duplicate'])

    def test_error_rows_skipped(self):
        row = self._row()
        row['errors'] = ['Invalid date']
        result = detect_duplicates([row], self.user)
        self.assertFalse(result[0]['is_duplicate'])

    def test_other_users_transactions_not_matched(self):
        # other user has no transactions — self.user's transaction must not bleed across
        other = make_user('other')
        rows = [self._row()]
        result = detect_duplicates(rows, other)
        self.assertFalse(result[0]['is_duplicate'])


# ---------------------------------------------------------------------------
# 2. Financial calculations (dashboard KPIs)
# ---------------------------------------------------------------------------

class FinancialCalculationTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.login(username='testuser', password='testpass123')

    def test_income_total(self):
        make_transaction(self.user, amount=Decimal('1000.00'), transaction_type=Transaction.INCOME)
        make_transaction(self.user, amount=Decimal('500.00'), transaction_type=Transaction.INCOME)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['income_total'], Decimal('1500.00'))

    def test_expense_total(self):
        make_transaction(self.user, amount=Decimal('200.00'), transaction_type=Transaction.EXPENSE)
        make_transaction(self.user, amount=Decimal('300.00'), transaction_type=Transaction.EXPENSE)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['expense_total'], Decimal('500.00'))

    def test_net_cash_flow(self):
        make_transaction(self.user, amount=Decimal('1000.00'), transaction_type=Transaction.INCOME)
        make_transaction(self.user, amount=Decimal('400.00'), transaction_type=Transaction.EXPENSE)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['net_cash_flow'], Decimal('600.00'))

    def test_net_cash_flow_negative(self):
        make_transaction(self.user, amount=Decimal('100.00'), transaction_type=Transaction.INCOME)
        make_transaction(self.user, amount=Decimal('500.00'), transaction_type=Transaction.EXPENSE)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['net_cash_flow'], Decimal('-400.00'))

    def test_zero_when_no_transactions(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['income_total'], Decimal('0'))
        self.assertEqual(response.context['expense_total'], Decimal('0'))
        self.assertEqual(response.context['net_cash_flow'], Decimal('0'))

    def test_date_filter_applied(self):
        make_transaction(self.user, date='2024-01-01', amount=Decimal('500.00'), transaction_type=Transaction.INCOME)
        make_transaction(self.user, date='2024-06-01', amount=Decimal('200.00'), transaction_type=Transaction.INCOME)
        response = self.client.get(reverse('dashboard'), {'date_from': '2024-06-01'})
        self.assertEqual(response.context['income_total'], Decimal('200.00'))

    def test_uncategorized_count(self):
        cat = make_category(self.user)
        make_transaction(self.user, amount=Decimal('100.00'))          # uncategorized
        make_transaction(self.user, amount=Decimal('200.00'), category=cat)  # categorized
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['uncategorized_count'], 1)


# ---------------------------------------------------------------------------
# 3. Category assignment
# ---------------------------------------------------------------------------

class CategoryAssignmentTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.login(username='testuser', password='testpass123')
        self.cat = make_category(self.user, name='CustomCat')

    def test_assign_category_via_edit(self):
        t = make_transaction(self.user)
        self.assertIsNone(t.category)
        self.client.post(reverse('transaction_edit', args=[t.pk]), {
            'date': '2024-01-15',
            'description': 'Test transaction',
            'amount': '100.00',
            'vendor': 'ACME',
            'transaction_type': Transaction.EXPENSE,
            'category': self.cat.pk,
        })
        t.refresh_from_db()
        self.assertEqual(t.category, self.cat)

    def test_accept_ai_suggestion(self):
        t = make_transaction(self.user)
        t.ai_suggested_category = self.cat
        t.save()
        self.client.post(reverse('api_accept_suggestion', args=[t.pk]),
                         content_type='application/json')
        t.refresh_from_db()
        self.assertEqual(t.category, self.cat)

    def test_accept_suggestion_does_not_overwrite_existing_category(self):
        other_cat = make_category(self.user, name='AnotherCat')
        t = make_transaction(self.user, category=other_cat)
        t.ai_suggested_category = self.cat
        t.save()
        response = self.client.post(reverse('api_accept_suggestion', args=[t.pk]),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 400)
        t.refresh_from_db()
        self.assertEqual(t.category, other_cat)  # unchanged

    def test_category_scoped_to_user(self):
        other = make_user('other')
        other_cat = make_category(other, name='Travel')  # same name, different user
        # other user's category should not appear for self.user
        self.assertNotIn(other_cat, Category.objects.filter(user=self.user))

    def test_default_categories_seeded_on_registration(self):
        new_user = User.objects.create_user('newuser', password='pass12345!')
        cats = Category.objects.filter(user=new_user)
        self.assertEqual(cats.count(), 8)
        names = set(cats.values_list('name', flat=True))
        self.assertIn('Revenue', names)
        self.assertIn('Software', names)
        self.assertIn('Travel', names)


# ---------------------------------------------------------------------------
# 4. TransactionForm domain integrity
# ---------------------------------------------------------------------------

class TransactionFormValidationTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.other = make_user('other')
        # Signal seeds default categories; use get_or_create to avoid duplicate-key errors
        self.income_cat, _ = Category.objects.get_or_create(user=self.user, name='Revenue', defaults={'type': Category.INCOME})
        self.expense_cat, _ = Category.objects.get_or_create(user=self.user, name='Software', defaults={'type': Category.EXPENSE})
        self.other_cat, _ = Category.objects.get_or_create(user=self.other, name='Other', defaults={'type': Category.EXPENSE})

    def _post_data(self, **overrides):
        data = {
            'date': '2024-01-15',
            'description': 'Test',
            'amount': '100.00',
            'vendor': 'ACME',
            'transaction_type': Transaction.EXPENSE,
            'category': self.expense_cat.pk,
        }
        data.update(overrides)
        return data

    def test_matching_type_is_valid(self):
        form = TransactionForm(self._post_data(), user=self.user)
        self.assertTrue(form.is_valid(), form.errors)

    def test_mismatched_type_invalid(self):
        """Income category chosen for an expense transaction — should fail."""
        form = TransactionForm(
            self._post_data(transaction_type=Transaction.INCOME, category=self.expense_cat.pk),
            user=self.user,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('category', form.errors)

    def test_other_users_category_invalid(self):
        """Category belonging to a different user should be rejected."""
        form = TransactionForm(
            self._post_data(category=self.other_cat.pk),
            user=self.user,
        )
        # ModelChoiceField won't even include other_cat in the queryset,
        # so it raises an invalid-choice validation error.
        self.assertFalse(form.is_valid())

    def test_no_category_is_valid(self):
        """Category is optional — omitting it must be accepted."""
        form = TransactionForm(self._post_data(category=''), user=self.user)
        self.assertTrue(form.is_valid(), form.errors)


# ---------------------------------------------------------------------------
# 5. Transaction model-level clean() validation
# ---------------------------------------------------------------------------

class TransactionModelValidationTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.other = make_user('other')
        self.expense_cat, _ = Category.objects.get_or_create(user=self.user, name='Software', defaults={'type': Category.EXPENSE})
        self.income_cat, _ = Category.objects.get_or_create(user=self.user, name='Revenue', defaults={'type': Category.INCOME})
        self.other_cat, _ = Category.objects.get_or_create(user=self.other, name='Other', defaults={'type': Category.EXPENSE})

    def _txn(self, **kwargs):
        defaults = dict(
            date='2024-01-15',
            description='Test',
            amount=Decimal('50.00'),
            transaction_type=Transaction.EXPENSE,
        )
        defaults.update(kwargs)
        t = Transaction(user=self.user, **defaults)
        return t

    def test_matching_category_passes(self):
        t = self._txn(category=self.expense_cat)
        t.clean()  # should not raise

    def test_mismatched_category_type_raises(self):
        t = self._txn(category=self.income_cat)
        with self.assertRaises(ValidationError) as cm:
            t.clean()
        self.assertIn('category', cm.exception.message_dict)

    def test_other_users_category_raises(self):
        t = self._txn(category=self.other_cat)
        with self.assertRaises(ValidationError) as cm:
            t.clean()
        self.assertIn('category', cm.exception.message_dict)

    def test_mismatched_ai_suggested_category_raises(self):
        t = self._txn(ai_suggested_category=self.income_cat)
        with self.assertRaises(ValidationError) as cm:
            t.clean()
        self.assertIn('ai_suggested_category', cm.exception.message_dict)

    def test_other_users_ai_suggested_category_raises(self):
        t = self._txn(ai_suggested_category=self.other_cat)
        with self.assertRaises(ValidationError) as cm:
            t.clean()
        self.assertIn('ai_suggested_category', cm.exception.message_dict)


# ---------------------------------------------------------------------------
# 6. Duplicate detection — normalization and intra-CSV detection
# ---------------------------------------------------------------------------

class DuplicateDetectionNormalizationTests(TestCase):
    def setUp(self):
        self.user = make_user()
        make_transaction(
            self.user,
            date='2024-01-15',
            description='AWS  Invoice',   # double space in DB
            amount=Decimal('120.00'),
        )

    def _row(self, description, date='2024-01-15', amount='120.00'):
        return {
            'date': datetime.date.fromisoformat(date),
            'description': description,
            'amount': Decimal(amount),
            'transaction_type': Transaction.EXPENSE,
            'errors': [],
            'is_duplicate': False,
            'row_num': 2,
        }

    def test_normalized_match_flagged(self):
        """Single-space vs double-space description should still match."""
        rows = [self._row('AWS Invoice')]  # single space
        result = detect_duplicates(rows, self.user)
        self.assertTrue(result[0]['is_duplicate'])

    def test_case_insensitive_match(self):
        rows = [self._row('aws invoice')]
        result = detect_duplicates(rows, self.user)
        self.assertTrue(result[0]['is_duplicate'])

    def test_intra_csv_first_row_not_duplicate(self):
        rows = [
            self._row('New Transaction'),
            self._row('New Transaction'),
        ]
        result = detect_duplicates(rows, self.user)
        self.assertFalse(result[0]['is_duplicate'])  # first occurrence is new
        self.assertTrue(result[1]['is_duplicate'])   # second is intra-CSV duplicate

    def test_intra_csv_different_amounts_not_duplicate(self):
        rows = [
            self._row('New Transaction', amount='50.00'),
            self._row('New Transaction', amount='75.00'),
        ]
        result = detect_duplicates(rows, self.user)
        self.assertFalse(result[0]['is_duplicate'])
        self.assertFalse(result[1]['is_duplicate'])
