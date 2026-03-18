from django.core.exceptions import ValidationError
from django.db import models
from django.contrib.auth.models import User


class Category(models.Model):
    INCOME = 'income'
    EXPENSE = 'expense'
    TYPE_CHOICES = [
        (INCOME, 'Income'),
        (EXPENSE, 'Expense'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['type', 'name']
        unique_together = ['user', 'name']
        indexes = [
            models.Index(fields=['user', 'type']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"


class Transaction(models.Model):
    INCOME = 'income'
    EXPENSE = 'expense'
    TYPE_CHOICES = [
        (INCOME, 'Income'),
        (EXPENSE, 'Expense'),
    ]

    PENDING = 'pending'
    CLEARED = 'cleared'
    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (CLEARED, 'Cleared'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transactions')
    date = models.DateField()
    description = models.CharField(max_length=500)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    vendor = models.CharField(max_length=200, blank=True)
    transaction_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='transactions'
    )
    ai_suggested_category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ai_suggested_transactions'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['user', 'date']),
            models.Index(fields=['user', 'category']),
            models.Index(fields=['user', 'transaction_type']),
            models.Index(fields=['user', 'status']),
        ]

    def clean(self):
        errors = {}

        if self.category_id and self.user_id:
            if self.category.user_id != self.user_id:
                errors['category'] = 'Category must belong to the same user as the transaction.'
            elif self.category.type != self.transaction_type:
                errors['category'] = (
                    f'Category type "{self.category.type}" does not match '
                    f'transaction type "{self.transaction_type}".'
                )

        if self.ai_suggested_category_id and self.user_id:
            if self.ai_suggested_category.user_id != self.user_id:
                errors['ai_suggested_category'] = (
                    'AI suggested category must belong to the same user as the transaction.'
                )
            elif self.ai_suggested_category.type != self.transaction_type:
                errors['ai_suggested_category'] = (
                    f'AI suggested category type "{self.ai_suggested_category.type}" does not match '
                    f'transaction type "{self.transaction_type}".'
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.date} | {self.description} | ${self.amount}"


class AuditLog(models.Model):
    IMPORT = 'import'
    EDIT = 'edit'
    DELETE = 'delete'
    AI_ACCEPTED = 'ai_accepted'
    ACTION_CHOICES = [
        (IMPORT, 'Imported'),
        (EDIT, 'Edited'),
        (DELETE, 'Deleted'),
        (AI_ACCEPTED, 'AI Suggestion Accepted'),
    ]

    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='audit_logs'
    )
    transaction = models.ForeignKey(
        Transaction, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='audit_logs'
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
        ]

    def __str__(self):
        return f"{self.get_action_display()} by {self.user_id} at {self.created_at}"


class ImportHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='import_history')
    filename = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    total_rows = models.IntegerField(default=0)
    imported_count = models.IntegerField(default=0)
    duplicate_count = models.IntegerField(default=0)
    invalid_count = models.IntegerField(default=0)
    # List of {row_num, errors} dicts for rows that had errors
    error_details = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.filename} ({self.uploaded_at:%Y-%m-%d}) by {self.user_id}"
