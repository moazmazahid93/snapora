from django import forms
from .models import Video, Tag
import os

class VideoUploadForm(forms.ModelForm):
    tags = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Comma-separated tags'}),
        help_text='Enter tags separated by commas'
    )

    class Meta:
        model = Video
        fields = ['video_file', 'thumbnail', 'title', 'description', 'visibility', 'tags']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pre-populate tags if editing an existing video
        if self.instance and self.instance.pk:
            tags = self.instance.tags.all()
            self.initial['tags'] = ', '.join([tag.name for tag in tags])

    def clean_tags(self):
        tags = self.cleaned_data.get('tags', '')
        # Return the string, we'll process it in the save method
        return tags

    def clean_video_file(self):
        video_file = self.cleaned_data.get('video_file')
        if video_file:
            # Check file size (500MB limit)
            if video_file.size > 500 * 1024 * 1024:
                raise forms.ValidationError("File size exceeds 500MB limit")
            
            # Check file type
            valid_extensions = ['.mp4', '.webm', '.avi', '.mov', '.mkv']
            ext = os.path.splitext(video_file.name)[1].lower()
            if ext not in valid_extensions:
                raise forms.ValidationError("Unsupported file format. Please upload a video file.")
        
        return video_file

    def save(self, commit=True):
        # First save the video instance
        video = super().save(commit=commit)
        
        # Process tags after the video is saved
        tags_input = self.cleaned_data.get('tags', '')
        if tags_input:
            tag_names = [tag.strip() for tag in tags_input.split(',') if tag.strip()]
            tags = []
            for tag_name in tag_names:
                tag, created = Tag.objects.get_or_create(
                    name=tag_name.lower(),
                    defaults={'slug': tag_name.lower().replace(' ', '-')}
                )
                tags.append(tag)
            video.tags.set(tags)
        else:
            video.tags.clear()
            
        return video
