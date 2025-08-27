from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import models
from django.db.models import Count, Q
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.utils import timezone
from django.conf import settings
import logging

from .models import Video, Tag
from .forms import VideoUploadForm
from interactions.models import Like, View

logger = logging.getLogger(__name__)

@login_required
def upload_video(request):
    if request.method == 'POST':
        form = VideoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                video = form.save(commit=False)
                video.user = request.user
                
                # Validate file size
                video_file = request.FILES.get('video_file')
                if video_file and video_file.size > 500 * 1024 * 1024:
                    messages.error(request, 'File size exceeds 500MB limit')
                    return render(request, 'videos/upload.html', {'form': form})
                
                video.save()
                form.save_m2m()
                
                # Handle tags
                tags_input = form.cleaned_data.get('tags', '')
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
                
                messages.success(request, 'Video uploaded successfully!')
                return redirect('videos:watch', video_id=video.id)
                
            except Exception as e:
                logger.error(f"Error uploading video: {str(e)}")
                # More specific error messages
                if "permission" in str(e).lower():
                    messages.error(request, 'Azure Storage permission denied. Check your credentials.')
                elif "connection" in str(e).lower():
                    messages.error(request, 'Could not connect to Azure Storage. Check network connection.')
                else:
                    messages.error(request, f'An error occurred while uploading the video: {str(e)}')
        else:
            logger.error(f"Form validation errors: {form.errors}")
            messages.error(request, 'Please correct the errors below.')
    else:
        form = VideoUploadForm()
    
    return render(request, 'videos/upload.html', {'form': form})

def watch_video(request, video_id):
    try:
        video = get_object_or_404(
            Video.objects.select_related('user')
                       .prefetch_related('tags', 'comments', 'comments__user'),
            id=video_id
        )

        # Check video visibility permissions
        if not can_view_video(request.user, video):
            if request.user.is_authenticated:
                messages.error(request, 'You do not have permission to view this video.')
                return redirect('home')
            else:
                messages.error(request, 'Please login to view this video.')
                return redirect('login')

        # Record view (for authenticated users only)
        if request.user.is_authenticated:
            View.objects.get_or_create(
                user=request.user,
                video=video,
                defaults={'viewed_at': timezone.now()}
            )
        else:
            # Track anonymous views using session
            viewed_videos = request.session.get('viewed_videos', [])
            if video_id not in viewed_videos:
                View.objects.create(user=None, video=video, viewed_at=timezone.now())
                viewed_videos.append(video_id)
                request.session['viewed_videos'] = viewed_videos

        # Get comments with optimization
        comments = video.comments.filter(parent=None).select_related('user').order_by('-created_at')

        # Check if user liked the video
        user_like = None
        if request.user.is_authenticated:
            user_like = video.likes.filter(user=request.user).first()

        # Get related videos
        related_videos = get_related_videos(video)

        context = {
            'video': video,
            'comments': comments,
            'user_like': user_like,
            'related_videos': related_videos,
        }
        return render(request, 'videos/watch.html', context)

    except Video.DoesNotExist:
        messages.error(request, 'Video not found.')
        return redirect('home')
    except Exception as e:
        logger.error(f"Error watching video {video_id}: {e}")
        messages.error(request, 'An error occurred while loading the video.')
        return redirect('home')

def can_view_video(user, video):
    """Check if user has permission to view the video"""
    if video.visibility == 'public':
        return True
    elif not user.is_authenticated:
        return False
    elif video.visibility == 'private':
        return video.user == user
    elif video.visibility == 'followers':
        return video.user == user or video.user.followers.filter(id=user.id).exists()
    return False

def get_related_videos(video, limit=6):
    """Get related videos based on tags and user"""
    related_videos = Video.objects.filter(
        visibility='public'
    ).exclude(id=video.id)

    # Filter by tags if video has tags
    if video.tags.exists():
        tag_ids = video.tags.values_list('id', flat=True)
        related_videos = related_videos.filter(
            tags__in=tag_ids
        ).distinct()

    # If not enough videos by tags, include videos from same user
    if related_videos.count() < limit:
        same_user_videos = Video.objects.filter(
            user=video.user,
            visibility='public'
        ).exclude(id=video.id)
        related_videos = (related_videos | same_user_videos).distinct()

    return related_videos.order_by('-created_at')[:limit]

@login_required
def edit_video(request, video_id):
    video = get_object_or_404(Video, id=video_id, user=request.user)
    
    if request.method == 'POST':
        form = VideoUploadForm(request.POST, request.FILES, instance=video)
        if form.is_valid():
            try:
                video = form.save(commit=False)
                
                # Handle file updates
                if 'video_file' in request.FILES:
                    # Delete old video file from Azure Storage if needed
                    old_video_file = video.video_file
                    video.video_file = request.FILES['video_file']
                    if old_video_file:
                        old_video_file.delete(save=False)
                
                if 'thumbnail' in request.FILES:
                    old_thumbnail = video.thumbnail
                    video.thumbnail = request.FILES['thumbnail']
                    if old_thumbnail:
                        old_thumbnail.delete(save=False)
                
                video.save()
                
                # Handle tags
                tags_input = form.cleaned_data.get('tags', '')
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
                
                messages.success(request, 'Video updated successfully!')
                return redirect('videos:watch', video_id=video.id)
                
            except Exception as e:
                logger.error(f"Error updating video {video_id}: {e}")
                messages.error(request, 'An error occurred while updating the video.')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        initial_tags = ', '.join(tag.name for tag in video.tags.all())
        form = VideoUploadForm(instance=video, initial={'tags': initial_tags})
    
    return render(request, 'videos/edit.html', {'form': form, 'video': video})

@login_required
@require_POST
def delete_video(request, video_id):
    video = get_object_or_404(Video, id=video_id, user=request.user)
    
    try:
        # Delete files from Azure Storage
        if video.video_file:
            video.video_file.delete(save=False)
        if video.thumbnail:
            video.thumbnail.delete(save=False)
        
        video.delete()
        messages.success(request, 'Video deleted successfully!')
        return redirect('users:profile', username=request.user.username)
        
    except Exception as e:
        logger.error(f"Error deleting video {video_id}: {e}")
        messages.error(request, 'An error occurred while deleting the video.')
        return redirect('videos:watch', video_id=video_id)

def search(request):
    query = request.GET.get('q', '').strip()
    page = request.GET.get('page', 1)
    sort_by = request.GET.get('sort', 'newest')
    
    videos = Video.objects.filter(visibility='public').select_related('user').prefetch_related('tags')

    if query:
        videos = videos.filter(
            Q(title__icontains=query) |
            Q(description__icontains=query) |
            Q(user__username__icontains=query) |
            Q(tags__name__icontains=query)
        ).distinct()

    # Sorting
    if sort_by == 'oldest':
        videos = videos.order_by('created_at')
    elif sort_by == 'most_views':
        videos = videos.annotate(view_count=Count('views')).order_by('-view_count')
    elif sort_by == 'most_likes':
        videos = videos.annotate(like_count=Count('likes')).order_by('-like_count')
    else:  # newest (default)
        videos = videos.order_by('-created_at')

    # Pagination
    paginator = Paginator(videos, 12)  # 12 videos per page
    try:
        videos_page = paginator.page(page)
    except PageNotAnInteger:
        videos_page = paginator.page(1)
    except EmptyPage:
        videos_page = paginator.page(paginator.num_pages)

    context = {
        'videos': videos_page,
        'query': query,
        'sort_by': sort_by,
    }
    return render(request, 'videos/search.html', context)

def videos_by_tag(request, tag_slug):
    tag = get_object_or_404(Tag, slug=tag_slug)
    page = request.GET.get('page', 1)
    
    videos = tag.videos.filter(visibility='public').select_related('user').order_by('-created_at')
    
    # Pagination
    paginator = Paginator(videos, 12)
    try:
        videos_page = paginator.page(page)
    except PageNotAnInteger:
        videos_page = paginator.page(1)
    except EmptyPage:
        videos_page = paginator.page(paginator.num_pages)

    context = {
        'tag': tag,
        'videos': videos_page,
    }
    return render(request, 'videos/tag.html', context)

@login_required
def my_videos(request):
    """View for authenticated users to see their own videos"""
    page = request.GET.get('page', 1)
    videos = Video.objects.filter(user=request.user).select_related('user').order_by('-created_at')
    
    paginator = Paginator(videos, 12)
    try:
        videos_page = paginator.page(page)
    except PageNotAnInteger:
        videos_page = paginator.page(1)
    except EmptyPage:
        videos_page = paginator.page(paginator.num_pages)

    return render(request, 'videos/my_videos.html', {'videos': videos_page})

# API endpoints for AJAX requests
@require_POST
@login_required
def increment_view_count(request, video_id):
    """API endpoint to increment view count (for AJAX)"""
    try:
        video = get_object_or_404(Video, id=video_id)
        if can_view_video(request.user, video):
            View.objects.get_or_create(
                user=request.user,
                video=video,
                defaults={'viewed_at': timezone.now()}
            )
            return JsonResponse({'success': True, 'views': video.views.count()})
        return JsonResponse({'success': False, 'error': 'Permission denied'})
    except Exception as e:
        logger.error(f"Error incrementing view count: {e}")
        return JsonResponse({'success': False, 'error': str(e)})
