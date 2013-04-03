import os
import json
import urlparse
from django.contrib.auth.models import User
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.core.urlresolvers import resolve

from rest_framework import generics
from rest_framework import permissions
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.reverse import reverse

from rodan.serializers.project import ProjectSerializer
from rodan.serializers.user import UserSerializer
from rodan.serializers.page import PageSerializer
from rodan.serializers.workflow import WorkflowSerializer
from rodan.serializers.workflowjob import WorkflowJobSerializer
from rodan.serializers.job import JobSerializer
from rodan.serializers.result import ResultSerializer

from rodan.models.project import Project
from rodan.models.workflow import Workflow
from rodan.models.workflowjob import WorkflowJob
from rodan.models.page import Page
from rodan.models.job import Job
from rodan.models.result import Result
from rodan.helpers.convert import ensure_compatible
from rodan.helpers.thumbnails import create_thumbnails
from rodan.helpers.pagedone import pagedone
from rodan.helpers.workflow import run_workflow


@api_view(('GET',))
def api_root(request, format=None):
    return Response({
            'projects': reverse('project-list', request=request, format=format),
            'workflows': reverse('workflow-list', request=request, format=format),
            'workflowjobs': reverse('workflowjob-list', request=request, format=format),
            'pages': reverse('page-list', request=request, format=format),
            'jobs': reverse('job-list', request=request, format=format),
            'results': reverse('result-list', request=request, format=format),
            'users': reverse('user-list', request=request, format=format)
    })


@api_view(('GET',))
def kickoff_workflow(request, pk, format=None):
    workflows = run_workflow(pk)
    return Response({
        'success': True,
        'workflows': workflows
    })


@api_view(('GET',))
def run_test_workflow(request, pk, page_id, format=None):
    run_workflow(pk, testing=True, page_id=page_id)
    return Response({'success': True})


@ensure_csrf_cookie
def home(request):
    data = {}
    return render(request, 'base.html', data)


class ProjectList(generics.ListCreateAPIView):
    model = Project
    permission_classes = (permissions.IsAuthenticatedOrReadOnly, )
    serializer_class = ProjectSerializer


class ProjectDetail(generics.RetrieveUpdateDestroyAPIView):
    model = Project
    permission_classes = (permissions.IsAuthenticatedOrReadOnly, )
    serializer_class = ProjectSerializer

    def pre_save(self, obj):
        obj.creator = self.request.user


class WorkflowList(generics.ListCreateAPIView):
    model = Workflow
    permission_classes = (permissions.IsAuthenticatedOrReadOnly, )
    serializer_class = WorkflowSerializer
    paginate_by = None


class WorkflowDetail(generics.RetrieveUpdateDestroyAPIView):
    model = Workflow
    permission_classes = (permissions.IsAuthenticatedOrReadOnly, )
    serializer_class = WorkflowSerializer

    def patch(self, request, pk, *args, **kwargs):
        print "Patch called"
        kwargs['partial'] = True

        workflow = Workflow.objects.get(pk=pk)
        if not workflow:
            return Response({}, status=status.HTTP_404_NOT_FOUND)

        pages = request.DATA.get('pages')
        if pages:
            for page in pages:
                value = urlparse.urlparse(page['url']).path
                # resolve the URL we're passed to a page object
                try:
                    p = resolve(value)
                except:
                    return Response({'error': 'Could not resolve path to page object'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                # check if the page already exists on this workflow. If so, we skip it.
                relationship_exists = workflow.pages.filter(pk=p.kwargs.get('pk')).exists()
                if relationship_exists:
                    continue

                # now use the pk to grab the Page object from the database
                page_obj = Page.objects.get(pk=p.kwargs.get('pk'))
                # finally, add this page to the workflow
                if not page_obj:
                    return Response({'error': 'Page Object was not found'}, status=status.HTTP_404_NOT_FOUND)

                workflow.pages.add(page_obj)

        return self.update(request, *args, **kwargs)


class WorkflowJobList(generics.ListCreateAPIView):
    model = WorkflowJob
    serializer_class = WorkflowJobSerializer


class WorkflowJobDetail(generics.RetrieveUpdateDestroyAPIView):
    model = WorkflowJob
    permission_classes = (permissions.IsAuthenticatedOrReadOnly, )
    serializer_class = WorkflowJobSerializer


class PageList(generics.ListCreateAPIView):
    model = Page
    permission_classes = (permissions.IsAuthenticatedOrReadOnly, )
    serializer_class = PageSerializer

    # override the POST method to deal with multiple files in a single request
    def post(self, request, *args, **kwargs):
        if not request.FILES:
            return Response({'error': "You must supply at least one file to upload"}, status=status.HTTP_400_BAD_REQUEST)
        response = []
        current_user = User.objects.get(pk=request.user.id)

        start_seq = int(request.POST['page_order'])

        for seq, fileobj in enumerate(request.FILES.getlist('files'), start=start_seq):
            data = {
                'name': fileobj.name,
                'project': request.POST['project'],
                'page_order': seq,
                'image_file_size': fileobj.size,
            }

            files = {
                'page_image': fileobj
            }
            serializer = PageSerializer(data=data, files=files)

            if serializer.is_valid():
                page_object = serializer.save()

                page_object.creator = current_user
                page_object.save()

                # Create a chain that will first ensure the
                # file is converted to PNG and then create the thumbnails.
                # The ensure_compatible() method returns the page_object
                # as the first (invisible) argument to the create_thumbnails
                # method.
                res = ensure_compatible.s(page_object)
                res.link(create_thumbnails.s())
                res.link(pagedone.s())
                res.apply_async()

                response.append(serializer.data)
            else:
                # if there's an error, bail early and send the error back to the client
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return Response({'pages': response}, status=status.HTTP_201_CREATED)


class PageDetail(generics.RetrieveUpdateDestroyAPIView):
    model = Page
    permission_classes = (permissions.IsAuthenticatedOrReadOnly, )
    serializer_class = PageSerializer


class JobList(generics.ListAPIView):
    model = Job
    serializer_class = JobSerializer
    paginate_by = None

    def get_queryset(self):
        """
        Optionally restricts the returned purchases to a given user,
        by filtering against a `username` query parameter in the URL.
        """
        queryset = Job.objects.all()
        enabled = self.request.QUERY_PARAMS.get('enabled', None)
        if enabled is not None:
            queryset = queryset.filter(enabled=enabled)
        return queryset


class JobDetail(generics.RetrieveUpdateDestroyAPIView):
    model = Job
    permission_classes = (permissions.IsAuthenticatedOrReadOnly, )
    serializer_class = JobSerializer


class ResultList(generics.ListCreateAPIView):
    model = Result
    serializer_class = ResultSerializer


class ResultDetail(generics.RetrieveUpdateDestroyAPIView):
    model = Result
    serializer_class = ResultSerializer


class UserList(generics.ListCreateAPIView):
    model = User
    permission_classes = (permissions.IsAuthenticatedOrReadOnly, )
    serializer_class = UserSerializer


class UserDetail(generics.RetrieveUpdateDestroyAPIView):
    model = User
    permission_classes = (permissions.IsAuthenticatedOrReadOnly, )
    serializer_class = UserSerializer
