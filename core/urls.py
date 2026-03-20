from django.urls import path
from . import views

urlpatterns = [
    path('', views.homepage, name='homepage'),
    path('register/', views.register, name='register'),
    path('profile/', views.profile_edit, name='profile'),
    path('dashboard/', views.dashboard, name='dashboard'),
    # Transactions
    path('transactions/', views.transaction_list, name='transaction_list'),
    path('transactions/add/', views.transaction_add, name='transaction_add'),
    path('transactions/<int:pk>/edit/', views.transaction_edit, name='transaction_edit'),
    path('transactions/<int:pk>/delete/', views.transaction_delete, name='transaction_delete'),
    path('transactions/batch-accept-suggestions/', views.batch_accept_suggestions, name='batch_accept_suggestions'),
    path('transactions/upload/', views.csv_upload, name='csv_upload'),
    path('transactions/export/', views.export_csv, name='export_csv'),
    path('transactions/imports/', views.import_history_list, name='import_history_list'),
    path('transactions/imports/<int:pk>/', views.import_history_detail, name='import_history_detail'),
    # AI API
    path('api/suggest-category/', views.api_suggest_category, name='api_suggest_category'),
    path('api/suggest-uncategorized/', views.api_suggest_uncategorized, name='api_suggest_uncategorized'),
    path('api/suggest-for-transaction/<int:pk>/', views.api_suggest_for_transaction, name='api_suggest_for_transaction'),
    path('api/accept-suggestion/<int:pk>/', views.api_accept_suggestion, name='api_accept_suggestion'),
    # Categories
    path('categories/', views.category_list, name='category_list'),
    path('categories/add/', views.category_add, name='category_add'),
    path('categories/<int:pk>/edit/', views.category_edit, name='category_edit'),
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),
]
