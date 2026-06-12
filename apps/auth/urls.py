"""
URL configuration for authentication app.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)
from . import views

# Create router for ViewSets
router = DefaultRouter()
# Temporarily disabled ViewSets causing UUID/Integer conflicts
router.register(r'users', views.UserViewSet, basename='user')
router.register(r'profiles', views.UserProfileViewSet, basename='userprofile')
router.register(r'agencies', views.AgencyViewSet, basename='agency')

from .test_views import TestAuthView

urlpatterns = [
    # Inscription agence (public) — AVANT le router : sinon agencies/<pk>/ capture "register"
    path('agencies/register/', views.AgencyCreateView.as_view(), name='agency_register'),
    path(
        'agencies/register-with-agent/',
        views.AgencyWithAgentRegisterView.as_view(),
        name='agency_register_with_agent',
    ),
    path('admin/agents/', views.AdminAgentsListView.as_view(), name='admin_agents_list'),
    path(
        'admin/agents/<uuid:agent_id>/',
        views.AdminAgentDetailView.as_view(),
        name='admin_agent_detail',
    ),
    # AVANT le router : sinon users/me/ est capturé par UserViewSet.me (GET seul) → PATCH 405
    path('users/me/', views.CurrentUserView.as_view(), name='current_user'),

    # API routes (ViewSets)
    path('', include(router.urls)),

    # JWT Authentication
    path('login/', views.CustomTokenObtainPairView.as_view(), name='login'),
    path('token/', views.CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('token/verify/', TokenVerifyView.as_view(), name='token_verify'),
    
    # Registration
    path('register/', views.RegisterView.as_view(), name='register'),
    
    # Custom authentication endpoints
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('verify/', views.verify_token, name='verify_token'),
    path('update-profile/', views.update_profile, name='update_profile'),

    # Test endpoint
    path('test-auth/', TestAuthView.as_view(), name='test_auth'),
    
    # OAuth 2.0 - Social Authentication (V2)
    path('oauth/google/', views.GoogleAuthView.as_view(), name='google_auth'),
    path('oauth/apple/', views.AppleAuthView.as_view(), name='apple_auth'),
    
    # User management (simple endpoints)
    path('users/list/', views.UserListView.as_view(), name='user_list'),
    path('users/<uuid:pk>/', views.UserDetailView.as_view(), name='user_detail'),
    # Création compte agent (authentifié, agence de l'utilisateur ou agency_id pour admin)
    path('agents/create/', views.CreateAgentView.as_view(), name='create_agent'),
]