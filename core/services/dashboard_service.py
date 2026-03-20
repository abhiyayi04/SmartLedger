import logging

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from collections import OrderedDict
from decimal import Decimal

from ..models import Transaction
from ..forms import DashboardFilterForm

logger = logging.getLogger(__name__)


@login_required
def dashboard(request):
    logger.info("Dashboard view started user_id=%s params=%s", request.user.id, dict(request.GET))

    filter_form = DashboardFilterForm(request.GET or None)
    date_from = None
    date_to = None
    if filter_form.is_valid():
        date_from = filter_form.cleaned_data.get('date_from')
        date_to = filter_form.cleaned_data.get('date_to')
        logger.info("Dashboard filter valid user_id=%s date_from=%s date_to=%s", request.user.id, date_from, date_to)
    else:
        logger.warning(
            "Dashboard filter invalid user_id=%s errors=%s non_field_errors=%s raw_params=%s",
            request.user.id,
            filter_form.errors,
            filter_form.non_field_errors(),
            dict(request.GET),
        )

    qs = Transaction.objects.filter(user=request.user)
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)

    filtered_count = qs.count()
    logger.info("Dashboard queryset filtered user_id=%s transaction_count=%s", request.user.id, filtered_count)

    # KPI totals
    income_total = qs.filter(transaction_type=Transaction.INCOME).aggregate(
        total=Sum('amount'))['total'] or Decimal('0')
    expense_total = qs.filter(transaction_type=Transaction.EXPENSE).aggregate(
        total=Sum('amount'))['total'] or Decimal('0')
    net_cash_flow = income_total - expense_total

    logger.info("Dashboard KPIs user_id=%s income=%s expense=%s net_cash_flow=%s", request.user.id, income_total, expense_total, net_cash_flow)

    # Uncategorized (always all-time so the alert is always visible)
    uncategorized_count = Transaction.objects.filter(
        user=request.user, category__isnull=True).count()

    logger.info("Dashboard uncategorized user_id=%s uncategorized_count=%s", request.user.id, uncategorized_count)

    # Recent 10 transactions
    recent_transactions = qs.select_related('category').order_by('-date', '-created_at')[:10]

    logger.info("Dashboard recent transactions user_id=%s fetched=%s", request.user.id, len(recent_transactions))

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

    # Top 5 vendors by expense spend (group by normalized vendor for consistency)
    top_vendors = (
        qs.filter(transaction_type=Transaction.EXPENSE)
        .exclude(normalized_vendor='')
        .values('normalized_vendor')
        .annotate(total=Sum('amount'))
        .order_by('-total')[:5]
    )

    logger.info("Dashboard grouped data user_id=%s expense_categories=%s monthly_rows=%s top_vendors=%s", request.user.id, len(expense_by_cat), len(monthly_qs), len(top_vendors))

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
            'labels': [item['normalized_vendor'] for item in top_vendors],
            'data': [float(item['total']) for item in top_vendors],
        },
    }

    logger.info("Dashboard chart_data built user_id=%s category_pie_labels=%s monthly_labels=%s vendor_labels=%s", request.user.id, len(chart_data['category_pie']['labels']), len(chart_data['monthly']['labels']), len(chart_data['vendors']['labels']))

    logger.info("Dashboard processing completed user_id=%s", request.user.id)

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
