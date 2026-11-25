from typing import Any
from django.shortcuts import render, redirect
from django.views import View
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse

from .. import forms

class RegisterView(View):
    template_name: str = 'RouteFinderWeb/register.html'
    
    def get(self, request: HttpRequest) -> HttpResponse:
        from django.conf import settings
        if getattr(settings, 'OIDC_ENABLED', False):
            return redirect('login')
        form = forms.UserRegisterForm()
        return render(request, self.template_name, {'form': form})
        
    def post(self, request: HttpRequest) -> HttpResponse:
        from django.conf import settings
        if getattr(settings, 'OIDC_ENABLED', False):
            return redirect('login')
        form = forms.UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False # Manual Admin Approval required
            user.save()
            messages.success(request, f"Account application submitted for {user.username}. You will be able to log in once an Administrator approves the account.")
            return redirect('login')
        return render(request, self.template_name, {'form': form})


class ProfileView(LoginRequiredMixin, View):
    template_name: str = 'RouteFinderWeb/profile.html'
    
    def get(self, request: HttpRequest) -> HttpResponse:
        form = forms.UserProfileForm(instance=request.user.userprofile)
        return render(request, self.template_name, {'form': form})
        
    def post(self, request: HttpRequest) -> HttpResponse:
        form = forms.UserProfileForm(request.POST, instance=request.user.userprofile)
        if form.is_valid():
            form.save()
            messages.success(request, "Your settings have been saved.")
            tab = request.POST.get('active_tab', '')
            if tab in ('general', 'ai', 'account'):
                return redirect(f"{request.path}#{tab}")
            return redirect('profile')
        return render(request, self.template_name, {'form': form})


class AITestConnectionView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest) -> HttpResponse:
        import json
        from django.http import JsonResponse
        from ..ai_service import AIService
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'ok': False, 'error': 'Invalid JSON', 'models': []}, status=400)
        api_url = (data.get('ai_api_url') or '').strip()
        api_key = (data.get('ai_api_key') or '').strip()
        if not api_key and hasattr(request.user, 'userprofile'):
            api_key = getattr(request.user.userprofile, 'ai_api_key', '') or ''
        result = AIService.test_connection(api_url, api_key)
        return JsonResponse(result)
