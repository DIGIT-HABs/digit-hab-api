# UUID object_id — drop indexes/constraints, convert, recreate (PostgreSQL).

from django.db import migrations, models


def _column_udt(schema_editor, table, column):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT udt_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
            """,
            [table, column],
        )
        row = cursor.fetchone()
        return row[0] if row else None


def migrate_object_id_to_uuid(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    # notification — index composite (content_type_id, object_id)
    schema_editor.execute(
        'DROP INDEX IF EXISTS notificatio_content_0c2d97_idx'
    )
    if _column_udt(schema_editor, 'notification', 'object_id') != 'uuid':
        schema_editor.execute('UPDATE notification SET object_id = NULL')
        schema_editor.execute(
            'ALTER TABLE notification '
            'ALTER COLUMN object_id TYPE uuid USING NULL::uuid'
        )
    schema_editor.execute(
        'CREATE INDEX IF NOT EXISTS notificatio_content_0c2d97_idx '
        'ON notification (content_type_id, object_id)'
    )

    # notification_subscription — unique_together inclut object_id
    schema_editor.execute("""
        DO $$
        DECLARE r RECORD;
        BEGIN
            FOR r IN (
                SELECT c.conname
                FROM pg_constraint c
                JOIN pg_class t ON c.conrelid = t.oid
                WHERE t.relname = 'notification_subscription'
                  AND c.contype = 'u'
            ) LOOP
                EXECUTE format(
                    'ALTER TABLE notification_subscription DROP CONSTRAINT %I',
                    r.conname
                );
            END LOOP;
        END $$;
    """)
    if _column_udt(schema_editor, 'notification_subscription', 'object_id') != 'uuid':
        schema_editor.execute('UPDATE notification_subscription SET object_id = NULL')
        schema_editor.execute(
            'ALTER TABLE notification_subscription '
            'ALTER COLUMN object_id TYPE uuid USING NULL::uuid'
        )
    schema_editor.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'notification_subscription_user_channel_content_object_uniq'
            ) THEN
                ALTER TABLE notification_subscription
                ADD CONSTRAINT notification_subscription_user_channel_content_object_uniq
                UNIQUE (user_id, channel_name, content_type_id, object_id);
            END IF;
        END $$;
        """
    )


def migrate_object_id_to_integer(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    schema_editor.execute(
        'DROP INDEX IF EXISTS notificatio_content_0c2d97_idx'
    )
    schema_editor.execute(
        'ALTER TABLE notification_subscription '
        'DROP CONSTRAINT IF EXISTS notification_subscription_user_channel_content_object_uniq'
    )
    schema_editor.execute('UPDATE notification SET object_id = NULL')
    schema_editor.execute('UPDATE notification_subscription SET object_id = NULL')
    schema_editor.execute(
        'ALTER TABLE notification '
        'ALTER COLUMN object_id TYPE integer USING NULL::integer'
    )
    schema_editor.execute(
        'ALTER TABLE notification_subscription '
        'ALTER COLUMN object_id TYPE integer USING NULL::integer'
    )
    schema_editor.execute(
        'CREATE INDEX notificatio_content_0c2d97_idx '
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
