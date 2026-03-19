from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_add_normalized_vendor'),
    ]

    operations = [
        migrations.DeleteModel(
            name='AuditLog',
        ),
    ]
