from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from decimal import Decimal
from .models import Category, Transaction


class DateTextInput(forms.TextInput):
    """Text input that accepts dates in YYYY-MM-DD format only."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('attrs', {})
        kwargs['attrs'].setdefault('placeholder', 'YYYY-MM-DD')
        super().__init__(*args, **kwargs)


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True, help_text='Required.')

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email')


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ('name', 'type')


class TransactionForm(forms.ModelForm):
    date = forms.DateField(
        input_formats=['%Y-%m-%d'],
        widget=DateTextInput(),
        error_messages={'invalid': 'Enter a date in YYYY-MM-DD format (e.g. 2024-01-31).'},
    )
    amount = forms.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal('0.01'),
        widget=forms.NumberInput(attrs={'step': '0.01', 'min': '0.01', 'placeholder': '0.00'}),
    )

    class Meta:
        model = Transaction
        fields = ('date', 'description', 'amount', 'vendor', 'transaction_type', 'category')

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._user = user
        if user:
            self.fields['category'].queryset = Category.objects.filter(user=user)
        self.fields['category'].required = False
        self.fields['category'].empty_label = '— Uncategorized —'
        self.fields['vendor'].required = False

    def clean(self):
        cleaned = super().clean()
        category = cleaned.get('category')
        transaction_type = cleaned.get('transaction_type')

        if category and self._user and category.user_id != self._user.pk:
            self.add_error('category', 'That category does not belong to your account.')

        if category and transaction_type and category.type != transaction_type:
            type_label = 'income' if transaction_type == Transaction.INCOME else 'expense'
            self.add_error(
                'category',
                f'Please choose an {type_label} category for an {type_label} transaction.',
            )

        return cleaned


class CSVUploadForm(forms.Form):
    MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5 MB

    file = forms.FileField(
        help_text='CSV with headers: Date, Description, Amount, Vendor. Max 5 MB.'
    )

    def clean_file(self):
        f = self.cleaned_data['file']
        if not f.name.endswith('.csv'):
            raise forms.ValidationError('File must be a .csv file.')
        if f.size > self.MAX_UPLOAD_SIZE:
            raise forms.ValidationError('File too large. Maximum size is 5 MB.')
        return f


class DashboardFilterForm(forms.Form):
    date_from = forms.DateField(
        required=False,
        input_formats=['%Y-%m-%d'],
        widget=DateTextInput(),
        error_messages={'invalid': 'Enter a date in YYYY-MM-DD format (e.g. 2024-01-31).'},
    )
    date_to = forms.DateField(
        required=False,
        input_formats=['%Y-%m-%d'],
        widget=DateTextInput(),
        error_messages={'invalid': 'Enter a date in YYYY-MM-DD format (e.g. 2024-01-31).'},
    )


class TransactionFilterForm(forms.Form):
    date_from = forms.DateField(
        required=False,
        input_formats=['%Y-%m-%d'],
        widget=DateTextInput(),
        error_messages={'invalid': 'Enter a date in YYYY-MM-DD format (e.g. 2024-01-31).'},
    )
    date_to = forms.DateField(
        required=False,
        input_formats=['%Y-%m-%d'],
        widget=DateTextInput(),
        error_messages={'invalid': 'Enter a date in YYYY-MM-DD format (e.g. 2024-01-31).'},
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.none(), required=False, empty_label='All Categories'
    )
    type = forms.ChoiceField(
        choices=[('', 'All Types')] + Transaction.TYPE_CHOICES, required=False
    )
    vendor = forms.CharField(required=False, max_length=200)
    amount_min = forms.DecimalField(
        required=False, min_value=Decimal('0'), decimal_places=2,
        widget=forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'placeholder': 'Min $'}),
    )
    amount_max = forms.DecimalField(
        required=False, min_value=Decimal('0'), decimal_places=2,
        widget=forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'placeholder': 'Max $'}),
    )
    sort = forms.ChoiceField(
        choices=[
            ('-date', 'Date (newest)'),
            ('date', 'Date (oldest)'),
            ('-amount', 'Amount (high)'),
            ('amount', 'Amount (low)'),
            ('category__name', 'Category (A-Z)'),
        ],
        required=False,
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['category'].queryset = Category.objects.filter(user=user)

    def clean(self):
        cleaned = super().clean()
        date_from = cleaned.get('date_from')
        date_to = cleaned.get('date_to')
        amount_min = cleaned.get('amount_min')
        amount_max = cleaned.get('amount_max')

        if date_from and date_to and date_from > date_to:
            raise forms.ValidationError('Start date must not be after end date.')

        if amount_min is not None and amount_max is not None and amount_min > amount_max:
            raise forms.ValidationError('Minimum amount must not be greater than maximum amount.')

        return cleaned
