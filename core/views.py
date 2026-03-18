from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction as db_transaction
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.http import HttpResponse
from collections import OrderedDict
from decimal import Decimal
import csv as csv_module
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .forms import RegisterForm, ProfileForm, CategoryForm, TransactionForm, CSVUploadForm, TransactionFilterForm, DashboardFilterForm
from .models import AuditLog, Category, ImportHistory, Transaction
from .utils import audit


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
    filter_form = DashboardFilterForm(request.GET or None)
    date_from = None
    date_to = None
    if filter_form.is_valid():
        date_from = filter_form.cleaned_data.get('date_from')
        date_to = filter_form.cleaned_data.get('date_to')

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
        'date_from': date_from.isoformat() if date_from else '',
        'date_to': date_to.isoformat() if date_to else '',
        'total_transactions': qs.count(),
    })


@login_required
def export_csv(request):
    qs = Transaction.objects.filter(user=request.user).select_related('category').order_by('-date')
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
        if d.get('amount_min') is not None:
            qs = qs.filter(amount__gte=d['amount_min'])
        if d.get('amount_max') is not None:
            qs = qs.filter(amount__lte=d['amount_max'])

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
    qs = Transaction.objects.filter(user=request.user).select_related('category', 'ai_suggested_category')
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
        if d.get('amount_min') is not None:
            qs = qs.filter(amount__gte=d['amount_min'])
        if d.get('amount_max') is not None:
            qs = qs.filter(amount__lte=d['amount_max'])
        sort = d.get('sort') or '-date'
        qs = qs.order_by(sort)

    total_count = qs.count()
    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'transactions/list.html', {
        'transactions': page_obj,
        'filter_form': filter_form,
        'total_count': total_count,
        'page_obj': page_obj,
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
            t = form.save()
            audit(request.user, AuditLog.EDIT, transaction=t,
                  metadata={'description': t.description, 'amount': str(t.amount)})
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
        audit(request.user, AuditLog.DELETE,
              metadata={'description': transaction.description, 'amount': str(transaction.amount), 'date': str(transaction.date)})
        transaction.delete()
        messages.success(request, 'Transaction deleted.')
        return redirect('transaction_list')
    return render(request, 'transactions/confirm_delete.html', {'transaction': transaction})


@login_required
def csv_upload(request):
    if request.method == 'POST':
        form = CSVUploadForm(request.POST, request.FILES)
        if form.is_valid():
            from .services.csv_service import parse_csv, detect_duplicates
            try:
                rows = parse_csv(request.FILES['file'])
                rows = detect_duplicates(rows, request.user)
                to_import = [
                    Transaction(
                        user=request.user,
                        date=row['date'],
                        description=row['description'],
                        amount=Decimal(row['amount']),
                        vendor=row['vendor'],
                        transaction_type=row['transaction_type'],
                    )
                    for row in rows if not row['errors'] and not row['is_duplicate']
                ]
                duplicate_count = sum(1 for r in rows if r['is_duplicate'] and not r['errors'])
                error_count = sum(1 for r in rows if r['errors'])
                error_details = [
                    {'row_num': r['row_num'], 'errors': r['errors']}
                    for r in rows if r['errors']
                ]

                if to_import:
                    with db_transaction.atomic():
                        Transaction.objects.bulk_create(to_import)

                history = ImportHistory.objects.create(
                    user=request.user,
                    filename=request.FILES['file'].name,
                    total_rows=len(rows),
                    imported_count=len(to_import),
                    duplicate_count=duplicate_count,
                    invalid_count=error_count,
                    error_details=error_details,
                )
                if len(to_import) > 0:
                    audit(request.user, AuditLog.IMPORT, metadata={
                        'filename': request.FILES['file'].name,
                        'imported_count': len(to_import),
                        'import_history_id': history.pk,
                    })
                return redirect('import_history_detail', pk=history.pk)
            except ValueError as e:
                messages.error(request, str(e))
    else:
        form = CSVUploadForm()
    return render(request, 'transactions/csv_upload.html', {'form': form})


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


@api_view(['POST'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_suggest_category(request):
    description = request.data.get('description', '').strip()
    vendor = request.data.get('vendor', '').strip()

    if not description:
        return Response({'error': 'description is required'}, status=400)

    categories = list(Category.objects.filter(user=request.user).values('id', 'name', 'type'))
    cat_map = {c['name']: c['id'] for c in categories}

    from .services.ai_service import suggest_category
    name = suggest_category(description, vendor, categories)

    if name is None:
        return Response({'suggestion': None})

    return Response({'suggestion': name, 'category_id': cat_map.get(name)})


@api_view(['POST'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_batch_suggest(request):
    rows = request.data.get('rows', [])

    if not rows:
        return Response({'suggestions': {}})

    categories = list(Category.objects.filter(user=request.user).values('id', 'name', 'type'))
    cat_map = {c['name']: c['id'] for c in categories}

    from .services.ai_service import batch_suggest
    names = batch_suggest(rows, categories)

    suggestions = {
        idx: {'name': name, 'category_id': cat_map.get(name)}
        for idx, name in names.items()
    }

    return Response({'suggestions': suggestions})


@api_view(['POST'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_suggest_uncategorized(request):
    """
    Run AI suggestions on all transactions for this user that have no category
    and no existing ai_suggested_category. Saves suggestions to the DB and
    returns {pk: {name, category_id}} for the caller to update the UI.
    """
    qs = Transaction.objects.filter(
        user=request.user,
        category__isnull=True,
        ai_suggested_category__isnull=True,
    ).values('id', 'description', 'vendor')

    rows = [{'index': t['id'], 'description': t['description'], 'vendor': t['vendor'] or ''} for t in qs]

    if not rows:
        return Response({'suggestions': {}})

    categories = list(Category.objects.filter(user=request.user).values('id', 'name', 'type'))
    cat_map = {c['name']: c['id'] for c in categories}

    from .services.ai_service import batch_suggest
    names = batch_suggest(rows, categories)

    suggestions = {}
    for pk_str, name in names.items():
        cat_id = cat_map.get(name)
        if cat_id:
            Transaction.objects.filter(pk=int(pk_str), user=request.user).update(
                ai_suggested_category_id=cat_id
            )
            suggestions[pk_str] = {'name': name, 'category_id': cat_id}

    return Response({'suggestions': suggestions})


@api_view(['POST'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_suggest_for_transaction(request, pk):
    """Run AI suggestion for a single existing transaction and save it to the DB."""
    transaction = get_object_or_404(Transaction, pk=pk, user=request.user)

    if transaction.category:
        return Response({'error': 'Transaction already categorized.'}, status=400)

    categories = list(Category.objects.filter(user=request.user).values('id', 'name', 'type'))
    cat_map = {c['name']: c['id'] for c in categories}

    from .services.ai_service import suggest_category
    name = suggest_category(
        transaction.description, transaction.vendor, categories,
        transaction_type=transaction.transaction_type,
    )

    if name is None:
        return Response({'suggestion': None})

    cat_id = cat_map.get(name)
    if cat_id:
        transaction.ai_suggested_category_id = cat_id
        transaction.save(update_fields=['ai_suggested_category_id'])

    return Response({'suggestion': name, 'category_id': cat_id})


@api_view(['POST'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_accept_suggestion(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, user=request.user)

    if transaction.category:
        return Response({'error': 'Transaction already has a category.'}, status=400)

    if not transaction.ai_suggested_category:
        return Response({'error': 'No AI suggestion to accept.'}, status=400)

    transaction.category = transaction.ai_suggested_category
    transaction.save(update_fields=['category'])

    audit(request.user, AuditLog.AI_ACCEPTED, transaction=transaction,
          metadata={'category': transaction.category.name})

    return Response({'category_name': transaction.category.name})
