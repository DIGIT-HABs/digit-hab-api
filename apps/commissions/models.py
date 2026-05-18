"""
Models for commission and payment management.
"""

import uuid
from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone
from decimal import Decimal

from apps.auth.models import User, Agency
from apps.properties.models import Property
from apps.reservations.models import Reservation


class Commission(models.Model):
    """
    Commission model for tracking agent commissions from property sales/rentals.
    """
    COMMISSION_STATUS = [
        ('pending', 'En attente'),
        ('approved', 'Approuvée'),
        ('paid', 'Payée'),
        ('cancelled', 'Annulée'),
    ]
    
    COMMISSION_TYPES = [
        ('sale', 'Vente'),
        ('rental', 'Location'),
        ('referral', 'Référence'),
        ('bonus', 'Bonus'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Relations
    agent = models.ForeignKey(User, on_delete=models.CASCADE, related_name='commissions')
    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='commissions')
    property = models.ForeignKey(Property, on_delete=models.SET_NULL, null=True, blank=True, related_name='commissions')
    reservation = models.ForeignKey(Reservation, on_delete=models.SET_NULL, null=True, blank=True, related_name='commissions')
    
    # Commission details
    commission_type = models.CharField(max_length=20, choices=COMMISSION_TYPES, default='sale')
    base_amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('3.00'), help_text="Taux de commission en pourcentage")
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    
    # Status
    status = models.CharField(max_length=20, choices=COMMISSION_STATUS, default='pending')
    
    # Dates
    transaction_date = models.DateTimeField(null=True, blank=True, help_text="Date de la transaction (vente/location)")
    approved_date = models.DateTimeField(null=True, blank=True)
    paid_date = models.DateTimeField(null=True, blank=True)
    
    # Notes
    notes = models.TextField(blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'agent_commissions'
        verbose_name = 'Commission'
        verbose_name_plural = 'Commissions'
        ordering = ['-transaction_date', '-created_at']
        indexes = [
            models.Index(fields=['agent', 'status']),
            models.Index(fields=['agency', 'status']),
            models.Index(fields=['transaction_date']),
        ]
    
    def __str__(self):
        return f"Commission {self.commission_amount} - {self.agent.get_full_name()} ({self.get_status_display()})"
    
    def save(self, *args, **kwargs):
        """Calculate commission amount if not set or zero."""
        if (
            (self.commission_amount is None or self.commission_amount == 0)
            and self.base_amount
            and self.commission_rate
        ):
            self.commission_amount = (
                self.base_amount * self.commission_rate
            ) / Decimal('100')
        super().save(*args, **kwargs)
    
    def approve(self, approved_by=None):
        """Approve the commission."""
        self.status = 'approved'
        self.approved_date = timezone.now()
        self.save(update_fields=['status', 'approved_date', 'updated_at'])
    
    def mark_as_paid(self, paid_date=None):
        """Mark commission as paid."""
        self.status = 'paid'
        self.paid_date = paid_date or timezone.now()
        self.save(update_fields=['status', 'paid_date', 'updated_at'])
    
    def cancel(self, reason=''):
        """Cancel the commission."""
        self.status = 'cancelled'
        if reason:
            self.notes = f"{self.notes}\n\n[Annulée] {reason}" if self.notes else f"[Annulée] {reason}"
        self.save(update_fields=['status', 'notes', 'updated_at'])


class Payment(models.Model):
    """
    Payment model for tracking commission payments to agents.
    """
    PAYMENT_METHODS = [
        ('bank_transfer', 'Virement bancaire'),
        ('mobile_money', 'Mobile Money'),
        ('cash', 'Espèces'),
        ('check', 'Chèque'),
        ('other', 'Autre'),
    ]
    
    PAYMENT_STATUS = [
        ('pending', 'En attente'),
        ('processing', 'En traitement'),
        ('completed', 'Complété'),
        ('failed', 'Échoué'),
        ('cancelled', 'Annulé'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Relations
    agent = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payments')
    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='payments')
    commissions = models.ManyToManyField(Commission, related_name='payments', blank=True)
    
    # Payment details
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='bank_transfer')
    payment_reference = models.CharField(max_length=200, blank=True, help_text="Référence de paiement")
    
    # Status
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='pending')
    
    # Dates
    payment_date = models.DateTimeField(null=True, blank=True)
    processed_date = models.DateTimeField(null=True, blank=True)
    
    # Notes
    notes = models.TextField(blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'commission_payments'
        verbose_name = 'Paiement Commission'
        verbose_name_plural = 'Paiements Commissions'
        ordering = ['-payment_date', '-created_at']
        indexes = [
            models.Index(fields=['agent', 'status']),
            models.Index(fields=['agency', 'status']),
            models.Index(fields=['payment_date']),
        ]
    
    def __str__(self):
        return f"Paiement {self.amount} - {self.agent.get_full_name()} ({self.get_status_display()})"
    
    def mark_as_completed(self, processed_date=None):
        """Mark payment as completed."""
        self.status = 'completed'
        self.processed_date = processed_date or timezone.now()
        if not self.payment_date:
            self.payment_date = self.processed_date
        
        # Mark related commissions as paid
        for commission in self.commissions.all():
            if commission.status == 'approved':
                commission.mark_as_paid(self.processed_date)
        
        self.save(update_fields=['status', 'processed_date', 'payment_date', 'updated_at'])
    
    def mark_as_failed(self, reason=''):
        """Mark payment as failed."""
        self.status = 'failed'
        if reason:
            self.notes = f"{self.notes}\n\n[Échec] {reason}" if self.notes else f"[Échec] {reason}"
        self.save(update_fields=['status', 'notes', 'updated_at'])

