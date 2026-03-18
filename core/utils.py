"""
Shared utilities for the core app.
"""


def audit(user, action, transaction=None, metadata=None):
    """
    Create an AuditLog entry. Import is deferred to avoid circular imports.

    Args:
        user: the User performing the action
        action: one of AuditLog.ACTION_CHOICES values (e.g. AuditLog.EDIT)
        transaction: optional Transaction instance
        metadata: optional dict of extra context
    """
    from .models import AuditLog
    AuditLog.objects.create(
        user=user,
        transaction=transaction,
        action=action,
        metadata=metadata or {},
    )
