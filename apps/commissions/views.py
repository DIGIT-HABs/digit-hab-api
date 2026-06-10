"""
Views for commission and payment management.
"""

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Sum, Count, Avg
from django.utils import timezone
from datetime import timedelta

from apps.auth.models import User, Agency
from .models import Commission, Payment
from .serializers import CommissionSerializer, PaymentSerializer



class CommissionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing commissions.
    """
    queryset = Commission.objects.select_related(
        'agent', 'agency', 'property', 'reservation',
    ).prefetch_related('property__images')
    serializer_class = CommissionSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        'agent': ['exact'],
        'agency': ['exact'],
        'status': ['exact'],
        'commission_type': ['exact'],
        'transaction_date': ['gte', 'lte'],
    }
    search_fields = ['agent__username', 'agent__email', 'property__title', 'notes']
    ordering_fields = ['commission_amount', 'transaction_date', 'created_at']
    ordering = ['-transaction_date', '-created_at']
    
    def get_queryset(self):
        """Filter queryset based on user role."""
        user = self.request.user
        queryset = super().get_queryset()
        
        if user.role == 'admin':
            # Admin can see all commissions
            return queryset
        elif user.role == 'agent':
            # « Mes commissions » : uniquement celles de l'agent connecté
            return queryset.filter(agent=user)

        return queryset.none()
    
    def perform_create(self, serializer):
        """Set agent and agency when creating commission."""
        # Le serializer.create() gère déjà la création
        # On laisse le serializer faire son travail
        pass
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def approve(self, request, pk=None):
        """Approve a commission."""
        try:
            commission = self.get_object()
            
            # Only admin or agency admin can approve
            if request.user.role != 'admin':
                return Response(
                    {'error': 'Seuls les administrateurs peuvent approuver les commissions.'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            commission.approve(approved_by=request.user)
            serializer = self.get_serializer(commission)
            return Response(serializer.data)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def mark_paid(self, request, pk=None):
        """Mark commission as paid."""
        try:
            commission = self.get_object()
            
            # Only admin can mark as paid
            if request.user.role != 'admin':
                return Response(
                    {'error': 'Seuls les administrateurs peuvent marquer les commissions comme payées.'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            commission.mark_as_paid()
            serializer = self.get_serializer(commission)
            return Response(serializer.data)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def stats(self, request):
        """Get commission statistics for the agent."""
        try:
            user = request.user
            queryset = self.get_queryset()
            
            # Calculate statistics
            total_commissions = queryset.count()
            total_amount = queryset.aggregate(total=Sum('commission_amount'))['total'] or 0
            pending_amount = queryset.filter(status='pending').aggregate(total=Sum('commission_amount'))['total'] or 0
            approved_amount = queryset.filter(status='approved').aggregate(total=Sum('commission_amount'))['total'] or 0
            paid_amount = queryset.filter(status='paid').aggregate(total=Sum('commission_amount'))['total'] or 0
            
            # Monthly statistics (last 12 months)
            twelve_months_ago = timezone.now() - timedelta(days=365)
            # Compatible SQLite et PostgreSQL
            from django.db import connection
            if 'sqlite' in connection.vendor:
                # SQLite: utiliser strftime
                monthly_stats = queryset.filter(
                    transaction_date__gte=twelve_months_ago
                ).extra(
                    select={'month': "strftime('%%Y-%%m', transaction_date)"}
                ).values('month').annotate(
                    count=Count('id'),
                    total=Sum('commission_amount')
                ).order_by('month')
            else:
                # PostgreSQL: utiliser DATE_TRUNC
                monthly_stats = queryset.filter(
                    transaction_date__gte=twelve_months_ago
                ).extra(
                    select={'month': "DATE_TRUNC('month', transaction_date)"}
                ).values('month').annotate(
                    count=Count('id'),
                    total=Sum('commission_amount')
                ).order_by('month')
            
            stats = {
                'total_commissions': total_commissions,
                'total_amount': float(total_amount),
                'pending_amount': float(pending_amount),
                'approved_amount': float(approved_amount),
                'paid_amount': float(paid_amount),
                'by_status': dict(queryset.values('status').annotate(count=Count('id')).values_list('status', 'count')),
                'by_type': dict(queryset.values('commission_type').annotate(count=Count('id')).values_list('commission_type', 'count')),
                'monthly_stats': list(monthly_stats),
            }
            
            return Response(stats)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def pending(self, request):
        """Get pending commissions."""
        queryset = self.get_queryset().filter(status='pending')
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class PaymentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing payments.
    """
    queryset = Payment.objects.select_related('agent', 'agency').prefetch_related('commissions')
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        'agent': ['exact'],
        'agency': ['exact'],
        'status': ['exact'],
        'payment_method': ['exact'],
        'payment_date': ['gte', 'lte'],
    }
    search_fields = ['agent__username', 'agent__email', 'payment_reference', 'notes']
    ordering_fields = ['amount', 'payment_date', 'created_at']
    ordering = ['-payment_date', '-created_at']
    
    def get_queryset(self):
        """Filter queryset based on user role."""
        user = self.request.user
        queryset = super().get_queryset()
        
        if user.role == 'admin':
            # Admin can see all payments
            return queryset
        elif user.role == 'agent':
            # Agent can see payments from their agency
            # Get agency from user
            agency = None
            if hasattr(user, 'profile') and user.profile.agency:
                agency = user.profile.agency
            elif hasattr(user, 'agency') and user.agency:
                agency = user.agency
            
            if agency:
                # Agent can see all payments from their agency
                return queryset.filter(agency=agency)
            else:
                # If no agency, only see their own payments
                return queryset.filter(agent=user)
        
        return queryset.none()
    
    def perform_create(self, serializer):
        """Set agent and agency when creating payment."""
        # Le serializer.create() gère déjà la création
        # On laisse le serializer faire son travail
        pass
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def mark_completed(self, request, pk=None):
        """Mark payment as completed."""
        try:
            payment = self.get_object()
            
            # Only admin can mark as completed
            if request.user.role != 'admin':
                return Response(
                    {'error': 'Seuls les administrateurs peuvent marquer les paiements comme complétés.'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            payment.mark_as_completed()
            serializer = self.get_serializer(payment)
            return Response(serializer.data)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def history(self, request):
        """Get payment history for the agent."""
        queryset = self.get_queryset().filter(status='completed')
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

