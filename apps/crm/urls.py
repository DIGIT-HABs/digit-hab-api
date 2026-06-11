"""
URL configuration for CRM management.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ClientProfileViewSet, PropertyInterestViewSet, ClientInteractionViewSet,
    LeadViewSet, PropertyMatchingViewSet, DashboardViewSet, ClientNoteViewSet,
    ReportingViewSet, CrmAnalyticsView, AdminPlatformOverviewView,
)

# Create router and register viewsets
router = DefaultRouter()
router.register(r'clients', ClientProfileViewSet, basename='clientprofile')
router.register(r'interests', PropertyInterestViewSet, basename='propertyinterest')
router.register(r'interactions', ClientInteractionViewSet, basename='clientinteraction')
router.register(r'leads', LeadViewSet, basename='lead')
router.register(r'matching', PropertyMatchingViewSet, basename='propertmatching')
router.register(r'dashboard', DashboardViewSet, basename='dashboard')
router.register(r'notes', ClientNoteViewSet, basename='clientnote')
router.register(r'reports', ReportingViewSet, basename='reporting')

# URL patterns
urlpatterns = [
    path('admin/overview/', AdminPlatformOverviewView.as_view(), name='crm-admin-overview'),
    path('analytics/', CrmAnalyticsView.as_view(), name='crm-analytics'),
    path('', include(router.urls)),
]