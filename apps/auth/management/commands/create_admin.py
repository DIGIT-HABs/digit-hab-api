"""
Créer un utilisateur administrateur (role=admin, accès API + Django admin).

Usage local :
  python manage.py create_admin

Usage VPS / Docker :
  docker compose -f docker-compose.prod.yml exec web python manage.py create_admin

Avec arguments :
  python manage.py create_admin --email admin@digit-hab.sn --username admin --password "MotDePasse123!"
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Crée un utilisateur avec role=admin (is_staff + is_superuser).'

    def add_arguments(self, parser):
        parser.add_argument('--email', type=str, help='Email (obligatoire en mode --no-input)')
        parser.add_argument('--username', type=str, help='Nom d\'utilisateur (défaut : partie avant @ de l\'email)')
        parser.add_argument('--password', type=str, help='Mot de passe (défaut : demandé en interactif)')
        parser.add_argument('--first-name', type=str, default='', help='Prénom')
        parser.add_argument('--last-name', type=str, default='', help='Nom')
        parser.add_argument(
            '--no-input',
            action='store_true',
            help='Ne pas demander de saisie (email et password requis)',
        )
        parser.add_argument(
            '--update',
            action='store_true',
            help='Promouvoir un compte existant (même email) en admin',
        )

    def handle(self, *args, **options):
        User = get_user_model()
        no_input = options['no_input']

        email = options.get('email')
        if not email and no_input:
            raise CommandError('--email est obligatoire avec --no-input.')
        if not email:
            email = input('Email : ').strip()
        if not email:
            raise CommandError('Email requis.')

        username = options.get('username') or email.split('@')[0]
        base_username = username
        counter = 1
        while User.objects.filter(username=username).exclude(email=email).exists():
            username = f'{base_username}{counter}'
            counter += 1

        password = options.get('password')
        if not password and no_input:
            raise CommandError('--password est obligatoire avec --no-input.')
        if not password:
            password = self._prompt_password()

        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError('Mot de passe invalide : ' + ' '.join(exc.messages)) from exc

        first_name = options.get('first_name') or ''
        last_name = options.get('last_name') or ''

        existing = User.objects.filter(email=email).first()
        if existing and not options['update']:
            raise CommandError(
                f'Un compte existe déjà avec {email}. '
                'Utilisez --update pour le promouvoir en admin.'
            )

        if existing:
            existing.username = existing.username or username
            existing.role = 'admin'
            existing.is_staff = True
            existing.is_superuser = True
            existing.is_active = True
            if first_name:
                existing.first_name = first_name
            if last_name:
                existing.last_name = last_name
            existing.set_password(password)
            existing.save()
            user = existing
            action = 'mis à jour'
        else:
            user = User.objects.create(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                role='admin',
                is_staff=True,
                is_superuser=True,
                is_active=True,
            )
            user.set_password(password)
            user.save()
            action = 'créé'

        self.stdout.write(
            self.style.SUCCESS(
                f'Administrateur {action} : {user.get_full_name() or user.username} '
                f'({user.email}) — role={user.role}'
            )
        )

    def _prompt_password(self) -> str:
        import getpass

        while True:
            p1 = getpass.getpass('Mot de passe : ')
            p2 = getpass.getpass('Confirmer le mot de passe : ')
            if p1 != p2:
                self.stdout.write(self.style.WARNING('Les mots de passe ne correspondent pas.'))
                continue
            if not p1:
                self.stdout.write(self.style.WARNING('Le mot de passe ne peut pas être vide.'))
                continue
            return p1
