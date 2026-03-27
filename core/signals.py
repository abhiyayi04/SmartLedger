from django.db.models.signals import post_save
from django.contrib.auth.models import User
from django.dispatch import receiver

DEFAULT_CATEGORIES = [
    ('Revenue', 'income'),
    ('Rent', 'expense'),
    ('Food & Dining', 'expense'),
    ('Groceries', 'expense'),
    ('Transportation', 'expense'),
    ('Entertainment', 'expense'),
    ('Shopping', 'expense'),
    ('Utilities', 'expense'),
    ('Subscriptions', 'expense'),
    ('Miscellaneous', 'expense'),
]


@receiver(post_save, sender=User)
def seed_default_categories(sender, instance, created, **kwargs):
    if created:
        from core.models import Category
        Category.objects.bulk_create([
            Category(user=instance, name=name, type=cat_type)
            for name, cat_type in DEFAULT_CATEGORIES
        ])
