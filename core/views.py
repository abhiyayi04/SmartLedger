from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction as db_transaction
from django.db.models import F
from django.http import HttpResponse
from decimal import Decimal
import csv as csv_module
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
import logging
from .forms import RegisterForm, ProfileForm, CategoryForm, TransactionForm, CSVUploadForm, TransactionFilterForm
from .models import Category, ImportHistory, Transaction
from .services.dashboard_service import dashboard

logger = logging.getLogger(__name__)


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
def export_csv(request):
    logger.info("export_csv started user_id=%s params=%s", request.user.id, dict(request.GET))

    qs = Transaction.objects.filter(user=request.user).select_related('category').order_by('-date')
    filter_form = TransactionFilterForm(request.GET or None, user=request.user)

    if filter_form.is_valid():
        d = filter_form.cleaned_data
        logger.info(
            "export_csv filter valid user_id=%s has_date_from=%s has_date_to=%s has_category=%s has_type=%s has_vendor=%s has_amount_min=%s has_amount_max=%s",
            request.user.id,
            bool(d.get('date_from')),
            bool(d.get('date_to')),
            bool(d.get('category')),
            bool(d.get('type')),
            bool(d.get('vendor')),
            d.get('amount_min') is not None,
            d.get('amount_max') is not None,
        )
        if d.get('date_from'):
            qs = qs.filter(date__gte=d['date_from'])
        if d.get('date_to'):
            qs = qs.filter(date__lte=d['date_to'])
        if d.get('category'):
            qs = qs.filter(category=d['category'])
        if d.get('type'):
            qs = qs.filter(transaction_type=d['type'])
        if d.get('vendor'):
            qs = qs.filter(vendor__icontains=d['vendor'])
        if d.get('amount_min') is not None:
            qs = qs.filter(amount__gte=d['amount_min'])
        if d.get('amount_max') is not None:
            qs = qs.filter(amount__lte=d['amount_max'])
    else:
        logger.info("export_csv filter invalid or empty user_id=%s errors=%s", request.user.id, filter_form.errors)

    row_count = qs.count()
    logger.info("export_csv writing rows user_id=%s row_count=%s", request.user.id, row_count)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="transactions.csv"'
    writer = csv_module.writer(response)
    writer.writerow(['Date', 'Description', 'Amount', 'Vendor', 'Type', 'Category'])
    for t in qs:
        sign = '-' if t.transaction_type == Transaction.EXPENSE else ''
        writer.writerow([
            t.date.isoformat(),
            t.description,
            f"{sign}{t.amount}",
            t.vendor,
            t.get_transaction_type_display(),
            t.category.name if t.category else '',
        ])

    logger.info("export_csv completed user_id=%s rows_written=%s", request.user.id, row_count)
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


def _safe_back(url):
    """Return url only if it is a safe local path (starts with '/' but not '//').
    Rejects protocol-relative URLs like //evil.com which would be off-site redirects."""
    if url and url.startswith('/') and not url.startswith('//'):
        return url
    return ''


@login_required
def transaction_edit(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, user=request.user)
    back = _safe_back(request.GET.get('back', '') or request.POST.get('back', ''))
    if request.method == 'POST':
        form = TransactionForm(request.POST, instance=transaction, user=request.user)
        if form.is_valid():
            t = form.save()
            messages.success(request, 'Transaction updated.')
            return redirect(back or 'transaction_list')
    else:
        form = TransactionForm(instance=transaction, user=request.user)
    return render(request, 'transactions/form.html', {
        'form': form, 'action': 'Edit', 'transaction': transaction, 'back': back,
    })


@login_required
def transaction_delete(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, user=request.user)
    back = _safe_back(request.GET.get('back', '') or request.POST.get('back', ''))
    if request.method == 'POST':
        transaction.delete()
        messages.success(request, 'Transaction deleted.')
        return redirect(back or 'transaction_list')
    return render(request, 'transactions/confirm_delete.html', {'transaction': transaction, 'back': back})


@login_required
def csv_upload(request):
    logger.info("csv_upload started user_id=%s method=%s", request.user.id, request.method)

    if request.method == 'POST':
        file_present = 'file' in request.FILES
        logger.info("csv_upload file_present=%s user_id=%s", file_present, request.user.id)

        form = CSVUploadForm(request.POST, request.FILES)
        if form.is_valid():
            filename = request.FILES['file'].name
            logger.info("csv_upload form valid filename=%s user_id=%s", filename, request.user.id)

            from .services.csv_service import parse_csv, detect_duplicates
            try:
                rows = parse_csv(request.FILES['file'])
                logger.info("csv_upload parse_csv completed filename=%s total_rows=%s user_id=%s", filename, len(rows), request.user.id)

                rows = detect_duplicates(rows, request.user)
                logger.info("csv_upload detect_duplicates completed filename=%s user_id=%s", filename, request.user.id)

                from .models import _normalize_vendor as _nv
                to_import = [
                    Transaction(
                        user=request.user,
                        date=row['date'],
                        description=row['description'],
                        amount=Decimal(row['amount']),
                        vendor=row['vendor'],
                        normalized_vendor=_nv(row['vendor']),
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

                logger.info(
                    "csv_upload row summary user_id=%s filename=%s total_rows=%s to_import=%s duplicate_count=%s error_count=%s",
                    request.user.id, filename, len(rows), len(to_import), duplicate_count, error_count,
                )

                if to_import:
                    with db_transaction.atomic():
                        Transaction.objects.bulk_create(to_import)
                    logger.info("csv_upload bulk_create completed user_id=%s inserted=%s filename=%s", request.user.id, len(to_import), filename)
                else:
                    logger.info("csv_upload bulk_create skipped nothing to import user_id=%s filename=%s", request.user.id, filename)

                history = ImportHistory.objects.create(
                    user=request.user,
                    filename=request.FILES['file'].name,
                    total_rows=len(rows),
                    imported_count=len(to_import),
                    duplicate_count=duplicate_count,
                    invalid_count=error_count,
                    error_details=error_details,
                )
                logger.info("csv_upload import history created history_id=%s user_id=%s filename=%s", history.pk, request.user.id, filename)
                logger.info("csv_upload redirecting to import_history_detail history_id=%s user_id=%s", history.pk, request.user.id)
                return redirect('import_history_detail', pk=history.pk)
            except ValueError as e:
                logger.warning("csv_upload ValueError user_id=%s filename=%s error=%s", request.user.id, request.FILES['file'].name, e)
                messages.error(request, str(e))
        else:
            logger.warning("csv_upload form invalid user_id=%s errors=%s", request.user.id, form.errors)
    else:
        form = CSVUploadForm()

    logger.info("csv_upload rendering upload form user_id=%s", request.user.id)
    return render(request, 'transactions/csv_upload.html', {'form': form})


@login_required
def import_history_list(request):
    logger.info("import_history_list started user_id=%s", request.user.id)
    history = ImportHistory.objects.filter(user=request.user)
    record_count = history.count()
    logger.info("import_history_list completed user_id=%s record_count=%s", request.user.id, record_count)
    return render(request, 'transactions/import_history_list.html', {'history': history})


@login_required
def import_history_detail(request, pk):
    logger.info("import_history_detail started user_id=%s history_id=%s", request.user.id, pk)
    record = get_object_or_404(ImportHistory, pk=pk, user=request.user)
    logger.info(
        "import_history_detail record loaded history_id=%s user_id=%s imported_count=%s duplicate_count=%s invalid_count=%s",
        pk, request.user.id, record.imported_count, record.duplicate_count, record.invalid_count,
    )
    logger.info("import_history_detail completed user_id=%s history_id=%s", request.user.id, pk)
    return render(request, 'transactions/import_history_detail.html', {'record': record})


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


@login_required
def batch_accept_suggestions(request):
    """
    Bulk-accept all AI suggestions for the current user where:
      - category is null
      - ai_suggested_category is not null
    Does NOT generate new suggestions. Does NOT overwrite existing categories.
    """
    logger.info("batch_accept_suggestions started user_id=%s method=%s", request.user.id, request.method)

    if request.method != 'POST':
        logger.warning("batch_accept_suggestions rejected non-POST user_id=%s method=%s", request.user.id, request.method)
        return redirect('transaction_list')

    back = _safe_back(request.POST.get('back', ''))

    qs = Transaction.objects.filter(
        user=request.user,
        category__isnull=True,
        ai_suggested_category__isnull=False,
    )

    count = qs.count()
    logger.info("batch_accept_suggestions eligible_count=%s user_id=%s", count, request.user.id)

    if count:
        qs.update(category_id=F('ai_suggested_category_id'))
        logger.info("batch_accept_suggestions updated user_id=%s updated_count=%s", request.user.id, count)

        messages.success(
            request,
            f'Accepted {count} AI suggestion{"s" if count != 1 else ""}.',
        )
    else:
        logger.info("batch_accept_suggestions no eligible transactions user_id=%s", request.user.id)
        messages.info(request, 'No pending AI suggestions to accept.')

    logger.info("batch_accept_suggestions completed user_id=%s", request.user.id)
    return redirect(back or 'transaction_list')


@api_view(['POST'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_suggest_category(request):
    logger.info("api_suggest_category started user_id=%s", request.user.id)

    description = request.data.get('description', '').strip()
    vendor = request.data.get('vendor', '').strip()

    if not description:
        logger.warning("api_suggest_category rejected: missing description user_id=%s", request.user.id)
        return Response({'error': 'description is required'}, status=400)

    categories = list(Category.objects.filter(user=request.user).values('id', 'name', 'type'))
    logger.info("api_suggest_category category_count=%s user_id=%s", len(categories), request.user.id)

    cat_map = {c['name']: c['id'] for c in categories}

    from .services.ai_service import suggest_category
    name = suggest_category(description, vendor, categories)

    if name is None:
        logger.info("api_suggest_category no suggestion returned user_id=%s", request.user.id)
        return Response({'suggestion': None})

    logger.info("api_suggest_category suggestion=%r category_id=%s user_id=%s", name, cat_map.get(name), request.user.id)
    return Response({'suggestion': name, 'category_id': cat_map.get(name)})


@api_view(['POST'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_suggest_uncategorized(request):
    """
    Run AI suggestions on all transactions for this user that have no category
    and no existing ai_suggested_category. Saves suggestions to the DB and
    returns {pk: {name, category_id}} for the caller to update the UI.
    """
    logger.info("api_suggest_uncategorized started user_id=%s", request.user.id)

    qs = Transaction.objects.filter(
        user=request.user,
        category__isnull=True,
        ai_suggested_category__isnull=True,
    ).values('id', 'description', 'vendor')

    rows = [{'index': t['id'], 'description': t['description'], 'vendor': t['vendor'] or ''} for t in qs]

    logger.info("api_suggest_uncategorized eligible_row_count=%s user_id=%s", len(rows), request.user.id)

    if not rows:
        logger.info("api_suggest_uncategorized no eligible transactions user_id=%s", request.user.id)
        return Response({'suggestions': {}})

    categories = list(Category.objects.filter(user=request.user).values('id', 'name', 'type'))
    logger.info("api_suggest_uncategorized category_count=%s user_id=%s", len(categories), request.user.id)

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

    logger.info("api_suggest_uncategorized completed user_id=%s saved_count=%s", request.user.id, len(suggestions))
    return Response({'suggestions': suggestions})


@api_view(['POST'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_suggest_for_transaction(request, pk):
    """Run AI suggestion for a single existing transaction and save it to the DB."""
    logger.info("api_suggest_for_transaction started user_id=%s transaction_pk=%s", request.user.id, pk)

    transaction = get_object_or_404(Transaction, pk=pk, user=request.user)

    if transaction.category:
        logger.warning("api_suggest_for_transaction rejected: already categorized user_id=%s transaction_pk=%s", request.user.id, pk)
        return Response({'error': 'Transaction already categorized.'}, status=400)

    categories = list(Category.objects.filter(user=request.user).values('id', 'name', 'type'))
    logger.info("api_suggest_for_transaction category_count=%s user_id=%s transaction_pk=%s", len(categories), request.user.id, pk)

    cat_map = {c['name']: c['id'] for c in categories}

    from .services.ai_service import suggest_category
    name = suggest_category(
        transaction.description, transaction.vendor, categories,
        transaction_type=transaction.transaction_type,
    )

    if name is None:
        logger.info("api_suggest_for_transaction no suggestion returned user_id=%s transaction_pk=%s", request.user.id, pk)
        return Response({'suggestion': None})

    cat_id = cat_map.get(name)
    if cat_id:
        transaction.ai_suggested_category_id = cat_id
        transaction.save(update_fields=['ai_suggested_category_id'])

    logger.info("api_suggest_for_transaction completed user_id=%s transaction_pk=%s suggestion=%r category_id=%s", request.user.id, pk, name, cat_id)
    return Response({'suggestion': name, 'category_id': cat_id})


@api_view(['POST'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_accept_suggestion(request, pk):
    logger.info("api_accept_suggestion started user_id=%s transaction_pk=%s", request.user.id, pk)

    transaction = get_object_or_404(Transaction, pk=pk, user=request.user)

    if transaction.category:
        logger.warning("api_accept_suggestion rejected: already has category user_id=%s transaction_pk=%s", request.user.id, pk)
        return Response({'error': 'Transaction already has a category.'}, status=400)

    if not transaction.ai_suggested_category:
        logger.warning("api_accept_suggestion rejected: no AI suggestion user_id=%s transaction_pk=%s", request.user.id, pk)
        return Response({'error': 'No AI suggestion to accept.'}, status=400)

    transaction.category = transaction.ai_suggested_category
    transaction.save(update_fields=['category'])

    logger.info("api_accept_suggestion completed user_id=%s transaction_pk=%s category_name=%r", request.user.id, pk, transaction.category.name)
    return Response({'category_name': transaction.category.name})
