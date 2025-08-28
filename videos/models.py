from django.db import models
from django.contrib.auth import get_user_model
from django.utils.text import slugify
from django.core.validators import FileExtensionValidator
from storages.backends.azure_storage import AzureStorage  # Add this import
import uuid
import os

User = get_user_model()

# Create AzureStorage instance at the module level
azure_storage = AzureStorage()

class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(unique=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class Video(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='videos')
    
    # Use AzureStorage for video files
    video_file = models.FileField(
        upload_to='videos/', 
        max_length=200,
        storage=azure_storage,  # Add this line to use Azure Storage
        validators=[FileExtensionValidator(allowed_extensions=['mp4', 'webm', 'avi', 'mov', 'mkv'])]
    )
    
    # Use AzureStorage for thumbnails
    thumbnail = models.ImageField(
        upload_to='thumbnails/', 
        blank=True, 
        null=True,
        max_length=200,
        storage=azure_storage  # Add this line to use Azure Storage
    )
    
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name='videos')
    visibility = models.CharField(
        max_length=10,
        choices=[
            ('public', 'Public'),
            ('private', 'Private'),
            ('followers', 'Followers Only'),
        ],
        default='public'
    )

    def __str__(self):
        return f'{self.title} by {self.user.username}'

    @property
    def like_count(self):
        return self.likes.filter(is_like=True).count()

    @property
    def comment_count(self):
        return self.comments.count()

    class Meta:
        ordering = ['-created_at']
