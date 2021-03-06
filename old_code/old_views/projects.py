import random

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.http import Http404
from django.conf import settings
from django.core.urlresolvers import reverse
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.db import transaction

from rodan.models.project import Project
from rodan.models.workflow import Workflow
from rodan.models.job import Job
from rodan.models.page import Page
from rodan.models.result import Result

from rodan.forms.projects import ProjectForm
from rodan.utils import rodan_view, headers, render_to_json
from rodan.jobs.diva_resources.divaserve import DivaServe
from rodan.jobs.diva_resources.search import do_query, LiberSearchException


@login_required
def dashboard(request):
    nojob = bool(request.GET.get('nojob', False))

    all_jobs = Job.objects.filter(enabled=True)
    available_jobs = {}
    user = request.user.get_profile() if request.user.is_authenticated() else None
    pages = list(Page.objects.order_by('sequence').all())

    for page in pages:
        for workflow in page.workflows.all():
            if workflow and workflow.has_started:
                page_job = page.get_next_job(user=user, workflow=workflow)
                if page_job:
                    available_jobs[page_job.slug] = page.project.id

    jobs = []
    for job in all_jobs:
        jobs.append((job, job.slug in available_jobs, available_jobs.get(job.slug, '')))

    my_projects = request.user.get_profile().project_set.order_by('-id')
    my_workflows = Workflow.objects.filter(project__creator=request.user.get_profile()).distinct()
    percent_done = sum(project.get_percent_done() for project in my_projects)
    percent_done /= my_projects.count() if my_projects.count() > 0 else 1

    current_jobs = Result.objects.filter(Q(end_manual_time__isnull=False) | Q(job_item__job__is_automatic=True))\
        .filter(end_total_time__isnull=True)\
        .exclude(task_state="FAILURE")

    data = {
        'current_jobs': current_jobs,
        'percent_done': percent_done,
        'my_projects': my_projects,
        'jobs': jobs,
        'workflows': my_workflows,
        'nojob': nojob,
        'title': 'Dashboard',
    }

    return render(request, 'projects/dashboard.html', data)


@login_required
def create(request):
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save(commit=False)
            project.creator = request.user.get_profile()
            project.save()
            return redirect('upload', project_id=project.id)
    else:
        form = ProjectForm()

    data = {
        'form': form,
        'title': 'Create a project',
    }

    return render(request, 'projects/create.html', data)


@rodan_view(Project)
def view(request, project):
    done = bool(request.GET.get('done', False))
    nojob = bool(request.GET.get('nojob', False))

    # All jobs that are part of this project's workflows
    all_jobs = Job.objects.filter(jobitem__workflow__page__project=project).distinct()

    # Jobs that can be performed the logged in user
    available_jobs = set([])
    user = request.user.get_profile() if request.user.is_authenticated() else None
    for page in project.page_set.all():
        for workflow in page.workflows.all():
            if workflow and workflow.has_started:
                page_job = page.get_next_job(user=user, workflow=workflow)
                if page_job:
                    available_jobs.add(page_job)

    current_jobs = Result.objects.filter(Q(end_manual_time__isnull=False) | Q(job_item__job__is_automatic=True))\
        .filter(end_total_time__isnull=True, page__project=project) \
        .exclude(task_state="FAILURE") \
        .order_by('end_manual_time', 'start_time')

    # Create a tuple: (job, if this job can be run now, project it's part of)
    jobs = []
    for job in all_jobs:
        jobs.append((job, job in available_jobs, project.id))

    data = {
        'current_jobs': current_jobs,
        'workflows': project.workflow_set.all(),
        'percent_done': project.get_percent_done(),
        'done': done,
        'nojob': nojob,
        'user_can_edit': project.is_owned_by(request.user),
        'project': project,
        'num_pages': project.page_set.count(),
        'jobs': jobs,
    }

    return ('View project', data)


@login_required
@rodan_view(Project)
def edit(request, project):
    submits = {
        'Save and return to dashboard': ('dashboard', None),
        'Save and continue to image upload': ('upload', [project.id],),
    }

    # If the user isn't the projects owner, show a 403 (forbidden)
    if not project.is_owned_by(request.user):
        raise PermissionDenied

    if request.method == 'POST':
        form = ProjectForm(request.POST, instance=project)

        if form.is_valid():
            form.save()

            # Figure out where to go next
            submit_value = request.POST.get('action', '')
            redirect_view, redirect_args = submits.get(submit_value, ('dashboard', None))
            return redirect(reverse(redirect_view, args=redirect_args))
    else:
        form = ProjectForm(instance=project)

    data = {
        'project': project,
        'form': form,
        'submits': submits,
    }

    return ('Edit', data)


# Will show you a random page from this project, with this slug
# If project_id == 0, then use all projects
@login_required
@headers(Cache_Control='no-cache, no-store, max-age=0, must-revalidate')
@rodan_view(Job)
def task(request, job, project_id=0, page_id=0):
    rodan_user = request.user.get_profile()

    if int(project_id) == 0:
        # Choose a random page!
        project = None
        all_pages = Page.objects.all()
    else:
        project = get_object_or_404(Project, pk=project_id)
        all_pages = project.page_set.all()

    if page_id:
        page = get_object_or_404(Page, pk=page_id)
        possible_workflows = [workflow for workflow in page.workflows.all() if page.get_next_job(user=rodan_user, workflow=workflow) == job and workflow.has_started]
        if not possible_workflows:
            raise Http404
        else:
            # If this is an automatic job then start it immediately
            if job.get_object().is_automatic:
                return redirect(page.get_absolute_url())
            else:
                page_workflow_tuple = (page, random.choice(possible_workflows))
    else:
        print "HERE"
        # Now, try to find a page in this project that has this job next
        # (May have been started by the current user but never finished)
        possible_page_workflow_tuples = [(page, workflow) for page in all_pages for workflow in page.workflows.all() if page.get_next_job(user=rodan_user, workflow=workflow) == job and workflow.has_started]

        # No pages that need this job. Show a 404 for now.
        if not possible_page_workflow_tuples:
            if project:
                return redirect(project.get_absolute_url() + '?nojob=1')
            else:
                return redirect('/dashboard?nojob=1')

        page_workflow_tuple = random.choice(possible_page_workflow_tuples)

    # This is needed in case we're looking at all the projects
    project = page_workflow_tuple[0].project

    # Start the job, noting this user (create the result, with no end time)
    # If the job has already been started by this user, do nothing
    page_workflow_tuple[0].start_next_job(page_workflow_tuple[1], rodan_user)

    print "TUPLE"
    print page_workflow_tuple
    job_object = job.get_object()
    view_data = job.get_view(page_workflow_tuple[0], page_workflow_tuple[1])
    data = {
        'disable_breadcrumbs': True,
        'project': project,
        'job': job,
        'page': page_workflow_tuple[0],
        'original_image': page_workflow_tuple[0].get_latest_thumb_url(page_workflow_tuple[1], size=settings.ORIGINAL_SIZE),
        'large_thumbnail': page_workflow_tuple[0].get_latest_thumb_url(page_workflow_tuple[1], size=settings.LARGE_THUMBNAIL),
        'medium_thumbnail': page_workflow_tuple[0].get_latest_thumb_url(page_workflow_tuple[1], size=settings.MEDIUM_THUMBNAIL),
        'small_thumbnail': page_workflow_tuple[0].get_latest_thumb_url(page_workflow_tuple[1], size=settings.SMALL_THUMBNAIL),
        'job_template': view_data[0],
        'context': view_data[1],
        'form_action': reverse('task_complete', args=[page_workflow_tuple[0].id, page_workflow_tuple[1].id, job.slug]),
        'form': True,
        'hide_sidebar': True,
    }

    return (job.name, data)


@login_required
@rodan_view(Project)
def upload(request, project):
    if not project.is_owned_by(request.user):
        raise Http404

    if request.method == 'POST':
        sample_image = request.POST.get('sample', 0)
        delete_id = request.POST.get('delete', 0)

        if delete_id > 0:
            try:
                page_to_delete = Page.objects.get(pk=delete_id)
                page_to_delete.delete()
            except Page.DoesNotExist:
                pass
        elif sample_image > 0 and Page.objects.filter(pk=sample_image).count() == 1:
            # Return the workflow edit page
            return redirect('new_workflow', sample_image)
        else:
            page_id = request.POST.get('page-id', '')
            page_sequence_new = request.POST.get('page-sequence-new', '')

            if page_id != '' and page_sequence_new != '':
                with transaction.commit_manually():
                    transaction.commit()
                    try:
                        pages = Page.objects.filter(project=project).all()
                        page = pages.get(pk=page_id)
                        page_sequence_new = int(page_sequence_new)
                        page_sequence_old = page.sequence

                        # null out the sequence to avoid uniqueness constraints when shifting
                        page.sequence = None
                        page.save()

                        # if the page was dragged to the right (i.e increase sequence)
                        if page_sequence_old < page_sequence_new:
                            for p in pages[page_sequence_old:page_sequence_new]:
                                p.sequence = p.sequence - 1
                                p.save()
                        else:
                            # if the page was dragged to the left (i.e decrease sequence)
                            # the reason for having a temp_list is because of the ordering
                            # of pages by sequence in the Page model - we need to process
                            # the pages in the range below in reverse order to prevent
                            # uniqueness constraints, but when you reverse the pages QuerySet
                            # the target page that is Null'd out will appear in the list as the first
                            # record to process, which throws a database error.
                            temp_list = []
                            for p in pages[page_sequence_new:page_sequence_old]:
                                temp_list.append(p)

                            temp_list.reverse()
                            for p in temp_list:
                                p.sequence = p.sequence + 1
                                p.save()

                        # change the targer page to its new target sequence value
                        page.sequence = page_sequence_new
                        page.save()
                    except:
                        transaction.rollback()
                    else:
                        transaction.commit()

            # If there's an image specified, create a new workflow for that page
            files = request.FILES.getlist('files[]')

            sequence = Page.objects.filter(project=project).count()

            for file in files:
                # The "sequence" is the number of pages in this project already + 1
                sequence += 1
                new_page = Page.objects.create(project=project, filename=file.name, sequence=sequence)
                new_page.handle_image_upload(file)

            # Figure out where to go next
            # Stay on the same page

    data = {
        'project': project,
        'form': True,
        'file_upload': True,
        'pages': project.page_set.all(),
        'num_processing': project.page_set.filter(is_ready=False).count(),
    }

    return ('Manage images', data)


@rodan_view(Project)
def workflows(request, project):
    if request.method == 'POST':
        wf_id = request.POST.get("workflow_to_remove", 0)
        if wf_id != 0:
            workflow = Workflow.objects.get(pk=wf_id)
            workflow.delete()

    workflows = Workflow.objects.filter(page__project=project).distinct()
    data = {
        'project': project,
        'workflows': workflows,
    }

    return ('Manage workflows', data)


@rodan_view(Project)
def diva(request, project):
    if project.is_partially_complete():
        divaserve_dir = project.get_divaserve_dir()
        iip_url = settings.IIP_URL + '?FIF=' + divaserve_dir + '/'

        data = {
            'form': True,
            'hide_sidebar': True,
            'iip_url': iip_url,
            'image_dir': divaserve_dir,
            'extra_stylesheets': ['diva.min']
        }
        return ('Document viewer', data)
    else:
        # Should eventually redirect to the project page, with a flash message
        raise Http404


@render_to_json()
def divaserve(request, project_id):
    project = Project.objects.get(pk=project_id)
    try:
        d = DivaServe(project.get_divaserve_dir())
    except OSError:
        raise Http404
    return d.get()


@render_to_json()
def query(request, project_id):
    project = Project.objects.get(pk=project_id)
    search_type = request.GET.get('type', 'pnames')
    query = request.GET.get('query', 'ab')
    zoom_level = request.GET.get('zoom', 2)

    try:
        boxes = do_query(search_type, query, zoom_level, project.id)
    except LiberSearchException:
        boxes = []

    return boxes
