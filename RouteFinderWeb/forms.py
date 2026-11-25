from typing import List
from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import UserProfile

class AddressForm(forms.Form):
    start = forms.CharField(widget=forms.TextInput(attrs={'size': 60, 'placeholder': 'Enter starting address'}),
                            label="Starting Location")
    addresses = forms.CharField(widget=forms.Textarea(attrs={'rows': 10, 'cols': 60, 'placeholder': 'Enter exact addresses, one per line.\n(Example: 123 Main St, Springfield, ST)'}),
                                label="Destinations")
    start_time = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}), label="Departure Time", initial="08:00")
    stop_mins = forms.IntegerField(label="Minutes at Each Stop", initial=15, min_value=0)

    def clean_addresses(self) -> List[str]:
        data = self.cleaned_data['addresses']
        # Split by newline and remove empty strings
        return [addr.strip() for addr in data.splitlines() if addr.strip()]

class UserRegisterForm(UserCreationForm):
    email = forms.EmailField(required=True, label="Email Address", widget=forms.EmailInput(attrs={'placeholder': 'name@example.com'}))

    class Meta:
        model = User
        fields = ['email']

    def save(self, commit: bool = True) -> User:
        user = super().save(commit=False)
        # Use email as username for consistency
        user.username = self.cleaned_data['email']
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
        return user

class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(label="Email Address", widget=forms.EmailInput(attrs={'autofocus': True, 'placeholder': 'name@example.com'}))

class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = [
            'home_street', 'home_city', 'home_zip', 'home_state', 
            'default_stop_mins', 
            'looking_for', 'ai_enabled', 'ai_thinking_enabled', 'ai_thinking_effort',
            'ai_provider', 'ai_api_url', 'ai_model', 'ai_api_key'
        ]
        labels = {
            'home_street': 'Street Address',
            'home_city': 'City',
            'home_zip': 'Zip Code',
            'home_state': 'State',
            'default_stop_mins': 'Default Minutes Per Sale',
            'looking_for': 'What are you looking for? (AI Wishlist)',
            'ai_enabled': 'Enable AI Scouting Features',
            'ai_thinking_enabled': 'Enable AI Deep Thinking',
            'ai_thinking_effort': 'AI Thinking Effort Level',
            'ai_provider': 'AI Service Provider',
            'ai_api_url': 'API Base URL',
            'ai_model': 'AI Model Name',
            'ai_api_key': 'API Key',
        }
        widgets = {
            'home_street': forms.TextInput(attrs={'placeholder': '123 Main St'}),
            'home_city': forms.TextInput(attrs={'placeholder': 'Mebane'}),
            'home_zip': forms.TextInput(attrs={'placeholder': '27302'}),
            'home_state': forms.TextInput(attrs={'placeholder': 'CA', 'maxlength': '2'}),
            'default_stop_mins': forms.NumberInput(attrs={'min': 0}),
            'looking_for': forms.Textarea(attrs={'rows': 2, 'placeholder': 'e.g. Vintage Pyrex, Gameboy, Tools'}),
            'ai_enabled': forms.CheckboxInput(attrs={'class': 'switch-checkbox'}),
            'ai_thinking_enabled': forms.CheckboxInput(attrs={'class': 'switch-checkbox'}),
            'ai_thinking_effort': forms.Select(choices=[
                (25, 'Low'),
                (50, 'Medium'),
                (75, 'High'),
                (100, 'Extra High'),
            ], attrs={'class': 'form-select'}),
            'ai_provider': forms.Select(attrs={'class': 'form-select'}),
            'ai_api_url': forms.TextInput(attrs={'placeholder': 'e.g. https://ollama.castertr0y357.net or https://api.openai.com/v1', 'autocomplete': 'off'}),
            'ai_model': forms.TextInput(attrs={'placeholder': 'e.g. gemma:4b or gpt-4o', 'autocomplete': 'off'}),
            'ai_api_key': forms.PasswordInput(render_value=True, attrs={'placeholder': 'Optional API Key', 'autocomplete': 'new-password'}),
        }

class SearchForm(forms.Form):
    zip_code = forms.CharField(max_length=10, label="Zip Code", widget=forms.TextInput(attrs={'placeholder': 'Enter Zip Code'}))
    radius = forms.ChoiceField(
        choices=[(5, '5 miles'), (10, '10 miles'), (15, '15 miles'), (30, '30 miles'), (60, '60 miles')],
        initial=15,
        required=False
    )
