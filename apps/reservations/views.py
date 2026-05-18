"""
Views for reservations management API.
"""

import logging

from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction, models
from django.db.models import Q, Count, Sum, Avg
from django.utils import timezone
from django.shortcuts import get_object_or_404
from apps.auth.models import User
from apps.properties.models import Property
from apps.crm.models import ClientProfile
from .models import Reservation, Payment, ReservationActivity, Contract, ContractTemplate
from .serializers import (
    ReservationSerializer, ReservationCreateSerializer, ReservationUpdateSerializer,
    ReservationStatusUpdateSerializer, PaymentSerializer, PaymentCreateSerializer,
    PaymentStatusUpdateSerializer, ReservationActivitySerializer,
    ReservationStatsSerializer,
    ContractSerializer, ContractCreateSerializer, ContractUpdateSerializer,
    ContractTemplateSerializer
)
from .permissions import (
    IsReservationOwnerOrAgent, CanManageReservations, CanViewAllReservations,
    CanAccessPaymentData, CanProcessPayments, IsAgencyMember,
    CanScheduleVisits, CanModifyReservationStatus, ReadOnly,
    IsContractOwnerOrAgent, CanManageContracts
)
from .services import PaymentService, NotificationService
from .contract_pdf import save_contract_pdf_to_field

logger = logging.getLogger(__name__)


class ReservationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing reservations.
    """
    
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = {
        'status': ['exact', 'in'],
        'reservation_type': ['exact', 'in'],
        'property': ['exact'],
        'client_profile': ['exact'],
        'assigned_agent': ['exact'],
        'scheduled_date': ['gte', 'lte', 'date'],
        'payment_status': ['exact', 'in'],
        'payment_required': ['exact'],
    }
    search_fields = [
        'client_name', 'client_email', 'client_phone', 'client_company',
        'property__title', 'property__address_line1', 'property__city'
    ]
    ordering_fields = [
        'created_at', 'scheduled_date', 'status', 'payment_status',
        'amount', 'property__price'
    ]
    ordering = ['-created_at']
    
    def get_queryset(self):
        """Get reservations based on user permissions."""
        user = self.request.user
        
        # Check if user is authenticated
        if not user.is_authenticated:
            return Reservation.objects.none()
        
        # Staff and superusers see all reservations
        if user.is_staff or user.is_superuser:
            return Reservation.objects.all().select_related(
                'property', 'client_profile__user', 'assigned_agent', 'created_by'
            ).prefetch_related('payments')
        
        # Agents see reservations for their agency
        if user.role in ['agent', 'manager']:
            user_agency = getattr(getattr(user, 'profile', None), 'agency', None)
            if user_agency:
                return Reservation.objects.filter(
                    property__agency=user_agency
                ).select_related(
                    'property', 'client_profile__user', 'assigned_agent', 'created_by'
                ).prefetch_related('payments')
        
        # Clients see only their own reservations (by profile, email or created_by)
        if user.role == 'client':
            client_profile = getattr(user, 'client_profile', None)
            base = Reservation.objects.select_related(
                'property', 'client_profile__user', 'assigned_agent', 'created_by'
            ).prefetch_related('payments')
            if client_profile:
                return base.filter(
                    Q(client_profile=client_profile)
                    | Q(client_email=user.email)
                    | Q(created_by=user)
                )
            return base.filter(Q(client_email=user.email) | Q(created_by=user))
        
        return Reservation.objects.none()
    
    def get_serializer_class(self):
        """Return appropriate serializer class."""
        if self.action == 'create':
            return ReservationCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return ReservationUpdateSerializer
        elif self.action == 'status_update':
            return ReservationStatusUpdateSerializer
        return ReservationSerializer
    
    def get_permissions(self):
        """Get permissions for different actions."""
        if self.action in ['list', 'retrieve']:
            permission_classes = [CanViewAllReservations | ReadOnly]
        elif self.action in ['create', 'my_reservations', 'activities']:
            permission_classes = [IsAuthenticated]
        elif self.action in ['update', 'partial_update', 'destroy']:
            permission_classes = [IsReservationOwnerOrAgent | CanManageReservations]
        elif self.action in ['confirm', 'cancel', 'complete']:
            permission_classes = [IsReservationOwnerOrAgent | CanModifyReservationStatus]
        else:
            permission_classes = [CanManageReservations]
        
        return [permission() for permission in permission_classes]
    
    def perform_create(self, serializer):
        """Create reservation and log activity."""
        with transaction.atomic():
            reservation = serializer.save()
            user = self.request.user
            # Log activity
            ReservationActivity.objects.create(
                reservation=reservation,
                activity_type='created',
                description=f"Réservation créée par {self.request.user.get_full_name()}",
                performed_by=self.request.user
            )
            # If a "client" user creates a reservation, automatically create/attach a CRM ClientProfile to this account and link it to the reservation.
            if user.role == 'client' and not reservation.client_profile:
                client_profile, _ = ClientProfile.objects.get_or_create(
                    user=user,
                    defaults={
                        'preferred_contact_method': getattr(user, 'preferred_contact_method', 'email') or 'email',
                        'status': 'prospect',
                        'priority_level': 'medium',
                    },
                )
                reservation.client_profile = client_profile
                reservation.save()

            # Send notification if it's a visit reservation
            if reservation.reservation_type == 'visit':
                NotificationService.send_visit_confirmation(reservation)
            # In-app notification: new reservation (agent + client if has account)
            NotificationService.send_in_app_reservation_created(reservation)
    
    def perform_update(self, serializer):
        """Update reservation and log activity."""
        old_instance = self.get_object()
        with transaction.atomic():
            reservation = serializer.save()
            
            # Log activity for significant changes
            if old_instance.status != reservation.status:
                ReservationActivity.objects.create(
                    reservation=reservation,
                    activity_type='status_changed',
                    description=f"Statut modifié de '{old_instance.get_status_display()}' vers '{reservation.get_status_display()}'",
                    old_value=old_instance.status,
                    new_value=reservation.status,
                    performed_by=self.request.user
                )
            else:
                ReservationActivity.objects.create(
                    reservation=reservation,
                    activity_type='updated',
                    description="Réservation modifiée",
                    performed_by=self.request.user
                )
    
    @action(detail=True, methods=['post'], permission_classes=[IsReservationOwnerOrAgent])
    def confirm(self, request, pk=None):
        """Confirm a reservation."""
        reservation = self.get_object()
        
        # Check if user can confirm
        if not reservation.can_be_confirmed_by(request.user):
            return Response(
                {'error': 'Vous n\'êtes pas autorisé à confirmer cette réservation.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        with transaction.atomic():
            reservation.confirm(user=request.user)
            
            # Log activity
            ReservationActivity.objects.create(
                reservation=reservation,
                activity_type='confirmed',
                description=f"Réservation confirmée par {request.user.get_full_name()}",
                performed_by=request.user
            )
            
            # Update property status if it's a purchase
            if reservation.reservation_type == 'purchase':
                reservation.property.status = 'reserved'
                reservation.property.save()
            
            # Send confirmation notification
            NotificationService.send_confirmation_notification(reservation)
            NotificationService.send_in_app_reservation_confirmed(reservation)
        
        serializer = self.get_serializer(reservation)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'], permission_classes=[IsReservationOwnerOrAgent])
    def cancel(self, request, pk=None):
        """Cancel a reservation."""
        reservation = self.get_object()
        reason = request.data.get('reason', '')
        
        # Check if user can cancel
        if not reservation.can_be_cancelled_by(request.user):
            return Response(
                {'error': 'Vous n\'êtes pas autorisé à annuler cette réservation.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        with transaction.atomic():
            reservation.cancel(reason=reason, user=request.user)
            
            # Log activity
            ReservationActivity.objects.create(
                reservation=reservation,
                activity_type='cancelled',
                description=f"Réservation annulée par {request.user.get_full_name()}" + 
                           (f". Raison: {reason}" if reason else ""),
                performed_by=request.user
            )
            
            # Update property status back to available
            if reservation.property.status == 'reserved':
                reservation.property.status = 'available'
                reservation.property.save()
            
            # Send cancellation notification
            NotificationService.send_cancellation_notification(reservation, reason)
            NotificationService.send_in_app_reservation_cancelled(reservation, reason)
        
        serializer = self.get_serializer(reservation)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'], permission_classes=[IsReservationOwnerOrAgent])
    def complete(self, request, pk=None):
        """Mark reservation as completed."""
        reservation = self.get_object()
        notes = request.data.get('notes', '')
        
        with transaction.atomic():
            reservation.complete(notes=notes)

            ReservationActivity.objects.create(
                reservation=reservation,
                activity_type='completed',
                description=f"Réservation marquée comme terminée par {request.user.get_full_name()}",
                performed_by=request.user
            )

            try:
                from apps.commissions.services import create_commission_for_reservation
                create_commission_for_reservation(
                    reservation,
                    source='reservation_completed',
                )
            except Exception:
                logger.exception(
                    'Échec création commission pour réservation %s',
                    reservation.pk,
                )
        
        serializer = self.get_serializer(reservation)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def activities(self, request, pk=None):
        """Get reservation activity log. Access follows get_queryset() (owner/agent/client_email/created_by)."""
        reservation = self.get_object()
        activities = reservation.activities.select_related('performed_by').order_by('-created_at')
        serializer = ReservationActivitySerializer(activities, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def stats(self, request):
        """Get reservation statistics. Returns stats based on user's permissions."""
        queryset = self.get_queryset()
        
        # Calculate statistics
        total_reservations = queryset.count()
        pending_reservations = queryset.filter(status='pending').count()
        confirmed_reservations = queryset.filter(status='confirmed').count()
        completed_reservations = queryset.filter(status='completed').count()
        cancelled_reservations = queryset.filter(status='cancelled').count()
        
        total_revenue = queryset.filter(
            status__in=['completed', 'confirmed'],
            amount__isnull=False
        ).aggregate(
            total=models.Sum('amount')
        )['total'] or 0
        
        avg_booking_value = (
            queryset.filter(
                status__in=['completed', 'confirmed'],
                amount__isnull=False
            ).aggregate(
                avg=models.Avg('amount')
            )['avg'] or 0
        )
        
        conversion_rate = (
            (completed_reservations / total_reservations * 100) 
            if total_reservations > 0 else 0
        )
        
        stats = {
            'total_reservations': total_reservations,
            'pending_reservations': pending_reservations,
            'confirmed_reservations': confirmed_reservations,
            'completed_reservations': completed_reservations,
            'cancelled_reservations': cancelled_reservations,
            'total_revenue': total_revenue,
            'avg_booking_value': avg_booking_value,
            'conversion_rate': round(conversion_rate, 2)
        }
        
        serializer = ReservationStatsSerializer(stats)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='my-reservations', permission_classes=[IsAuthenticated])
    def my_reservations(self, request):
        """Get current user's reservations."""
        user = request.user
        
        # Check if user is authenticated (should be guaranteed by permission_classes)
        if not user.is_authenticated:
            return Response(
                {'error': 'Authentication required'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        if user.role == 'client':
            client_profile = getattr(user, 'client_profile', None)
            base = Reservation.objects.select_related(
                'property', 'client_profile__user', 'assigned_agent', 'created_by'
            ).prefetch_related('payments')
            if client_profile:
                queryset = base.filter(
                    Q(client_profile=client_profile)
                    | Q(client_email=user.email)
                    | Q(created_by=user)
                )
            else:
                queryset = base.filter(
                    Q(client_email=user.email) | Q(created_by=user)
                )
        else:
            queryset = Reservation.objects.filter(
                assigned_agent=user
            ).select_related(
                'property', 'client_profile__user', 'assigned_agent', 'created_by'
            ).prefetch_related('payments')
        
        # Apply filters
        queryset = self.filter_queryset(queryset)
        page = self.paginate_queryset(queryset)
        
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class PaymentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing payments.
    """
    
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated, CanAccessPaymentData]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = {
        'reservation': ['exact'],
        'status': ['exact', 'in'],
        'payment_method': ['exact', 'in'],
        'created_at': ['gte', 'lte', 'date'],
    }
    search_fields = ['reservation__client_name', 'reservation__client_email', 'description']
    ordering_fields = ['created_at', 'amount', 'status']
    ordering = ['-created_at']
    
    def get_queryset(self):
        """Get payments based on user permissions."""
        user = self.request.user
        
        # Check if user is authenticated
        if not user.is_authenticated:
            return Payment.objects.none()
        
        # Staff and superusers see all payments
        if user.is_staff or user.is_superuser:
            return Payment.objects.all().select_related('reservation__property', 'reservation__client_profile__user')
        
        # Agents see payments for their agency's reservations
        if user.role in ['agent', 'manager']:
            user_agency = getattr(getattr(user, 'profile', None), 'agency', None)
            if user_agency:
                return Payment.objects.filter(
                    reservation__property__agency=user_agency
                ).select_related('reservation__property', 'reservation__client_profile__user')
        
        # Clients see only their own payments
        if user.role == 'client':
            client_profile = getattr(user, 'client_profile', None)
            if client_profile:
                return Payment.objects.filter(
                    reservation__client_profile=client_profile
                ).select_related('reservation__property', 'reservation__client_profile__user')
            else:
                # Fallback to email matching
                return Payment.objects.filter(
                    reservation__client_email=user.email
                ).select_related('reservation__property', 'reservation__client_profile__user')
        
        return Payment.objects.none()
    
    def get_serializer_class(self):
        """Return appropriate serializer class."""
        if self.action == 'create':
            return PaymentCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return PaymentStatusUpdateSerializer
        return PaymentSerializer
    
    def get_permissions(self):
        """Get permissions for different actions."""
        if self.action == 'create':
            permission_classes = [CanProcessPayments]
        elif self.action in ['update', 'partial_update']:
            permission_classes = [CanProcessPayments]
        else:
            permission_classes = [CanAccessPaymentData]
        
        return [permission() for permission in permission_classes]
    
    def perform_create(self, serializer):
        """Create payment and process it through Stripe."""
        with transaction.atomic():
            payment = serializer.save()
            
            # Process payment through Stripe
            payment_service = PaymentService()
            try:
                payment_intent = payment_service.create_payment_intent(
                    amount=int(payment.amount * 100),  # Convert to cents
                    currency=payment.currency.lower(),
                    reservation_id=str(payment.reservation.id),
                    description=payment.description or f"Paiement pour {payment.reservation}",
                    billing_info={
                        'name': payment.billing_name,
                        'email': payment.billing_email,
                        'phone': payment.billing_phone,
                        'address': {
                            'line1': payment.billing_address_line1,
                            'line2': payment.billing_address_line2,
                            'city': payment.billing_city,
                            'postal_code': payment.billing_postal_code,
                            'country': payment.billing_country or 'FR'
                        }
                    }
                )
                
                payment.stripe_payment_intent_id = payment_intent.id
                payment.save()
                
            except Exception as e:
                payment.mark_as_failed(error_message=str(e))
                raise serializers.ValidationError(f"Erreur lors du traitement du paiement: {str(e)}")
            
            # Log activity
            ReservationActivity.objects.create(
                reservation=payment.reservation,
                activity_type='payment_created',
                description=f"Paiement de {payment.amount} {payment.currency} créé",
                performed_by=self.request.user
            )
    
    @action(detail=True, methods=['post'], permission_classes=[CanProcessPayments])
    def process(self, request, pk=None):
        """Process a payment through Stripe."""
        payment = self.get_object()
        
        if payment.status != 'pending':
            return Response(
                {'error': 'Seuls les paiements en attente peuvent être traités.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        payment_service = PaymentService()
        try:
            result = payment_service.confirm_payment_intent(payment.stripe_payment_intent_id)
            
            if result['status'] == 'succeeded':
                payment.mark_as_completed(charge_id=result.get('charges', [{}])[0].get('id'))
                return Response({'message': 'Paiement traité avec succès.'})
            else:
                payment.mark_as_failed(
                    error_code=result.get('last_payment_error', {}).get('code'),
                    error_message=result.get('last_payment_error', {}).get('message')
                )
                return Response(
                    {'error': f"Paiement échoué: {result.get('last_payment_error', {}).get('message')}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except Exception as e:
            payment.mark_as_failed(error_message=str(e))
            return Response(
                {'error': f"Erreur lors du traitement: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'], permission_classes=[CanProcessPayments])
    def refund(self, request, pk=None):
        """Process a refund."""
        payment = self.get_object()
        amount = request.data.get('amount')
        reason = request.data.get('reason', '')
        
        if not payment.can_be_refunded():
            return Response(
                {'error': 'Ce paiement ne peut pas être remboursé.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not amount or amount > payment.get_refundable_amount():
            return Response(
                {'error': f'Montant invalide. Maximum remboursable: {payment.get_refundable_amount()}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        payment_service = PaymentService()
        try:
            refund = payment_service.create_refund(
                payment.stripe_charge_id,
                amount=int(amount * 100),  # Convert to cents
                reason=reason
            )
            
            if payment.refund(amount, reason):
                # Log activity
                ReservationActivity.objects.create(
                    reservation=payment.reservation,
                    activity_type='refund_created',
                    description=f"Remboursement de {amount} {payment.currency} traité",
                    performed_by=request.user
                )
                
                return Response({'message': 'Remboursement traité avec succès.'})
            else:
                return Response(
                    {'error': 'Erreur lors du traitement du remboursement.'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
        except Exception as e:
            return Response(
                {'error': f"Erreur lors du remboursement: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# --- Contract templates (read-only for agents, manage for staff) ---

class ContractTemplateViewSet(viewsets.ReadOnlyModelViewSet):
    """List and retrieve contract templates."""
    queryset = ContractTemplate.objects.filter(is_active=True)
    serializer_class = ContractTemplateSerializer
    permission_classes = [IsAuthenticated, CanManageContracts]
    filterset_fields = ['contract_type']


# --- Contracts ---

class ContractViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing contracts (draft → sent → signed).
    When contract is signed: reservation is completed and property status set to sold/rented.
    """
    permission_classes = [IsAuthenticated, IsContractOwnerOrAgent]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['reservation', 'status', 'contract_type']
    ordering_fields = ['created_at', 'sent_at', 'signed_at']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Contract.objects.none()
        qs = Contract.objects.select_related(
            'reservation', 'reservation__property', 'created_by', 'signed_by', 'template'
        )
        if user.is_staff or user.is_superuser:
            return qs
        if getattr(user, 'role', None) in ['agent', 'manager']:
            agency = getattr(getattr(user, 'profile', None), 'agency', None)
            if agency:
                return qs.filter(reservation__property__agency=agency)
            return qs.filter(reservation__assigned_agent=user)
        if getattr(user, 'role', None) == 'client':
            from apps.crm.models import ClientProfile
            client_profile = getattr(user, 'client_profile', None)
            if client_profile:
                return qs.filter(
                    Q(reservation__client_profile=client_profile)
                    | Q(reservation__client_email=user.email)
                )
            return qs.filter(reservation__client_email=user.email)
        return Contract.objects.none()

    def get_serializer_class(self):
        if self.action == 'create':
            return ContractCreateSerializer
        if self.action in ['update', 'partial_update']:
            return ContractUpdateSerializer
        return ContractSerializer

    def get_permissions(self):
        if self.action == 'create':
            return [IsAuthenticated(), CanManageContracts()]
        return [IsAuthenticated(), IsContractOwnerOrAgent()]

    def perform_create(self, serializer):
        contract = serializer.save()
        ReservationActivity.objects.create(
            reservation=contract.reservation,
            activity_type='contract_created',
            description="Contrat créé (brouillon)",
            performed_by=self.request.user
        )
        NotificationService.send_in_app_contract_created(contract)

    def perform_update(self, serializer):
        serializer.save()

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsContractOwnerOrAgent])
    def upload_document(self, request, pk=None):
        """Upload the contract document (PDF). Only when status is draft."""
        contract = self.get_object()
        if not contract.can_be_edited():
            return Response(
                {'error': 'Seul un contrat en brouillon peut recevoir un document.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        doc = request.FILES.get('document')
        if not doc:
            return Response(
                {'error': 'Le fichier "document" est requis.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        contract.document = doc
        contract.save(update_fields=['document', 'updated_at'])
        return Response(ContractSerializer(contract).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsContractOwnerOrAgent])
    def generate_pdf(self, request, pk=None):
        """Generate contract PDF with QR code and save to contract.document (draft only)."""
        contract = self.get_object()
        if not contract.can_be_edited():
            return Response(
                {'error': 'Seul un contrat en brouillon peut générer un PDF.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            verify_base = request.build_absolute_uri('/api/reservations/contracts/verify/')
            save_contract_pdf_to_field(contract, verify_base)
            ReservationActivity.objects.create(
                reservation=contract.reservation,
                activity_type='contract_created',
                description="PDF du contrat généré (avec QR code de vérification)",
                performed_by=request.user
            )
            return Response(ContractSerializer(contract).data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {'error': f'Génération PDF impossible : {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsContractOwnerOrAgent])
    def mark_sent(self, request, pk=None):
        """Mark contract as sent to client. Requires document to be uploaded."""
        contract = self.get_object()
        if contract.status != 'draft':
            return Response(
                {'error': 'Seul un contrat en brouillon peut être marqué comme envoyé.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not contract.document:
            return Response(
                {'error': 'Veuillez joindre un document au contrat avant de l\'envoyer.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        with transaction.atomic():
            contract.mark_sent()
            ReservationActivity.objects.create(
                reservation=contract.reservation,
                activity_type='contract_sent',
                description="Contrat envoyé au client",
                performed_by=request.user
            )
            NotificationService.send_in_app_contract_sent(contract)
        return Response(ContractSerializer(contract).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsContractOwnerOrAgent])
    def mark_signed(self, request, pk=None):
        """
        Mark contract as signed. Optionally upload signed_document.
        Completes the reservation and sets property status to sold (sale) or rented (rent).
        """
        contract = self.get_object()
        if contract.status not in ('draft', 'sent'):
            return Response(
                {'error': 'Ce contrat est déjà signé ou archivé.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        signed_file = request.FILES.get('signed_document')
        with transaction.atomic():
            contract.mark_signed(user=request.user)
            if signed_file:
                contract.signed_document = signed_file
                contract.save(update_fields=['signed_document', 'updated_at'])
            ReservationActivity.objects.create(
                reservation=contract.reservation,
                activity_type='contract_signed',
                description="Contrat signé",
                performed_by=request.user
            )
            res = contract.reservation
            res.complete(notes=res.completion_notes or "Contrat signé.")
            prop = res.property
            if contract.contract_type == 'sale':
                prop.status = 'sold'
            else:
                prop.status = 'rented'
            prop.save(update_fields=['status'])

            try:
                from apps.commissions.services import create_commission_for_reservation
                create_commission_for_reservation(
                    res,
                    source=f'contract_signed_{contract.contract_type}',
                    contract_type=contract.contract_type,
                )
            except Exception:
                logger.exception(
                    'Échec création commission à la signature du contrat %s',
                    contract.pk,
                )

            NotificationService.send_in_app_contract_signed(contract)
        return Response(ContractSerializer(contract).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='by-reservation/(?P<reservation_id>[^/.]+)')
    def by_reservation(self, request, reservation_id=None):
        """Get contract for a given reservation (if any)."""
        user = request.user
        if not user.is_authenticated:
            return Response({'error': 'Authentification requise.'}, status=status.HTTP_401_UNAUTHORIZED)
        qs = self.get_queryset().filter(reservation_id=reservation_id)
        contract = qs.first()
        if not contract:
            return Response({'detail': 'Aucun contrat pour cette réservation.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(ContractSerializer(contract).data)

    @action(
        detail=False,
        methods=['get', 'post'],
        url_path='verify/(?P<code>[^/.]+)',
        permission_classes=[AllowAny],
    )
    def verify(self, request, code=None):
        """
        Public endpoint for QR code verification.
        GET: returns contract summary (authenticity check).
        POST: mark contract as viewed/validated (optional).
        """
        contract = Contract.objects.filter(verification_code=code).select_related(
            'reservation', 'reservation__property'
        ).first()
        if not contract:
            return Response(
                {'error': 'Contrat introuvable ou code invalide.', 'valid': False},
                status=status.HTTP_404_NOT_FOUND
            )
        res = contract.reservation
        prop = res.property
        payload = {
            'valid': True,
            'contract_id': str(contract.id),
            'verification_code': contract.verification_code,
            'status': contract.status,
            'contract_type': contract.contract_type,
            'property_title': prop.title,
            'property_address': f"{prop.address_line1}, {prop.postal_code} {prop.city}",
            'client_name': res.get_client_name(),
            'signed_at': contract.signed_at.isoformat() if contract.signed_at else None,
            'viewed_at': contract.viewed_at.isoformat() if contract.viewed_at else None,
        }
        if request.method == 'POST':
            # Marquer comme consulté / validé
            if not contract.viewed_at:
                from django.utils import timezone
                contract.viewed_at = timezone.now()
                contract.save(update_fields=['viewed_at', 'updated_at'])
                payload['viewed_at'] = contract.viewed_at.isoformat()
            return Response(payload, status=status.HTTP_200_OK)
        return Response(payload, status=status.HTTP_200_OK)