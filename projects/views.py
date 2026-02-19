from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from .models import ProjectCategories, Projects, ProjectsContentBlock


def get_all_categories(request):
    categories = ProjectCategories.objects.all()

    payload = []
    for category in categories:
        payload.append({
            'id': category.id,
            'title': category.title,
            'slug': category.slug,
            'created_at': category.created_at,
        })

    return JsonResponse(payload, safe=False)


def get_projects_by_category(request, slug):
    page = request.GET.get('page', 1)
    limit = request.GET.get('limit', 10)

    projects = Projects.objects.filter(category__slug=slug)
    paginator = Paginator(projects, limit)

    try:
        projects_page = paginator.get_page(page)
    except PageNotAnInteger:
        projects_page = paginator.get_page(1)
    except EmptyPage:
        projects_page = []

    has_next_page = projects_page.has_next()
    payload = {
        'page': projects_page.number,
        'has_next': has_next_page,
        'has_previous': projects_page.has_previous(),
        'next_page': projects_page.next_page_number() if has_next_page else None,
        'data': []
    }
    data = []
    for project in projects_page:
        data.append({
            'id': project.id,
            'title': project.title,
            'slug': project.slug,
            'customer_name': project.customer_name,
            'year': project.year,
            'type': project.type,
            'preview': project.preview_image.url if project.preview_image else None,
        })
    payload['data'] = data
    return JsonResponse(payload, safe=False)


def get_projects_details(request, slug):
    project = get_object_or_404(Projects, slug=slug)

    data = []
    for block in project.blocks.all():
        block_object_data = {
            'type': block.type,
        }

        if block.type == ProjectsContentBlock.IMAGE:
            block_object_data['content'] = block.media.url if block.media else None
        elif block.type == ProjectsContentBlock.VIDEO:
            block_object_data['content'] = block.media.url if block.media else None
            block_object_data['first_video_frame'] = block.first_video_frame.url if block.first_video_frame else None
        elif block.type == ProjectsContentBlock.TEXT or block.type == ProjectsContentBlock.HEADING:
            block_object_data['content'] = block.text

        data.append(block_object_data)

    return JsonResponse(data, safe=False)
