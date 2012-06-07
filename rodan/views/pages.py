from django.shortcuts import redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from rodan.models.projects import Page, Job, JobItem
from rodan.models.results import Result
from django.utils import timezone

def view(request, page_id):
    return redirect('/')

@login_required
# Called when submiting the form on the task page
def process(request, page_id, job_slug):
    page = get_object_or_404(Page, pk=page_id)
    job = get_object_or_404(Job, slug=job_slug)

    if request.method != 'POST':
        # Temp - should redirect to the task page
        return redirect('/')
    else:
        job_object = job.get_object()
        kwargs = {}
        parameters = job_object.parameters

        for parameter, default in parameters.iteritems():
            param_type = type(default)
            # Cast it to the right type (<3 python)
            kwargs[parameter] = param_type(request.POST.get(parameter, default))

        # First create a result ...
        job_item = JobItem.objects.get(workflow=page.workflow, job=job)
        try:
            result = Result.objects.get(job_item=job_item, user=request.user.get_profile(), page=page)
        except Result.DoesNotExist:
            result = Result.objects.create(job_item=job_item, user=request.user.get_profile(), page=page, end_manual_time=timezone.now())

        # Figure out the relevant task etc
        task = job_object.task
        task.delay(result.id, **kwargs)

        return redirect(page.project.get_absolute_url())