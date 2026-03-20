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
        response = self.client.get(reverse('dashboard'))
        self.assertRedirects(response, '/login/?next=/dashboard/')

    def test_transaction_list_requires_login(self):
        response = self.client.get(reverse('transaction_list'))
        self.assertRedirects(response, '/login/?next=/transactions/')

    def test_csv_upload_requires_login(self):
        response = self.client.get(reverse('csv_upload'))
        self.assertRedirects(response, '/login/?next=/transactions/upload/')

    def test_authenticated_user_redirected_from_register(self):
        make_user()
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('register'))
        self.assertRedirects(response, reverse('dashboard'))

    def test_bad_credentials_stay_on_login(self):
        response = self.client.post('/login/', {'username': 'nobody', 'password': 'wrong'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)


# ---------------------------------------------------------------------------
# 2. Registration
# ---------------------------------------------------------------------------

class RegistrationTests(TestCase):
    """Register view and default category seeding."""

    def test_valid_registration_logs_in_and_redirects(self):
        response = self.client.post(reverse('register'), {
            'username': 'newuser',
            'email': 'new@example.com',
            'password1': 'strongpass99!',
            'password2': 'strongpass99!',
        })
        self.assertRedirects(response, reverse('dashboard'))
        self.assertTrue(response.wsgi_request.user.is_authenticated)
        # Default categories should be seeded by the signal
        self.assertEqual(Category.objects.filter(user__username='newuser').count(), 8)

    def test_mismatched_passwords_do_not_create_user(self):
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
        make_transaction(self.user)
        response = self.client.get(reverse('transaction_list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 1)

    def test_transaction_add_creates_and_redirects(self):
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
        t = make_transaction(self.other)
        response = self.client.get(reverse('transaction_edit', args=[t.pk]))
        self.assertEqual(response.status_code, 404)

    def test_delete_other_users_transaction_returns_404(self):
        t = make_transaction(self.other)
        response = self.client.post(reverse('transaction_delete', args=[t.pk]))
        self.assertEqual(response.status_code, 404)

    def test_edit_own_transaction_updates_it(self):
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
        t = make_transaction(self.user)
        self.client.post(reverse('transaction_delete', args=[t.pk]))
        self.assertFalse(Transaction.objects.filter(pk=t.pk).exists())

    def test_transaction_list_only_shows_own_transactions(self):
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
        f = make_csv_fileobj("Date,Description,Amount,Vendor\n2024-01-15,Rent,-500.00,Landlord\n")
        rows = parse_csv(f)
        self.assertEqual(rows[0]['transaction_type'], Transaction.EXPENSE)

    def test_positive_amount_classified_as_income(self):
        f = make_csv_fileobj("Date,Description,Amount,Vendor\n2024-01-15,Salary,3000.00,Employer\n")
        rows = parse_csv(f)
        self.assertEqual(rows[0]['transaction_type'], Transaction.INCOME)

    def test_parentheses_amount_notation_classified_as_expense(self):
        f = make_csv_fileobj("Date,Description,Amount,Vendor\n2024-01-15,Refund,(50.00),Shop\n")
        rows = parse_csv(f)
        self.assertEqual(rows[0]['transaction_type'], Transaction.EXPENSE)
        self.assertEqual(rows[0]['amount'], Decimal('50.00'))

    def test_missing_required_headers_raises_value_error(self):
        f = make_csv_fileobj("Date,Description,Amount\n2024-01-15,No vendor,100.00\n")
        with self.assertRaises(ValueError):
            parse_csv(f)

    def test_invalid_date_and_empty_description_produce_row_errors(self):
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
        f = SimpleUploadedFile('data.txt', b'some,data', content_type='text/plain')
        form = CSVUploadForm(files={'file': f})
        self.assertFalse(form.is_valid())
        self.assertIn('file', form.errors)

    def test_oversized_file_is_invalid(self):
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
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        for key in ('income_total', 'expense_total', 'net_cash_flow', 'chart_data'):
            self.assertIn(key, response.context)

    def test_dashboard_net_cash_flow(self):
        make_transaction(self.user, amount=Decimal('1000.00'), transaction_type=Transaction.INCOME)
        make_transaction(self.user, amount=Decimal('400.00'), transaction_type=Transaction.EXPENSE)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['net_cash_flow'], Decimal('600.00'))

    def test_dashboard_zero_totals_when_no_transactions(self):
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
        f = make_csv_file(
            "Date,Description,Amount,Vendor\n"
            "2024-01-15,AWS Invoice,-120.00,Amazon\n"
            "2024-01-16,Salary,3000.00,Employer\n"
        )
        self.client.post(reverse('csv_upload'), {'file': f})
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 2)

    def test_csv_with_all_invalid_rows_creates_no_transactions(self):
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
        self.client.logout()
        response = self.client.post(
            reverse('api_suggest_category'),
            data='{"description":"AWS charge","vendor":"Amazon"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)

    def test_ai_suggest_for_transaction_saves_suggestion(self):
        """When AI returns a valid category name, it is saved as ai_suggested_category."""
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
        """When OPENAI_API_KEY is not set, the endpoint returns suggestion=None without crashing."""
        from django.test import override_settings
        t = make_transaction(self.user)
        with override_settings(OPENAI_API_KEY=''):
            response = self.client.post(reverse('api_suggest_for_transaction', args=[t.pk]),
                                        content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['suggestion'])

    def test_api_accept_suggestion_applies_category(self):
        t = make_transaction(self.user)
        t.ai_suggested_category = self.cat
        t.save()
        response = self.client.post(reverse('api_accept_suggestion', args=[t.pk]),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 200)
        t.refresh_from_db()
        self.assertEqual(t.category, self.cat)

    def test_api_accept_suggestion_does_not_overwrite_existing_category(self):
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
        other = make_user('other')
        t = make_transaction(other)
        response = self.client.post(reverse('api_suggest_for_transaction', args=[t.pk]),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 404)
