import csv as csv_module
import datetime
import io
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse

from .models import Category, ImportHistory, Transaction
from .forms import DashboardFilterForm, TransactionFilterForm, TransactionForm
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


# ---------------------------------------------------------------------------
# 7. Typed date input validation (YYYY-MM-DD only)
# ---------------------------------------------------------------------------

class TypedDateValidationTests(TestCase):
    """All date fields must accept YYYY-MM-DD and reject other formats."""

    def test_transaction_form_accepts_yyyy_mm_dd(self):
        user = make_user()
        form = TransactionForm({
            'date': '2024-03-15',
            'description': 'Test',
            'amount': '50.00',
            'transaction_type': Transaction.EXPENSE,
        }, user=user)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['date'], datetime.date(2024, 3, 15))

    def test_transaction_form_rejects_us_slash_format(self):
        user = make_user()
        form = TransactionForm({
            'date': '03/15/2024',
            'description': 'Test',
            'amount': '50.00',
            'transaction_type': Transaction.EXPENSE,
        }, user=user)
        self.assertFalse(form.is_valid())
        self.assertIn('date', form.errors)

    def test_transaction_form_rejects_ambiguous_format(self):
        user = make_user()
        form = TransactionForm({
            'date': '15-03-2024',
            'description': 'Test',
            'amount': '50.00',
            'transaction_type': Transaction.EXPENSE,
        }, user=user)
        self.assertFalse(form.is_valid())
        self.assertIn('date', form.errors)

    def test_dashboard_filter_accepts_yyyy_mm_dd(self):
        form = DashboardFilterForm({'date_from': '2024-01-01', 'date_to': '2024-12-31'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['date_from'], datetime.date(2024, 1, 1))
        self.assertEqual(form.cleaned_data['date_to'], datetime.date(2024, 12, 31))

    def test_dashboard_filter_rejects_slash_format(self):
        form = DashboardFilterForm({'date_from': '01/01/2024'})
        self.assertFalse(form.is_valid())
        self.assertIn('date_from', form.errors)

    def test_transaction_filter_accepts_yyyy_mm_dd(self):
        user = make_user()
        form = TransactionFilterForm({'date_from': '2024-06-01'}, user=user)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['date_from'], datetime.date(2024, 6, 1))

    def test_transaction_filter_rejects_slash_format(self):
        user = make_user()
        form = TransactionFilterForm({'date_from': '06/01/2024'}, user=user)
        self.assertFalse(form.is_valid())
        self.assertIn('date_from', form.errors)

    def test_dashboard_filtering_works_with_typed_dates(self):
        """Dashboard view still filters correctly when dates are typed in YYYY-MM-DD."""
        user = make_user()
        client = self.client
        client.login(username='testuser', password='testpass123')
        make_transaction(user, date='2024-01-01', amount=Decimal('100.00'), transaction_type=Transaction.INCOME)
        make_transaction(user, date='2024-06-01', amount=Decimal('300.00'), transaction_type=Transaction.INCOME)
        response = client.get(reverse('dashboard'), {'date_from': '2024-06-01'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['income_total'], Decimal('300.00'))

    def test_transaction_list_filtering_works_with_typed_dates(self):
        """Transaction list view still filters correctly when dates are typed in YYYY-MM-DD."""
        user = make_user()
        client = self.client
        client.login(username='testuser', password='testpass123')
        make_transaction(user, date='2024-01-01', amount=Decimal('50.00'))
        make_transaction(user, date='2024-09-01', amount=Decimal('200.00'))
        response = client.get(reverse('transaction_list'), {'date_from': '2024-09-01'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 1)


# ---------------------------------------------------------------------------
# 8. Batch Accept AI Suggestions
# ---------------------------------------------------------------------------

class BatchAcceptSuggestionsTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.login(username='testuser', password='testpass123')
        self.cat = make_category(self.user, name='CustomCat')

    def test_batch_accept_sets_category_from_suggestion(self):
        t = make_transaction(self.user)
        t.ai_suggested_category = self.cat
        t.save()
        self.client.post(reverse('batch_accept_suggestions'), {'back': '/transactions/'})
        t.refresh_from_db()
        self.assertEqual(t.category, self.cat)

    def test_batch_accept_does_not_overwrite_existing_category(self):
        other_cat = make_category(self.user, name='OtherCat')
        t = make_transaction(self.user, category=other_cat)
        t.ai_suggested_category = self.cat
        t.save()
        self.client.post(reverse('batch_accept_suggestions'), {'back': '/transactions/'})
        t.refresh_from_db()
        self.assertEqual(t.category, other_cat)  # must be unchanged

    def test_batch_accept_skips_transactions_without_suggestion(self):
        t = make_transaction(self.user)  # no ai_suggested_category
        self.client.post(reverse('batch_accept_suggestions'), {'back': '/transactions/'})
        t.refresh_from_db()
        self.assertIsNone(t.category)

    def test_batch_accept_only_affects_current_user(self):
        other = make_user('other2')
        other_cat = make_category(other, name='OtherCat2')
        t_other = make_transaction(other)
        t_other.ai_suggested_category = other_cat
        t_other.save()
        self.client.post(reverse('batch_accept_suggestions'), {'back': '/transactions/'})
        t_other.refresh_from_db()
        self.assertIsNone(t_other.category)  # other user's transaction untouched

    def test_batch_accept_updates_multiple_eligible_transactions(self):
        t1 = make_transaction(self.user, description='Tx 1')
        t2 = make_transaction(self.user, description='Tx 2')
        t1.ai_suggested_category = self.cat
        t2.ai_suggested_category = self.cat
        t1.save()
        t2.save()
        response = self.client.post(
            reverse('batch_accept_suggestions'), {'back': '/transactions/'}, follow=True
        )
        t1.refresh_from_db()
        t2.refresh_from_db()
        self.assertEqual(t1.category, self.cat)
        self.assertEqual(t2.category, self.cat)
        self.assertContains(response, 'Accepted 2 AI suggestions')

    def test_batch_accept_shows_info_when_nothing_to_accept(self):
        response = self.client.post(
            reverse('batch_accept_suggestions'), {'back': '/transactions/'}, follow=True
        )
        self.assertContains(response, 'No pending AI suggestions')

    def test_batch_accept_redirects_to_back_url(self):
        response = self.client.post(
            reverse('batch_accept_suggestions'), {'back': '/transactions/?date_from=2024-01-01'}
        )
        self.assertRedirects(response, '/transactions/?date_from=2024-01-01')

    def test_batch_accept_get_redirects(self):
        response = self.client.get(reverse('batch_accept_suggestions'))
        self.assertRedirects(response, reverse('transaction_list'))


# ---------------------------------------------------------------------------
# 9. TransactionFilterForm cross-field validation
# ---------------------------------------------------------------------------

class TransactionFilterFormCrossFieldTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_date_range_reversed_is_invalid(self):
        form = TransactionFilterForm(
            {'date_from': '2024-12-31', 'date_to': '2024-01-01'}, user=self.user
        )
        self.assertFalse(form.is_valid())

    def test_date_range_same_day_is_valid(self):
        form = TransactionFilterForm(
            {'date_from': '2024-06-15', 'date_to': '2024-06-15'}, user=self.user
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_date_range_ascending_is_valid(self):
        form = TransactionFilterForm(
            {'date_from': '2024-01-01', 'date_to': '2024-12-31'}, user=self.user
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_amount_range_reversed_is_invalid(self):
        form = TransactionFilterForm({'amount_min': '200', 'amount_max': '50'}, user=self.user)
        self.assertFalse(form.is_valid())

    def test_amount_range_equal_is_valid(self):
        form = TransactionFilterForm({'amount_min': '100', 'amount_max': '100'}, user=self.user)
        self.assertTrue(form.is_valid(), form.errors)

    def test_amount_range_ascending_is_valid(self):
        form = TransactionFilterForm({'amount_min': '10', 'amount_max': '500'}, user=self.user)
        self.assertTrue(form.is_valid(), form.errors)

    def test_only_date_from_provided_is_valid(self):
        """Single bound with no corresponding other bound must not raise."""
        form = TransactionFilterForm({'date_from': '2024-01-01'}, user=self.user)
        self.assertTrue(form.is_valid(), form.errors)

    def test_only_amount_max_provided_is_valid(self):
        form = TransactionFilterForm({'amount_max': '500'}, user=self.user)
        self.assertTrue(form.is_valid(), form.errors)


# ---------------------------------------------------------------------------
# 10. CSV export respects filters
# ---------------------------------------------------------------------------

class CSVExportFilterTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.login(username='testuser', password='testpass123')

    def _parse_csv(self, response):
        content = response.content.decode('utf-8')
        return list(csv_module.DictReader(io.StringIO(content)))

    def test_export_respects_date_from(self):
        make_transaction(self.user, date='2024-01-01', description='Old tx')
        make_transaction(self.user, date='2024-09-01', description='New tx')
        response = self.client.get(reverse('export_csv'), {'date_from': '2024-09-01'})
        rows = self._parse_csv(response)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['Description'], 'New tx')

    def test_export_respects_date_to(self):
        make_transaction(self.user, date='2024-01-01', description='Old tx')
        make_transaction(self.user, date='2024-09-01', description='New tx')
        response = self.client.get(reverse('export_csv'), {'date_to': '2024-03-01'})
        rows = self._parse_csv(response)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['Description'], 'Old tx')

    def test_export_respects_type_filter(self):
        make_transaction(self.user, description='Income tx', transaction_type=Transaction.INCOME)
        make_transaction(self.user, description='Expense tx', transaction_type=Transaction.EXPENSE)
        response = self.client.get(reverse('export_csv'), {'type': 'income'})
        rows = self._parse_csv(response)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['Description'], 'Income tx')

    def test_export_respects_vendor_filter(self):
        make_transaction(self.user, description='Tx A', vendor='Amazon')
        make_transaction(self.user, description='Tx B', vendor='Shopify')
        response = self.client.get(reverse('export_csv'), {'vendor': 'amazon'})
        rows = self._parse_csv(response)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['Description'], 'Tx A')

    def test_export_respects_amount_range(self):
        make_transaction(self.user, description='Small', amount=Decimal('10.00'))
        make_transaction(self.user, description='Medium', amount=Decimal('50.00'))
        make_transaction(self.user, description='Large', amount=Decimal('200.00'))
        response = self.client.get(
            reverse('export_csv'), {'amount_min': '20', 'amount_max': '100'}
        )
        rows = self._parse_csv(response)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['Description'], 'Medium')

    def test_export_respects_category_filter(self):
        cat = make_category(self.user, name='CatA')
        make_transaction(self.user, description='Categorized', category=cat)
        make_transaction(self.user, description='Uncategorized')
        response = self.client.get(reverse('export_csv'), {'category': cat.pk})
        rows = self._parse_csv(response)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['Description'], 'Categorized')

    def test_export_with_no_filters_returns_all_user_transactions(self):
        make_transaction(self.user, description='Tx 1')
        make_transaction(self.user, description='Tx 2')
        response = self.client.get(reverse('export_csv'))
        rows = self._parse_csv(response)
        self.assertEqual(len(rows), 2)

    def test_export_does_not_include_other_users_transactions(self):
        other = make_user('csvother')
        make_transaction(self.user, description='Mine')
        make_transaction(other, description='Theirs')
        response = self.client.get(reverse('export_csv'))
        rows = self._parse_csv(response)
        descriptions = [r['Description'] for r in rows]
        self.assertIn('Mine', descriptions)
        self.assertNotIn('Theirs', descriptions)


# ---------------------------------------------------------------------------
# 11. ImportHistory creation and contents
# ---------------------------------------------------------------------------

def _make_csv_file(content, filename='test.csv'):
    return SimpleUploadedFile(filename, content.encode('utf-8'), content_type='text/csv')


class ImportHistoryTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.login(username='testuser', password='testpass123')

    def _upload(self, csv_content, filename='test.csv'):
        f = _make_csv_file(csv_content, filename)
        return self.client.post(reverse('csv_upload'), {'file': f})

    def test_upload_creates_import_history_record(self):
        self._upload("Date,Description,Amount,Vendor\n2024-01-15,Test tx,-100.00,Amazon\n")
        self.assertEqual(ImportHistory.objects.filter(user=self.user).count(), 1)

    def test_import_history_stores_filename(self):
        self._upload(
            "Date,Description,Amount,Vendor\n2024-01-15,Test tx,-100.00,Amazon\n",
            filename='mydata.csv',
        )
        h = ImportHistory.objects.get(user=self.user)
        self.assertEqual(h.filename, 'mydata.csv')

    def test_import_history_total_rows(self):
        csv_content = (
            "Date,Description,Amount,Vendor\n"
            "2024-01-15,Row 1,-50.00,A\n"
            "2024-01-16,Row 2,-80.00,B\n"
        )
        self._upload(csv_content)
        h = ImportHistory.objects.get(user=self.user)
        self.assertEqual(h.total_rows, 2)

    def test_import_history_imported_count(self):
        csv_content = (
            "Date,Description,Amount,Vendor\n"
            "2024-01-15,Valid tx,-50.00,Amazon\n"
        )
        self._upload(csv_content)
        h = ImportHistory.objects.get(user=self.user)
        self.assertEqual(h.imported_count, 1)

    def test_import_history_invalid_count(self):
        csv_content = (
            "Date,Description,Amount,Vendor\n"
            "2024-01-15,Valid tx,-50.00,Amazon\n"
            "bad-date,Invalid tx,100.00,Vendor\n"
        )
        self._upload(csv_content)
        h = ImportHistory.objects.get(user=self.user)
        self.assertEqual(h.total_rows, 2)
        self.assertEqual(h.imported_count, 1)
        self.assertEqual(h.invalid_count, 1)

    def test_import_history_duplicate_count(self):
        # Pre-seed a transaction that will match the CSV row
        make_transaction(
            self.user, date='2024-01-15', description='Existing tx',
            amount=Decimal('50.00'), transaction_type=Transaction.EXPENSE,
        )
        csv_content = (
            "Date,Description,Amount,Vendor\n"
            "2024-01-15,Existing tx,-50.00,Amazon\n"   # duplicate
            "2024-02-01,New tx,-80.00,Shop\n"          # new
        )
        self._upload(csv_content)
        h = ImportHistory.objects.get(user=self.user)
        self.assertEqual(h.duplicate_count, 1)
        self.assertEqual(h.imported_count, 1)

    def test_import_history_error_details_stored(self):
        csv_content = (
            "Date,Description,Amount,Vendor\n"
            "bad-date,Invalid tx,100.00,Vendor\n"   # row 2: bad date
        )
        self._upload(csv_content)
        h = ImportHistory.objects.get(user=self.user)
        self.assertEqual(len(h.error_details), 1)
        self.assertEqual(h.error_details[0]['row_num'], 2)
        self.assertTrue(len(h.error_details[0]['errors']) > 0)


# ---------------------------------------------------------------------------
# 12. Vendor normalization
# ---------------------------------------------------------------------------

class VendorNormalizationTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.login(username='testuser', password='testpass123')

    def test_manual_creation_normalizes_whitespace_and_case(self):
        t = make_transaction(self.user, vendor='  Amazon  ')
        self.assertEqual(t.normalized_vendor, 'amazon')

    def test_all_caps_vendor_normalized(self):
        t = make_transaction(self.user, vendor='WALMART')
        self.assertEqual(t.normalized_vendor, 'walmart')

    def test_internal_extra_whitespace_collapsed(self):
        t = make_transaction(self.user, vendor='Amazon  Prime')
        self.assertEqual(t.normalized_vendor, 'amazon prime')

    def test_edit_updates_normalized_vendor(self):
        t = make_transaction(self.user, vendor='Old Vendor')
        self.client.post(reverse('transaction_edit', args=[t.pk]), {
            'date': '2024-01-15',
            'description': 'Test transaction',
            'amount': '100.00',
            'vendor': '  NEW VENDOR  ',
            'transaction_type': Transaction.EXPENSE,
        })
        t.refresh_from_db()
        self.assertEqual(t.normalized_vendor, 'new vendor')

    def test_csv_import_normalizes_vendor(self):
        f = _make_csv_file(
            "Date,Description,Amount,Vendor\n2024-01-15,Test tx,-100.00,  AMAZON  \n"
        )
        self.client.post(reverse('csv_upload'), {'file': f})
        t = Transaction.objects.filter(user=self.user).first()
        self.assertEqual(t.normalized_vendor, 'amazon')

    def test_vendor_variants_aggregate_as_one_group_in_dashboard(self):
        """Dashboard top-vendors chart groups by normalized_vendor, so variants must merge."""
        make_transaction(
            self.user, vendor='Amazon', amount=Decimal('100.00'),
            transaction_type=Transaction.EXPENSE,
        )
        make_transaction(
            self.user, vendor='AMAZON', amount=Decimal('50.00'),
            transaction_type=Transaction.EXPENSE,
        )
        make_transaction(
            self.user, vendor=' Amazon ', amount=Decimal('25.00'),
            transaction_type=Transaction.EXPENSE,
        )
        response = self.client.get(reverse('dashboard'))
        vendors = response.context['chart_data']['vendors']
        self.assertEqual(len(vendors['labels']), 1)
        self.assertEqual(vendors['labels'][0], 'amazon')
        self.assertAlmostEqual(vendors['data'][0], 175.0)


# ---------------------------------------------------------------------------
# 14. Import history access control
# ---------------------------------------------------------------------------

def _make_import_history(user, filename='import.csv'):
    return ImportHistory.objects.create(
        user=user, filename=filename, total_rows=1, imported_count=1,
    )


class ImportHistoryAccessControlTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.other = make_user('other_ihac')
        self.client.login(username='testuser', password='testpass123')

    def test_list_shows_only_own_history(self):
        own = _make_import_history(self.user, 'mine.csv')
        other = _make_import_history(self.other, 'theirs.csv')
        response = self.client.get(reverse('import_history_list'))
        self.assertEqual(response.status_code, 200)
        listed = list(response.context['history'])
        self.assertIn(own, listed)
        self.assertNotIn(other, listed)

    def test_detail_accessible_for_own_history(self):
        own = _make_import_history(self.user)
        response = self.client.get(reverse('import_history_detail', args=[own.pk]))
        self.assertEqual(response.status_code, 200)

    def test_detail_returns_404_for_other_users_history(self):
        other = _make_import_history(self.other)
        response = self.client.get(reverse('import_history_detail', args=[other.pk]))
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# 15. Safe back redirect handling
# ---------------------------------------------------------------------------

class SafeBackRedirectTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.login(username='testuser', password='testpass123')

    def _edit_post(self, t, extra=None):
        data = {
            'date': '2024-01-15',
            'description': 'Test transaction',
            'amount': '100.00',
            'vendor': 'ACME',
            'transaction_type': Transaction.EXPENSE,
        }
        if extra:
            data.update(extra)
        return self.client.post(reverse('transaction_edit', args=[t.pk]), data)

    def test_valid_local_back_used_after_edit(self):
        t = make_transaction(self.user)
        response = self._edit_post(t, {'back': '/transactions/?date_from=2024-01-01'})
        self.assertRedirects(response, '/transactions/?date_from=2024-01-01')

    def test_external_back_rejected_after_edit(self):
        t = make_transaction(self.user)
        response = self._edit_post(t, {'back': 'https://evil.com'})
        self.assertRedirects(response, reverse('transaction_list'))

    def test_empty_back_falls_back_to_list_after_edit(self):
        t = make_transaction(self.user)
        response = self._edit_post(t)
        self.assertRedirects(response, reverse('transaction_list'))

    def test_valid_local_back_used_after_delete(self):
        t = make_transaction(self.user)
        response = self.client.post(
            reverse('transaction_delete', args=[t.pk]), {'back': '/transactions/'}
        )
        self.assertRedirects(response, '/transactions/')

    def test_external_back_rejected_after_delete(self):
        t = make_transaction(self.user)
        response = self.client.post(
            reverse('transaction_delete', args=[t.pk]), {'back': 'http://evil.com'}
        )
        self.assertRedirects(response, reverse('transaction_list'))

    def test_empty_back_falls_back_to_list_after_delete(self):
        t = make_transaction(self.user)
        response = self.client.post(reverse('transaction_delete', args=[t.pk]))
        self.assertRedirects(response, reverse('transaction_list'))

    def test_protocol_relative_url_rejected(self):
        """//evil.com does not start with '/' + alpha — _safe_back must reject it."""
        t = make_transaction(self.user)
        response = self._edit_post(t, {'back': '//evil.com/steal'})
        self.assertRedirects(response, reverse('transaction_list'))


# ---------------------------------------------------------------------------
# 16. Optional: same-name categories across users, stronger normalization
# ---------------------------------------------------------------------------

class MiscEdgeCaseTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.other = make_user('misc_other')

    def test_two_users_can_share_category_name(self):
        """unique_together is [user, name], so two users can have the same category name."""
        cat1 = make_category(self.user, name='Travel', cat_type='expense')
        cat2 = make_category(self.other, name='Travel', cat_type='expense')
        self.assertNotEqual(cat1.pk, cat2.pk)
        self.assertEqual(cat1.name, cat2.name)

    def test_duplicate_detection_with_both_spacing_and_casing_difference(self):
        """A DB description with extra spaces AND different case must still match the CSV row."""
        make_transaction(
            self.user,
            date='2024-03-10',
            description='  AWS  INVOICE  ',   # extra spaces + uppercase in DB
            amount=Decimal('99.00'),
        )
        row = {
            'date': datetime.date(2024, 3, 10),
            'description': 'aws invoice',      # single-spaced + lowercase in CSV
            'amount': Decimal('99.00'),
            'transaction_type': Transaction.EXPENSE,
            'errors': [],
            'is_duplicate': False,
            'row_num': 2,
        }
        result = detect_duplicates([row], self.user)
        self.assertTrue(result[0]['is_duplicate'])
