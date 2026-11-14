import logging
from typing import Any, Dict, Optional
from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth import views as auth_views
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

logger = logging.getLogger(__name__)

class EmailBackend(ModelBackend):
    def authenticate(self, request: Optional[HttpRequest], username: Optional[str] = None, password: Optional[str] = None, **kwargs: Any) -> Optional[AbstractBaseUser]:
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        try:
            # Check if username is an email
            user = UserModel.objects.get(email=username)
        except UserModel.DoesNotExist:
            # Fallback to standard username check
            try:
                user = UserModel.objects.get(username=username)
            except UserModel.DoesNotExist:
                return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None


class AuthentikOIDCBackend(OIDCAuthenticationBackend):
    """
    OIDC authentication backend for RouteFinder integrated with Authentik.
    - Matches users by email (case-insensitive) or preferred_username.
    - Sets unusable password for OIDC-created users and activates them immediately.
    - UserProfile is automatically created via post_save signal.
    - Synchronizes first_name, last_name, email, and grants staff/superuser
      for members of OIDC_ADMIN_GROUP.
    - Enforces OIDC_REQUIRED_GROUP if configured.
    """

    def filter_users_by_claims(self, claims: Dict[str, Any]):
        UserModel = get_user_model()
        email = claims.get('email')
        preferred_username = claims.get('preferred_username')

        if email:
            users = UserModel.objects.filter(email__iexact=email)
            if users.exists():
                return users

        if preferred_username:
            users = UserModel.objects.filter(username__iexact=preferred_username)
            if users.exists():
                return users

        return UserModel.objects.none()

    def verify_claims(self, claims: Dict[str, Any]) -> bool:
        scopes_verified = super().verify_claims(claims)
        if not scopes_verified:
            return False

        required_group = getattr(settings, 'OIDC_REQUIRED_GROUP', '')
        if required_group:
            user_groups = claims.get('groups', [])
            if required_group not in user_groups:
                logger.warning(
                    f"AuthentikOIDC - Access denied: User {claims.get('email')} lacks required group '{required_group}'"
                )
                return False

        return True

    def create_user(self, claims: Dict[str, Any]):
        UserModel = get_user_model()
        email = claims.get('email', '')
        username = claims.get('preferred_username') or (email.split('@')[0] if email else 'oidc_user')

        base_username = username
        counter = 1
        while UserModel.objects.filter(username=username).exists():
            username = f"{base_username}_{counter}"
            counter += 1

        user = UserModel(username=username, email=email, is_active=True)
        user.set_unusable_password()
        self._sync_user_attributes(user, claims)
        user.save()
        logger.info(f"AuthentikOIDC - Created RouteFinder user '{user.username}' from Authentik claims")
        return user

    def update_user(self, user, claims: Dict[str, Any]):
        user.is_active = True
        self._sync_user_attributes(user, claims)
        user.save()
        logger.info(f"AuthentikOIDC - Updated RouteFinder user '{user.username}' from Authentik claims")
        return user

    def _sync_user_attributes(self, user, claims: Dict[str, Any]):
        if 'name' in claims and claims['name']:
            parts = claims['name'].split(' ', 1)
            user.first_name = parts[0]
            user.last_name = parts[1] if len(parts) > 1 else ''
        else:
            if 'given_name' in claims:
                user.first_name = claims.get('given_name', '')
            if 'family_name' in claims:
                user.last_name = claims.get('family_name', '')

        if 'email' in claims and claims['email']:
            user.email = claims['email']

        admin_group = getattr(settings, 'OIDC_ADMIN_GROUP', 'authentik Admins')
        user_groups = claims.get('groups', [])
        if admin_group and admin_group in user_groups:
            user.is_staff = True
            user.is_superuser = True


class StrictOIDCLoginView(auth_views.LoginView):
    """
    LoginView that strictly redirects to Authentik OIDC when OIDC_ENABLED is True,
    rejecting POST requests with 403 Forbidden.
    """

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if getattr(settings, 'OIDC_ENABLED', False):
            if request.method == 'GET':
                next_page = request.GET.get('next', '')
                redirect_url = '/oidc/authenticate/'
                if next_page:
                    redirect_url += f"?next={next_page}"
                return redirect(redirect_url)
            return HttpResponseForbidden("Password login is disabled. Please authenticate via Authentik SSO.")
        return super().dispatch(request, *args, **kwargs)

