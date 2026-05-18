# Generated manually — UUID object_id for GenericForeignKey targets

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='object_id',
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='notificationsubscription',
            name='object_id',
            field=models.UUIDField(blank=True, null=True),
        ),
    ]
