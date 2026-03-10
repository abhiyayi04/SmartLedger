from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.http import HttpResponse
from collections import OrderedDict
from decimal import Decimal
import csv as csv_module
from .forms import RegisterForm, ProfileForm, CategoryForm, TransactionForm, CSVUploadForm, TransactionFilterForm
from .models import Category, Transaction


def homepage(request):
    return render(request, 'homepage.html')


def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f'Welcome to SmartLedger, {user.username}!')
            return redirect('dashboard')
    else:
        form = RegisterForm()
    return render(request, 'auth/register.html', {'form': form})


@login_required
def profile_edit(request):
    if request.method == 'POST':
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully.')
            return redirect('profile')
    else:
        form = ProfileForm(instance=request.user)
    return render(request, 'auth/profile.html', {'form': form})


@login_required
def dashboard(request):
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    qs = Transaction.objects.filter(user=request.user)
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)

    # KPI totals
    income_total = qs.filter(transaction_type=Transaction.INCOME).aggregate(
        total=Sum('amount'))['total'] or Decimal('0')
    expense_total = qs.filter(transaction_type=Transaction.EXPENSE).aggregate(
        total=Sum('amount'))['total'] or Decimal('0')
    net_cash_flow = income_total - expense_total

    # Uncategorized (always all-time so the alert is always visible)
    uncategorized_count = Transaction.objects.filter(
        user=request.user, category__isnull=True).count()

    # Recent 10 transactions
    recent_transactions = qs.select_related('category').order_by('-date', '-created_at')[:10]

    # Expense by category for pie chart
    expense_by_cat = (
        qs.filter(transaction_type=Transaction.EXPENSE, category__isnull=False)
        .values('category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')
    )

    # Monthly income vs expense for bar chart
    monthly_qs = (
        qs.annotate(month=TruncMonth('date'))
        .values('month', 'transaction_type')
        .annotate(total=Sum('amount'))
        .order_by('month')
    )
    monthly_data = OrderedDict()
    for item in monthly_qs:
        key = item['month'].strftime('%b %Y')
        if key not in monthly_data:
            monthly_data[key] = {'income': 0.0, 'expense': 0.0}
        monthly_data[key][item['transaction_type']] = float(item['total'])

    # Top 5 vendors by expense spend
    top_vendors = (
        qs.filter(transaction_type=Transaction.EXPENSE)
        .exclude(vendor='')
        .values('vendor')
        .annotate(total=Sum('amount'))
        .order_by('-total')[:5]
    )

    chart_data = {
        'category_pie': {
            'labels': [item['category__name'] for item in expense_by_cat],
            'data': [float(item['total']) for item in expense_by_cat],
        },
        'monthly': {
            'labels': list(monthly_data.keys()),
            'income': [monthly_data[k]['income'] for k in monthly_data],
            'expense': [monthly_data[k]['expense'] for k in monthly_data],
        },
        'vendors': {
            'labels': [item['vendor'] for item in top_vendors],
            'data': [float(item['total']) for item in top_vendors],
        },
    }

    return render(request, 'dashboard/index.html', {
        'income_total': income_total,
        'expense_total': expense_total,
        'net_cash_flow': net_cash_flow,
        'uncategorized_count': uncategorized_count,
        'recent_transactions': recent_transactions,
        'chart_data': chart_data,
        'date_from': date_from,
        'date_to': date_to,
        'total_transactions': qs.count(),
    })


@login_required
def export_csv(request):
    qs = Transaction.objects.filter(user=request.user).select_related('category').order_by('-date')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="transactions.csv"'
    writer = csv_module.writer(response)
    writer.writerow(['Date', 'Description', 'Amount', 'Vendor', 'Type', 'Status', 'Category'])
    for t in qs:
        sign = '-' if t.transaction_type == Transaction.EXPENSE else ''
        writer.writerow([
            t.date.isoformat(),
            t.description,
            f"{sign}{t.amount}",
            t.vendor,
            t.get_transaction_type_display(),
            t.get_status_display(),
            t.category.name if t.category else '',
        ])
    return response


@login_required
def transaction_list(request):
    qs = Transaction.objects.filter(user=request.user).select_related('category')
    filter_form = TransactionFilterForm(request.GET or None, user=request.user)

    if filter_form.is_valid():
        d = filter_form.cleaned_data
        if d.get('date_from'):
            qs = qs.filter(date__gte=d['date_from'])
        if d.get('date_to'):
            qs = qs.filter(date__lte=d['date_to'])
        if d.get('category'):
            qs = qs.filter(category=d['category'])
        if d.get('type'):
            qs = qs.filter(transaction_type=d['type'])
        if d.get('status'):
            qs = qs.filter(status=d['status'])
        if d.get('vendor'):
            qs = qs.filter(vendor__icontains=d['vendor'])
        sort = d.get('sort') or '-date'
        qs = qs.order_by(sort)

    return render(request, 'transactions/list.html', {
        'transactions': qs,
        'filter_form': filter_form,
        'total_count': qs.count(),
    })


@login_required
def transaction_add(request):
    if request.method == 'POST':
        form = TransactionForm(request.POST, user=request.user)
        if form.is_valid():
            t = form.save(commit=False)
            t.user = request.user
            t.save()
            messages.success(request, 'Transaction added.')
            return redirect('transaction_list')
    else:
        form = TransactionForm(user=request.user)
    return render(request, 'transactions/form.html', {'form': form, 'action': 'Add'})


@login_required
def transaction_edit(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, user=request.user)
    if request.method == 'POST':
        form = TransactionForm(request.POST, instance=transaction, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Transaction updated.')
            return redirect('transaction_list')
    else:
        form = TransactionForm(instance=transaction, user=request.user)
    return render(request, 'transactions/form.html', {
        'form': form, 'action': 'Edit', 'transaction': transaction
    })


@login_required
def transaction_delete(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, user=request.user)
    if request.method == 'POST':
        transaction.delete()
        messages.success(request, 'Transaction deleted.')
        return redirect('transaction_list')
    return render(request, 'transactions/confirm_delete.html', {'transaction': transaction})


@login_required
def csv_upload(request):
    if request.method == 'POST':
        form = CSVUploadForm(request.POST, request.FILES)
        if form.is_valid():
            from .services.csv_service import parse_csv, detect_duplicates, serialize_rows
            try:
                rows = parse_csv(request.FILES['file'])
                rows = detect_duplicates(rows, request.user)
                request.session['csv_preview'] = serialize_rows(rows)
                return redirect('csv_preview')
            except ValueError as e:
                messages.error(request, str(e))
    else:
        form = CSVUploadForm()
    return render(request, 'transactions/csv_upload.html', {'form': form})


@login_required
def csv_preview(request):
    rows = request.session.get('csv_preview')
    if not rows:
        messages.error(request, 'No CSV data found. Please upload a file first.')
        return redirect('csv_upload')

    if request.method == 'POST':
        selected = set(request.POST.getlist('selected_rows'))
        to_import = []
        for i, row in enumerate(rows):
            if str(i) in selected and not row['errors']:
                to_import.append(Transaction(
                    user=request.user,
                    date=row['date'],
                    description=row['description'],
                    amount=Decimal(row['amount']),
                    vendor=row['vendor'],
                    transaction_type=row['transaction_type'],
                    status=Transaction.PENDING,
                ))
        if to_import:
            Transaction.objects.bulk_create(to_import)
            del request.session['csv_preview']
            messages.success(request, f'Imported {len(to_import)} transaction(s).')
            return redirect('transaction_list')
        else:
            messages.warning(request, 'No rows selected for import.')

    valid_count = sum(1 for r in rows if not r['errors'] and not r['is_duplicate'])
    duplicate_count = sum(1 for r in rows if r['is_duplicate'] and not r['errors'])
    error_count = sum(1 for r in rows if r['errors'])

    return render(request, 'transactions/csv_preview.html', {
        'rows': rows,
        'valid_count': valid_count,
        'duplicate_count': duplicate_count,
        'error_count': error_count,
    })


@login_required
def category_list(request):
    categories = Category.objects.filter(user=request.user)
    income_cats = categories.filter(type=Category.INCOME)
    expense_cats = categories.filter(type=Category.EXPENSE)
    return render(request, 'categories/list.html', {
        'income_cats': income_cats,
        'expense_cats': expense_cats,
    })


@login_required
def category_add(request):
    if request.method == 'POST':
        form = CategoryForm(request.POST)
        if form.is_valid():
            category = form.save(commit=False)
            category.user = request.user
            category.save()
            messages.success(request, f'Category "{category.name}" created.')
            return redirect('category_list')
    else:
        form = CategoryForm()
    return render(request, 'categories/form.html', {'form': form, 'action': 'Add'})


@login_required
def category_edit(request, pk):
    category = get_object_or_404(Category, pk=pk, user=request.user)
    if request.method == 'POST':
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            messages.success(request, f'Category "{category.name}" updated.')
            return redirect('category_list')
    else:
        form = CategoryForm(instance=category)
    return render(request, 'categories/form.html', {'form': form, 'action': 'Edit', 'category': category})


@login_required
def category_delete(request, pk):
    category = get_object_or_404(Category, pk=pk, user=request.user)
    if request.method == 'POST':
        name = category.name
        category.delete()
        messages.success(request, f'Category "{name}" deleted.')
        return redirect('category_list')
    return render(request, 'categories/confirm_delete.html', {'category': category})
