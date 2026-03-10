from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from decimal import Decimal
from .models import Category, Transaction


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
    amount = forms.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal('0.01'),
        widget=forms.NumberInput(attrs={'step': '0.01', 'min': '0.01', 'placeholder': '0.00'}),
    )

    class Meta:
        model = Transaction
        fields = ('date', 'description', 'amount', 'vendor', 'transaction_type', 'status', 'category')
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['category'].queryset = Category.objects.filter(user=user)
        self.fields['category'].required = False
        self.fields['category'].empty_label = '— Uncategorized —'
        self.fields['vendor'].required = False


class CSVUploadForm(forms.Form):
    file = forms.FileField(
        help_text='CSV with headers: Date, Description, Amount, Vendor'
    )

    def clean_file(self):
        f = self.cleaned_data['file']
        if not f.name.endswith('.csv'):
            raise forms.ValidationError('File must be a .csv file.')
        return f


class TransactionFilterForm(forms.Form):
    date_from = forms.DateField(
        required=False, widget=forms.DateInput(attrs={'type': 'date'})
    )
    date_to = forms.DateField(
        required=False, widget=forms.DateInput(attrs={'type': 'date'})
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.none(), required=False, empty_label='All Categories'
    )
    type = forms.ChoiceField(
        choices=[('', 'All Types')] + Transaction.TYPE_CHOICES, required=False
    )
    status = forms.ChoiceField(
        choices=[('', 'All Statuses')] + Transaction.STATUS_CHOICES, required=False
    )
    vendor = forms.CharField(required=False, max_length=200)
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
