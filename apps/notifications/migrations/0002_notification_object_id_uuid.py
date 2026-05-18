# UUID object_id — PostgreSQL ne peut pas caster integer → uuid directement.

from django.db import migrations, models


def _pg_tables():
    return ('notification', 'notification_subscription')


def migrate_object_id_to_uuid(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for table in _pg_tables():
        schema_editor.execute(f'UPDATE {table} SET object_id = NULL')
        schema_editor.execute(
            f'ALTER TABLE {table} '
            f'ALTER COLUMN object_id TYPE uuid USING NULL::uuid'
        )


def migrate_object_id_to_integer(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for table in _pg_tables():
        schema_editor.execute(f'UPDATE {table} SET object_id = NULL')
        schema_editor.execute(
            f'ALTER TABLE {table} '
            f'ALTER COLUMN object_id TYPE integer USING NULL::integer'
        )


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0001_initial'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    migrate_object_id_to_uuid,
                    migrate_object_id_to_integer,
                ),
            ],
            state_operations=[
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
            ],
        ),
    ]
