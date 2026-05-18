# UUID object_id — remplace la colonne integer (évite ALTER TYPE / conflits d'index).

from django.db import migrations, models


def _column_is_uuid(schema_editor, table):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT udt_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s AND column_name = 'object_id'
            """,
            [table],
        )
        row = cursor.fetchone()
        return row and row[0] == 'uuid'


def _drop_indexes_on_column(schema_editor, table, column):
    schema_editor.execute(
        f"""
        DO $dropidx$
        DECLARE r RECORD;
        BEGIN
            FOR r IN (
                SELECT indexname FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = '{table}'
                  AND indexdef LIKE '%{column}%'
            ) LOOP
                EXECUTE format('DROP INDEX IF EXISTS %I', r.indexname);
            END LOOP;
        END $dropidx$;
        """
    )


def _drop_unique_constraints(schema_editor, table):
    schema_editor.execute(
        f"""
        DO $dropuniq$
        DECLARE r RECORD;
        BEGIN
            FOR r IN (
                SELECT c.conname FROM pg_constraint c
                JOIN pg_class t ON c.conrelid = t.oid
                WHERE t.relname = '{table}' AND c.contype = 'u'
            ) LOOP
                EXECUTE format(
                    'ALTER TABLE {table} DROP CONSTRAINT %I', r.conname
                );
            END LOOP;
        END $dropuniq$;
        """
    )


def _replace_object_id_column(schema_editor, table):
    if _column_is_uuid(schema_editor, table):
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s AND column_name = 'object_id_new'
            """,
            [table],
        )
        has_new = cursor.fetchone() is not None
    if not has_new:
        schema_editor.execute(
            f'ALTER TABLE {table} ADD COLUMN object_id_new uuid NULL'
        )
    schema_editor.execute(f'ALTER TABLE {table} DROP COLUMN IF EXISTS object_id')
    schema_editor.execute(
        f'ALTER TABLE {table} RENAME COLUMN object_id_new TO object_id'
    )


def migrate_object_id_to_uuid(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    _drop_indexes_on_column(schema_editor, 'notification', 'object_id')
    _replace_object_id_column(schema_editor, 'notification')
    schema_editor.execute(
        'CREATE INDEX IF NOT EXISTS notificatio_content_0c2d97_idx '
        'ON notification (content_type_id, object_id)'
    )

    _drop_unique_constraints(schema_editor, 'notification_subscription')
    _drop_indexes_on_column(schema_editor, 'notification_subscription', 'object_id')
    _replace_object_id_column(schema_editor, 'notification_subscription')
    schema_editor.execute(
        """
        DO $adduniq$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'notification_subscription_user_channel_content_object_uniq'
            ) THEN
                ALTER TABLE notification_subscription
                ADD CONSTRAINT notification_subscription_user_channel_content_object_uniq
                UNIQUE (user_id, channel_name, content_type_id, object_id);
            END IF;
        END $adduniq$;
        """
    )


def migrate_object_id_to_integer(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    _drop_indexes_on_column(schema_editor, 'notification', 'object_id')
    _drop_unique_constraints(schema_editor, 'notification_subscription')
    _drop_indexes_on_column(schema_editor, 'notification_subscription', 'object_id')

    for table in ('notification', 'notification_subscription'):
        if _column_is_uuid(schema_editor, table):
            schema_editor.execute(
                f'ALTER TABLE {table} ADD COLUMN object_id_new integer NULL'
            )
            schema_editor.execute(f'ALTER TABLE {table} DROP COLUMN object_id')
            schema_editor.execute(
                f'ALTER TABLE {table} RENAME COLUMN object_id_new TO object_id'
            )

    schema_editor.execute(
        'CREATE INDEX IF NOT EXISTS notificatio_content_0c2d97_idx '
        'ON notification (content_type_id, object_id)'
    )
    schema_editor.execute(
        'ALTER TABLE notification_subscription '
        'ADD CONSTRAINT notification_subscription_user_channel_content_object_uniq '
        'UNIQUE (user_id, channel_name, content_type_id, object_id)'
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
