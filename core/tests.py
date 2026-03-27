import datetime
import io
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import Category, Transaction
from .forms import CSVUploadForm
from .services.csv_service import parse_csv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(username='testuser', password='testpass123'):
    return User.objects.create_user(username=username, password=password)


def make_category(user, name='TestCat', cat_type='expense'):
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


def make_csv_file(content, filename='test.csv'):
    return SimpleUploadedFile(filename, content.encode('utf-8'), content_type='text/csv')


def make_csv_fileobj(content):
    """Return a file-like object for parse_csv (no Django upload wrapper needed)."""
    f = io.BytesIO(content.encode('utf-8'))
    f.name = 'test.csv'
    return f


# ---------------------------------------------------------------------------
# 1. Auth & Protected Routes
# ---------------------------------------------------------------------------

class AuthProtectionTests(TestCase):
    """Unauthenticated requests must be redirected to the login page."""

    def test_dashboard_requires_login(self):
        # A visitor who is not logged in should be redirected to /login/
        # with a ?next= param pointing back to the dashboard.
        response = self.client.get(reverse('dashboard'))
        self.assertRedirects(response, '/login/?next=/dashboard/')

    def test_transaction_list_requires_login(self):
        # The transaction list is private — unauthenticated GET must redirect to login.
        response = self.client.get(reverse('transaction_list'))
        self.assertRedirects(response, '/login/?next=/transactions/')

    def test_csv_upload_requires_login(self):
        # The CSV upload page is private — unauthenticated GET must redirect to login.
        response = self.client.get(reverse('csv_upload'))
        self.assertRedirects(response, '/login/?next=/transactions/upload/')

    def test_authenticated_user_redirected_from_register(self):
        # A user who is already logged in has no reason to visit /register/.
        # They should be bounced straight to the dashboard instead.
        make_user()
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('register'))
        self.assertRedirects(response, reverse('dashboard'))

    def test_bad_credentials_stay_on_login(self):
        # Submitting wrong credentials must not authenticate the user.
        # The login page re-renders (200) and the session stays unauthenticated.
        response = self.client.post('/login/', {'username': 'nobody', 'password': 'wrong'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)


# ---------------------------------------------------------------------------
# 2. Registration
# ---------------------------------------------------------------------------

class RegistrationTests(TestCase):
    """Register view and default category seeding."""

    def test_valid_registration_logs_in_and_redirects(self):
        # Posting valid credentials should create the user, log them in immediately,
        # redirect to the dashboard, and seed the 8 default categories via the post_save signal.
        response = self.client.post(reverse('register'), {
            'username': 'newuser',
            'email': 'new@example.com',
            'password1': 'strongpass99!',
            'password2': 'strongpass99!',
        })
        self.assertRedirects(response, reverse('dashboard'))
        self.assertTrue(response.wsgi_request.user.is_authenticated)
        # Default categories should be seeded by the signal
        self.assertEqual(Category.objects.filter(user__username='newuser').count(), 10)

    def test_mismatched_passwords_do_not_create_user(self):
        # If password1 and password2 don't match, the form is invalid and
        # no User record should be created in the database.
        self.client.post(reverse('register'), {
            'username': 'newuser',
            'email': 'new@example.com',
            'password1': 'strongpass99!',
            'password2': 'different',
        })
        self.assertFalse(User.objects.filter(username='newuser').exists())


# ---------------------------------------------------------------------------
# 3. Transaction CRUD & Access Control
# ---------------------------------------------------------------------------

class TransactionCRUDTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.other = make_user('other')
        self.client.login(username='testuser', password='testpass123')

    def test_transaction_list_loads(self):
        # The transaction list page should return 200 and expose the correct
        # transaction count in context — confirming the queryset is scoped to self.user.
        make_transaction(self.user)
        response = self.client.get(reverse('transaction_list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 1)

    def test_transaction_add_creates_and_redirects(self):
        # POSTing a valid transaction form should persist one Transaction row
        # for the logged-in user and redirect to the list page.
        response = self.client.post(reverse('transaction_add'), {
            'date': '2024-03-01',
            'description': 'Office supplies',
            'amount': '49.99',
            'vendor': 'Staples',
            'transaction_type': Transaction.EXPENSE,
        })
        self.assertRedirects(response, reverse('transaction_list'))
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 1)

    def test_edit_other_users_transaction_returns_404(self):
        # A user must not be able to open the edit page for a transaction
        # that belongs to a different user — the view should return 404.
        t = make_transaction(self.other)
        response = self.client.get(reverse('transaction_edit', args=[t.pk]))
        self.assertEqual(response.status_code, 404)

    def test_delete_other_users_transaction_returns_404(self):
        # A user must not be able to delete another user's transaction.
        # POSTing to the delete URL for a foreign transaction should return 404.
        t = make_transaction(self.other)
        response = self.client.post(reverse('transaction_delete', args=[t.pk]))
        self.assertEqual(response.status_code, 404)

    def test_edit_own_transaction_updates_it(self):
        # POSTing a valid edit form for the user's own transaction should
        # persist the changed field values to the database.
        t = make_transaction(self.user, description='Old description')
        self.client.post(reverse('transaction_edit', args=[t.pk]), {
            'date': '2024-01-15',
            'description': 'Updated description',
            'amount': '100.00',
            'vendor': 'ACME',
            'transaction_type': Transaction.EXPENSE,
        })
        t.refresh_from_db()
        self.assertEqual(t.description, 'Updated description')

    def test_delete_own_transaction_removes_it(self):
        # POSTing to the delete URL for the user's own transaction should
        # remove the row from the database entirely.
        t = make_transaction(self.user)
        self.client.post(reverse('transaction_delete', args=[t.pk]))
        self.assertFalse(Transaction.objects.filter(pk=t.pk).exists())

    def test_transaction_list_only_shows_own_transactions(self):
        # The queryset in transaction_list is filtered by request.user.
        # Creating one transaction per user should result in total_count=1,
        # confirming the other user's transaction is invisible.
        make_transaction(self.user, description='Mine')
        make_transaction(self.other, description='Theirs')
        response = self.client.get(reverse('transaction_list'))
        self.assertEqual(response.context['total_count'], 1)


# ---------------------------------------------------------------------------
# 4. CSV Parsing Service
# ---------------------------------------------------------------------------

class ParseCSVTests(TestCase):
    """Tests for core/services/csv_service.parse_csv."""

    def test_valid_row_parsed_correctly(self):
        # A well-formed CSV row should be parsed without errors and produce
        # the correct date (as a date object), amount (as Decimal), description, and vendor.
        f = make_csv_fileobj("Date,Description,Amount,Vendor\n2024-01-15,AWS Invoice,-120.00,Amazon\n")
        rows = parse_csv(f)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['errors'], [])
        self.assertEqual(row['date'], datetime.date(2024, 1, 15))
        self.assertEqual(row['amount'], Decimal('120.00'))
        self.assertEqual(row['description'], 'AWS Invoice')
        self.assertEqual(row['vendor'], 'Amazon')

    def test_negative_amount_classified_as_expense(self):
        # A negative amount in the CSV signals money going out.
        # parse_csv should set transaction_type to EXPENSE for that row.
        f = make_csv_fileobj("Date,Description,Amount,Vendor\n2024-01-15,Rent,-500.00,Landlord\n")
        rows = parse_csv(f)
        self.assertEqual(rows[0]['transaction_type'], Transaction.EXPENSE)

    def test_positive_amount_classified_as_income(self):
        # A positive amount signals money coming in.
        # parse_csv should set transaction_type to INCOME for that row.
        f = make_csv_fileobj("Date,Description,Amount,Vendor\n2024-01-15,Salary,3000.00,Employer\n")
        rows = parse_csv(f)
        self.assertEqual(rows[0]['transaction_type'], Transaction.INCOME)

    def test_parentheses_amount_notation_classified_as_expense(self):
        # Some accounting exports use (50.00) to represent a negative number.
        # parse_csv should treat this as an expense and strip the parens from the amount.
        f = make_csv_fileobj("Date,Description,Amount,Vendor\n2024-01-15,Refund,(50.00),Shop\n")
        rows = parse_csv(f)
        self.assertEqual(rows[0]['transaction_type'], Transaction.EXPENSE)
        self.assertEqual(rows[0]['amount'], Decimal('50.00'))

    def test_missing_required_headers_raises_value_error(self):
        # If the CSV is missing one of the four required columns (Date, Description,
        # Amount, Vendor), parse_csv should raise ValueError immediately — before
        # processing any rows — so the upload can be rejected cleanly.
        f = make_csv_fileobj("Date,Description,Amount\n2024-01-15,No vendor,100.00\n")
        with self.assertRaises(ValueError):
            parse_csv(f)

    def test_invalid_date_and_empty_description_produce_row_errors(self):
        # Rows with an unparseable date or blank description should not be silently skipped.
        # Each problem should be recorded in the row's 'errors' list so the UI
        # can show the user exactly which rows failed and why.
        f = make_csv_fileobj("Date,Description,Amount,Vendor\nbad-date,,-50.00,Shop\n")
        rows = parse_csv(f)
        self.assertEqual(len(rows), 1)
        errors = rows[0]['errors']
        self.assertTrue(any('date' in e.lower() or 'invalid' in e.lower() for e in errors))
        self.assertTrue(any('description' in e.lower() or 'empty' in e.lower() for e in errors))


# ---------------------------------------------------------------------------
# 5. CSV Upload Form Validation
# ---------------------------------------------------------------------------

class CSVUploadFormTests(TestCase):
    """CSVUploadForm.clean_file rejects wrong extension and oversized files."""

    def test_non_csv_extension_is_invalid(self):
        # The upload form's clean_file() checks the filename extension.
        # Uploading a .txt file should fail validation with an error on the 'file' field.
        f = SimpleUploadedFile('data.txt', b'some,data', content_type='text/plain')
        form = CSVUploadForm(files={'file': f})
        self.assertFalse(form.is_valid())
        self.assertIn('file', form.errors)

    def test_oversized_file_is_invalid(self):
        # The upload form enforces a 5 MB size limit.
        # A file even one byte over the limit should be rejected with a field error.
        big = b'x' * (5 * 1024 * 1024 + 1)  # 1 byte over 5 MB
        f = SimpleUploadedFile('data.csv', big, content_type='text/csv')
        form = CSVUploadForm(files={'file': f})
        self.assertFalse(form.is_valid())
        self.assertIn('file', form.errors)


# ---------------------------------------------------------------------------
# 6. Transaction Model Domain Rules
# ---------------------------------------------------------------------------

class TransactionModelTests(TestCase):
    """Model-level clean() validation and vendor normalization."""

    def setUp(self):
        self.user = make_user()
        self.other = make_user('other')
        self.income_cat, _ = Category.objects.get_or_create(
            user=self.user, name='Revenue', defaults={'type': Category.INCOME}
        )

    def test_income_category_on_expense_transaction_raises(self):
        # Assigning an income-type category to an expense transaction violates
        # the domain rule that category.type must match transaction_type.
        # Transaction.clean() should raise ValidationError with an error on 'category'.
        t = Transaction(
            user=self.user,
            date='2024-01-15',
            description='Test',
            amount=Decimal('50.00'),
            transaction_type=Transaction.EXPENSE,
            category=self.income_cat,
        )
        with self.assertRaises(ValidationError) as cm:
            t.clean()
        self.assertIn('category', cm.exception.message_dict)

    def test_other_users_category_raises(self):
        # A category owned by user B must never be assignable to user A's transaction.
        # Transaction.clean() should catch this cross-user assignment and raise ValidationError.
        other_cat = make_category(self.other, name='Travel')
        t = Transaction(
            user=self.user,
            date='2024-01-15',
            description='Test',
            amount=Decimal('50.00'),
            transaction_type=Transaction.EXPENSE,
            category=other_cat,
        )
        with self.assertRaises(ValidationError) as cm:
            t.clean()
        self.assertIn('category', cm.exception.message_dict)

    def test_save_normalizes_vendor(self):
        # Transaction.save() calls _normalize_vendor() which lowercases the string
        # and collapses internal whitespace. This ensures vendor grouping in charts
        # is consistent regardless of how the vendor was typed or imported.
        t = make_transaction(self.user, vendor='  AMAZON  Prime  ')
        self.assertEqual(t.normalized_vendor, 'amazon prime')


# ---------------------------------------------------------------------------
# 7. Dashboard
# ---------------------------------------------------------------------------

class DashboardTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.login(username='testuser', password='testpass123')

    def test_dashboard_loads_for_authenticated_user(self):
        # The dashboard should return 200 and pass the KPI and chart context
        # variables that the template depends on.
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        for key in ('income_total', 'expense_total', 'net_cash_flow', 'chart_data'):
            self.assertIn(key, response.context)

    def test_dashboard_net_cash_flow(self):
        # net_cash_flow = income_total - expense_total.
        # With $1,000 income and $400 expense the dashboard should show $600 net.
        make_transaction(self.user, amount=Decimal('1000.00'), transaction_type=Transaction.INCOME)
        make_transaction(self.user, amount=Decimal('400.00'), transaction_type=Transaction.EXPENSE)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['net_cash_flow'], Decimal('600.00'))

    def test_dashboard_zero_totals_when_no_transactions(self):
        # A brand-new account with no transactions should show 0 for all KPIs
        # rather than None or a missing key (which would crash the template).
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['income_total'], Decimal('0'))
        self.assertEqual(response.context['expense_total'], Decimal('0'))
        self.assertEqual(response.context['net_cash_flow'], Decimal('0'))


# ---------------------------------------------------------------------------
# 8. CSV Upload View
# ---------------------------------------------------------------------------

class CSVUploadViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.login(username='testuser', password='testpass123')

    def test_valid_csv_upload_creates_transactions(self):
        # Uploading a well-formed two-row CSV through the actual upload view
        # should result in two Transaction rows owned by the logged-in user.
        f = make_csv_file(
            "Date,Description,Amount,Vendor\n"
            "2024-01-15,AWS Invoice,-120.00,Amazon\n"
            "2024-01-16,Salary,3000.00,Employer\n"
        )
        self.client.post(reverse('csv_upload'), {'file': f})
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 2)

    def test_csv_with_all_invalid_rows_creates_no_transactions(self):
        # If every row in the uploaded file has parse errors (bad date, empty description),
        # none of them should be imported — Transaction count must stay at zero.
        f = make_csv_file(
            "Date,Description,Amount,Vendor\n"
            "bad-date,,-999.00,Shop\n"   # invalid date + empty description
        )
        self.client.post(reverse('csv_upload'), {'file': f})
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 0)


# ---------------------------------------------------------------------------
# 9. AI Suggestion
# ---------------------------------------------------------------------------

class AISuggestionTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.login(username='testuser', password='testpass123')
        self.cat = make_category(self.user, name='Software', cat_type='expense')

    def test_ai_suggest_category_endpoint_requires_auth(self):
        # The AI suggestion API is session-authenticated.
        # An unauthenticated POST should be rejected with 403, not a redirect.
        self.client.logout()
        response = self.client.post(
            reverse('api_suggest_category'),
            data='{"description":"AWS charge","vendor":"Amazon"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)

    def test_ai_suggest_for_transaction_saves_suggestion(self):
        # When the AI service returns a category name that matches one of the user's
        # categories, the view should save it as ai_suggested_category on the transaction
        # and return the name and category_id in the JSON response.
        # The OpenAI call is mocked so no real API request is made.
        from unittest.mock import patch
        t = make_transaction(self.user, description='AWS charge', vendor='Amazon')
        with patch('core.services.ai_service.suggest_category', return_value='Software'):
            response = self.client.post(reverse('api_suggest_for_transaction', args=[t.pk]),
                                        content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['suggestion'], 'Software')
        t.refresh_from_db()
        self.assertEqual(t.ai_suggested_category, self.cat)

    def test_ai_suggest_handles_no_api_key_gracefully(self):
        # When OPENAI_API_KEY is blank, suggest_category returns None early.
        # The endpoint should still return 200 with suggestion=None rather than crashing.
        from django.test import override_settings
        t = make_transaction(self.user)
        with override_settings(OPENAI_API_KEY=''):
            response = self.client.post(reverse('api_suggest_for_transaction', args=[t.pk]),
                                        content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['suggestion'])

    def test_api_accept_suggestion_applies_category(self):
        # Accepting an AI suggestion should copy ai_suggested_category into the
        # real category field and return 200 with the category name in the response.
        t = make_transaction(self.user)
        t.ai_suggested_category = self.cat
        t.save()
        response = self.client.post(reverse('api_accept_suggestion', args=[t.pk]),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 200)
        t.refresh_from_db()
        self.assertEqual(t.category, self.cat)

    def test_api_accept_suggestion_does_not_overwrite_existing_category(self):
        # If the transaction already has a real category assigned, accepting an
        # AI suggestion on top of it should be rejected with 400 to prevent
        # silently overwriting a user's deliberate categorization choice.
        other_cat = make_category(self.user, name='Meals', cat_type='expense')
        t = make_transaction(self.user, category=other_cat)
        t.ai_suggested_category = self.cat
        t.save()
        response = self.client.post(reverse('api_accept_suggestion', args=[t.pk]),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 400)
        t.refresh_from_db()
        self.assertEqual(t.category, other_cat)  # unchanged

    def test_ai_suggest_for_other_users_transaction_returns_404(self):
        # A user must not be able to trigger AI suggestions on another user's transaction.
        # The view uses get_object_or_404(Transaction, pk=pk, user=request.user),
        # so a foreign pk should return 404.
        other = make_user('other')
        t = make_transaction(other)
        response = self.client.post(reverse('api_suggest_for_transaction', args=[t.pk]),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# 10. Transaction list filter — invalid date handling
# ---------------------------------------------------------------------------

class TransactionListFilterTests(TestCase):
    """Verify that invalid dates surface a visible error and don't silently drop filters."""

    def setUp(self):
        self.user = make_user()
        self.client.login(username='testuser', password='testpass123')
        # Two transactions in different months so date filtering is testable
        make_transaction(self.user, date='2024-01-10', description='January tx')
        make_transaction(self.user, date='2024-06-15', description='June tx')

    def test_invalid_date_from_returns_200_with_form_error(self):
        # Feb 31 doesn't exist, so DateField validation should fail.
        # The page should still render (200) and expose the error on date_from
        # in the filter form's error dict so the template can display it.
        response = self.client.get(reverse('transaction_list'), {'date_from': '2024-02-31'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['filter_form'].is_valid())
        self.assertIn('date_from', response.context['filter_form'].errors)

    def test_invalid_date_from_renders_error_text_in_page(self):
        # The error message must actually appear in the rendered HTML so the user
        # can see what went wrong without inspecting the network response.
        response = self.client.get(reverse('transaction_list'), {'date_from': '2024-02-31'})
        self.assertContains(response, 'Enter a date in YYYY-MM-DD format')

    def test_invalid_date_to_returns_200_with_form_error(self):
        # Month 13 doesn't exist — same validation failure as above but on date_to.
        # Ensures both date fields are independently validated and reported.
        response = self.client.get(reverse('transaction_list'), {'date_to': '2024-13-01'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('date_to', response.context['filter_form'].errors)

    def test_invalid_date_shows_all_transactions_not_empty(self):
        # When the filter form is invalid, no filtering is applied at all.
        # The full unfiltered dataset should be returned so the user still
        # sees their transactions while they correct the invalid input.
        response = self.client.get(reverse('transaction_list'), {'date_from': '2024-02-31'})
        self.assertEqual(response.context['total_count'], 2)

    def test_reversed_date_range_shows_non_field_error(self):
        # Both dates are individually valid, but date_from > date_to is a logical
        # contradiction caught by TransactionFilterForm.clean(). The error is a
        # non-field (form-level) error and must appear in the rendered page.
        response = self.client.get(reverse('transaction_list'),
                                   {'date_from': '2024-12-31', 'date_to': '2024-01-01'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['filter_form'].non_field_errors())
        self.assertContains(response, 'Start date must not be after end date')

    def test_valid_date_filter_applies_correctly(self):
        # A well-formed date range should filter the queryset correctly.
        # Only the June transaction falls within June–December, so total_count must be 1.
        response = self.client.get(reverse('transaction_list'),
                                   {'date_from': '2024-06-01', 'date_to': '2024-12-31'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 1)
        self.assertContains(response, 'June tx')
