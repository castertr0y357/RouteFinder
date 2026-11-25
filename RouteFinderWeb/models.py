from typing import Any
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

# Create your models here.

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, db_index=True)
    home_street = models.TextField(blank=True, help_text="Street address")
    home_city = models.CharField(max_length=100, blank=True)
    home_zip = models.CharField(max_length=10, blank=True)
    home_state = models.CharField(max_length=2, blank=True)
    default_stop_mins = models.IntegerField(default=15, help_text="Default minutes spent at each individual garage sale.")
    
    # AI Discovery Preferences
    looking_for = models.TextField(blank=True, help_text="Comma-separated items you are looking for (e.g. 'Vintage Pyrex, Gameboy')")
    ai_enabled = models.BooleanField(default=True, help_text="Toggle all AI functionalities in the application")
    ai_thinking_enabled = models.BooleanField(default=False, help_text="Toggle AI thinking/reasoning")
    ai_thinking_effort = models.IntegerField(default=50, help_text="Adjust thinking effort (1-100)")
    
    # Provider & Model Settings
    ai_provider = models.CharField(
        max_length=50, 
        default='ollama', 
        choices=[('ollama', 'Ollama (Native)'), ('openai', 'OpenAI Compatible')]
    )
    ai_api_url = models.CharField(max_length=500, blank=True, help_text="Custom API base URL")
    ai_model = models.CharField(max_length=255, default='gemma:4b', help_text="Model name to target")
    ai_api_key = models.CharField(max_length=255, blank=True, help_text="Optional API Key for authentication")

    def __str__(self) -> str:
        return f"{self.user.username}'s Profile"

@receiver(post_save, sender=User)
def create_user_profile(sender: Any, instance: User, created: bool, **kwargs: Any) -> None:
    if created:
        UserProfile.objects.get_or_create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender: Any, instance: User, **kwargs: Any) -> None:
    UserProfile.objects.get_or_create(user=instance)

class SavedRoute(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='saved_routes', db_index=True)
    name = models.TextField(default="Weekend Route")
    start_time_str = models.TextField(default="08:00")
    stop_mins = models.IntegerField(default=15)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self) -> str:
        return f"{self.name} - {self.user.username}"

class RouteStop(models.Model):
    route = models.ForeignKey(SavedRoute, on_delete=models.CASCADE, related_name='stops', db_index=True)
    order_index = models.IntegerField()
    address = models.CharField(max_length=500, db_index=True)
    drive_time_str = models.TextField(blank=True)
    arrival_time = models.TextField(blank=True)
    departure_time = models.TextField(blank=True)
    
    class Meta:
        ordering = ['order_index']

class AddressRating(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='address_ratings', db_index=True)
    address = models.CharField(max_length=500, db_index=True)
    
    RATING_CHOICES = [
        ('bust', 'Bust'),
        ('great', 'Great Find'),
        ('neutral', 'Neutral')
    ]
    rating = models.CharField(max_length=10, choices=RATING_CHOICES, default='neutral')
    notes = models.TextField(blank=True)
    is_hidden = models.BooleanField(default=False)
    
    class Meta:
        unique_together = ('user', 'address')
        
    def __str__(self) -> str:
        return f"{self.address} ({self.rating})"

class ScoutIntel(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='scout_intel', db_index=True)
    data = models.JSONField(default=list)
    metadata = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Scout Intel for {self.user.username}"
