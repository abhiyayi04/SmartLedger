from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from core.models import Category
from core.signals import DEFAULT_CATEGORIES


class Command(BaseCommand):
    help = 'Seeds default categories for users who have none'

    def handle(self, *args, **options):
        seeded = 0
        for user in User.objects.all():
            if not Category.objects.filter(user=user).exists():
                Category.objects.bulk_create([
                    Category(user=user, name=name, type=cat_type)
                    for name, cat_type in DEFAULT_CATEGORIES
                ])
                self.stdout.write(f'  Seeded categories for: {user.username}')
                seeded += 1

        if seeded:
            self.stdout.write(self.style.SUCCESS(f'Done. Seeded {seeded} user(s).'))
        else:
            self.stdout.write('All users already have categories. Nothing to do.')
