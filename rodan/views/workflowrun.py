import urlparse
import os
import shutil
from operator import itemgetter
from celery import registry, chain
from celery.task.control import revoke
from django.core.urlresolvers import resolve

from rest_framework import generics
from rest_framework import permissions
from rest_framework import status
from rest_framework import mixins
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.relations import HyperlinkedIdentityField

from rodan.models import Workflow, RunJob, WorkflowJob, WorkflowRun, Connection, Resource, Input, Output, OutputPort, InputPort, ResourceType
from rodan.serializers.user import UserSerializer
from rodan.paginators.pagination import PaginationSerializer
from rodan.serializers.workflowrun import WorkflowRunSerializer, WorkflowRunByPageSerializer

from rodan.constants import task_status
from rodan.exceptions import CustomAPIException

class WorkflowRunList(generics.ListCreateAPIView):
    """
    Returns a list of all WorkflowRuns. Accepts a POST request with a data body to
    create a new WorkflowRun. POST requests will return the newly-created WorkflowRun
    object.

    Creating a new WorkflowRun instance executes the workflow. Meanwhile, RunJobs,
    Inputs, Outputs and Resources are created corresponding to the workflow.

    #### Parameters
    - `workflow` -- GET-only. UUID(GET) or Hyperlink(POST) of a Workflow.
    - `resource_assignments` -- POST-only. A JSON object. Keys are URLs of InputPorts
      in the Workflow, and values are list of Resource URLs.
    """
    model = WorkflowRun
    permission_classes = (permissions.IsAuthenticated, )
    serializer_class = WorkflowRunSerializer
    pagination_serializer_class = PaginationSerializer
    filter_fields = ('workflow', 'project')
    queryset = WorkflowRun.objects.all()  # [TODO] filter according to the user?

    def perform_create(self, serializer):
        wfrun_status = serializer.validated_data.get('status', task_status.PROCESSING)
        if wfrun_status != task_status.PROCESSING:
            raise ValidationError({'status': ["Cannot create a cancelled, failed or finished WorkflowRun."]})
        wf = serializer.validated_data['workflow']
        if not wf.valid:
            raise ValidationError({'workflow': ["Workflow must be valid before you can run it."]})

        if 'resource_assignments' not in self.request.data:
            raise ValidationError({'resource_assignments': ['This field is required']})
        resource_assignment_dict = self.request.data['resource_assignments']

        try:
            validated_resource_assignment_dict = self._validate_resource_assignments(resource_assignment_dict, serializer)
        except ValidationError as e:
            e.detail = {'resource_assignments': e.detail}
            raise e

        wfrun = serializer.save(creator=self.request.user, project=wf.project)
        wfrun_id = str(wfrun.uuid)
        self._create_workflow_run(wf, wfrun, validated_resource_assignment_dict)
        registry.tasks['rodan.core.master_task'].apply_async((wfrun_id,))

    def _validate_resource_assignments(self, resource_assignment_dict, serializer):
        """
        Validates the resource assignments

        May throw ValidationError.
        Returns a validated dictionary.
        """
        if not isinstance(resource_assignment_dict, dict):
            raise ValidationError(['This field must be a JSON object'])

        unsatisfied_ips = set(InputPort.objects.filter(workflow_job__in=serializer.validated_data['workflow'].workflow_jobs.all(), connections__isnull=True))
        validated_resource_assignment_dict = {}
        multiple_resource_set = None
        for input_port, resources in resource_assignment_dict.iteritems():
            # 1. InputPort is not satisfied
            h_ip = HyperlinkedIdentityField(view_name="inputport-detail")
            h_ip.queryset = InputPort.objects.all()
            try:
                ip = h_ip.to_internal_value(input_port)
            except ValidationError as e:
                e.detail = {input_port: e.detail}
                raise e

            if ip not in unsatisfied_ips:
                raise ValidationError({input_port: ['Assigned InputPort must be unsatisfied']})
            unsatisfied_ips.remove(ip)
            types_of_ip = ip.input_port_type.resource_types.all()

            # 2. Resources:
            if not isinstance(resources, list):
                raise ValidationError({input_port: ['A list of resources is expected']})

            h_res = HyperlinkedIdentityField(view_name="resource-detail")
            h_res.queryset = Resource.objects.all()
            ress = []

            for index, r in enumerate(resources):
                try:
                    ress.append(h_res.to_internal_value(r))
                except ValidationError as e:
                    e.detail = {input_port: {index: e.detail}}
                    raise e


            ## No empty resource set
            if len(ress) == 0:
                raise ValidationError({input_port: ['It is not allowed to assign an empty resource set']})

            ## There must be at most one multiple resource set
            if len(ress) > 1:
                ress_set = set(map(lambda r: r.uuid, ress))
                if not multiple_resource_set:
                    multiple_resource_set = ress_set
                else:
                    if multiple_resource_set != ress_set:
                        raise ValidationError({input_port: ['It is not allowed to assign multiple resource sets']})

            ## Resource must be in project and resource types are matched
            for index, res in enumerate(ress):
                if res.project != serializer.validated_data['workflow'].project:
                    raise ValidationError({input_port: {index: ['Resource is not in the project of Workflow']}})

                if not res.compat_resource_file:
                    raise ValidationError({input_port: {index: ['The compatible resource file is not ready']}})

                type_of_res = res.resource_type
                if type_of_res not in types_of_ip:
                    raise ValidationError({input_port: {index: ['The resource type does not match the InputPort']}})

            validated_resource_assignment_dict[ip] = ress

        # Still we have unsatisfied input ports
        if unsatisfied_ips:
            raise ValidationError(['There are still unsatisfied InputPorts: {0}'.format(
                ' '.join([h_ip.get_url(ip, 'inputport-detail', self.request, None) for ip in unsatisfied_ips])
            )])

        return validated_resource_assignment_dict


    def _create_workflow_run(self, workflow, workflow_run, resource_assignment_dict):
        endpoint_workflowjobs = self._endpoint_workflow_jobs(workflow)
        singleton_workflowjobs = self._singleton_workflow_jobs(workflow, resource_assignment_dict)
        workflowjob_runjob_map = {}
        output_outputport_map = {}
        outputportrunjob_output_map = {}

        def create_runjob_A(wfjob, arg_resource):
            run_job = RunJob(workflow_job=wfjob,
                             workflow_job_uuid=wfjob.uuid.hex,
                             resource_uuid=arg_resource.uuid.hex if arg_resource else None,
                             workflow_run=workflow_run,
                             job_name=wfjob.job.job_name,
                             job_settings=wfjob.job_settings)
            run_job.save()

            outputports = OutputPort.objects.filter(workflow_job=wfjob).prefetch_related('output_port_type__resource_types')

            for op in outputports:
                resource = Resource(project=workflow_run.workflow.project,
                                    resource_type=ResourceType.cached('application/octet-stream'))  # ResourceType will be determined later (see method _create_runjobs)
                resource.save()

                output = Output(output_port=op,
                                run_job=run_job,
                                resource=resource,
                                output_port_type_name=op.output_port_type.name)
                output.save()

                resource.description = """Generated by workflow {0}.
                Output of {1}:{2}
                """.format(workflow_run.name, run_job.job_name, output.output_port_type_name)   # [TODO] could be better described.
                if arg_resource:   # which resource in multiple resources?
                    resource.name = arg_resource.name
                else:
                    resource.name = 'Output of workflow {0}'.format(workflow_run.name)  # assign a name for it
                resource.origin = output
                resource.save()

                output_outputport_map[output] = op
                outputportrunjob_output_map[(op, run_job)] = output

            return run_job


        def create_runjobs(wfjob_A, arg_resource):
            if wfjob_A in workflowjob_runjob_map:
                return workflowjob_runjob_map[wfjob_A]

            runjob_A = create_runjob_A(wfjob_A, arg_resource)

            incoming_connections = Connection.objects.filter(input_port__workflow_job=wfjob_A)

            for conn in incoming_connections:
                wfjob_B = conn.output_workflow_job
                runjob_B = create_runjobs(wfjob_B, arg_resource)

                associated_output = outputportrunjob_output_map[(conn.output_port, runjob_B)]

                Input(run_job=runjob_A,
                      input_port=conn.input_port,
                      input_port_type_name=conn.input_port.input_port_type.name,
                      resource=associated_output.resource).save()

            # entry inputs
            for wfj_ip in wfjob_A.input_ports.all():
                if wfj_ip in resource_assignment_dict:
                    ress = resource_assignment_dict[wfj_ip]
                    if len(ress) > 1:
                        entry_res = arg_resource
                    else:
                        entry_res = ress[0]

                    Input(run_job=runjob_A,
                          input_port=wfj_ip,
                          input_port_type_name=wfj_ip.input_port_type.name,
                          resource=entry_res).save()

            # Determine ResourceType of the outputs of RunJob A.
            for o in runjob_A.outputs.all():
                resource_type_set = set(o.output_port.output_port_type.resource_types.all())
                res = o.resource

                if len(resource_type_set) > 1:
                    ## Eliminate this set by considering the connected InputPorts
                    for connection in o.output_port.connections.all():
                        in_type_set = set(connection.input_port.input_port_type.resource_types.all())
                        resource_type_set.intersection_update(in_type_set)

                if len(resource_type_set) > 1:
                    ## Try to find a same resource type in the input resources.
                    for i in runjob_A.inputs.all():
                        if i.resource.resource_type in resource_type_set:
                            res.resource_type = i.resource.resource_type
                            break
                    else:
                        res.resource_type = resource_type_set.pop()
                else:
                    res.resource_type = resource_type_set.pop()
                res.save()

            workflowjob_runjob_map[wfjob_A] = runjob_A
            return runjob_A


        def runjob_creation_loop(arg_resource):
            for wfjob in endpoint_workflowjobs:
                create_runjobs(wfjob, arg_resource)

            workflow_job_iteration = {}

            for wfjob in workflowjob_runjob_map:
                workflow_job_iteration[wfjob] = workflowjob_runjob_map[wfjob]

            for wfjob in workflow_job_iteration:
                if wfjob not in singleton_workflowjobs:
                    del workflowjob_runjob_map[wfjob]


        # Main:
        ress_multiple = None
        for ip, ress in resource_assignment_dict.iteritems():
            if len(ress) > 1:
                ress_multiple = ress
                break

        if ress_multiple:
            for res in ress_multiple:
                runjob_creation_loop(res)
        else:
            runjob_creation_loop(None)

    def _endpoint_workflow_jobs(self, workflow):
        workflow_jobs = WorkflowJob.objects.filter(workflow=workflow)
        endpoint_workflowjobs = []

        for wfjob in workflow_jobs:
            connections = Connection.objects.filter(output_port__workflow_job=wfjob)

            if not connections:
                endpoint_workflowjobs.append(wfjob)

        return endpoint_workflowjobs

    def _singleton_workflow_jobs(self, workflow, resource_assignment_dict):
        singleton_workflowjobs = []

        def traversal(wfjob):
            if wfjob in singleton_workflowjobs:
                singleton_workflowjobs.remove(wfjob)
            adjacent_connections = Connection.objects.filter(output_port__workflow_job=wfjob)
            for conn in adjacent_connections:
                adj_wfjob = WorkflowJob.objects.get(input_ports=conn.input_port)
                traversal(adj_wfjob)

        for wfjob in WorkflowJob.objects.filter(workflow=workflow):
            singleton_workflowjobs.append(wfjob)

        for ip, ress in resource_assignment_dict.iteritems():
            if len(ress) > 1:
                initial_wfjob = ip.workflow_job
                traversal(initial_wfjob)

        return singleton_workflowjobs



class WorkflowRunDetail(mixins.UpdateModelMixin, generics.RetrieveAPIView):
    """
    Performs operations on a single WorkflowRun instance.

    #### Parameters
    - `status` -- PATCH-only. An integer. Attempt of uncancelling will trigger an error.
    """
    model = WorkflowRun
    permission_classes = (permissions.IsAuthenticated, )
    serializer_class = WorkflowRunSerializer
    queryset = WorkflowRun.objects.all() # [TODO] filter according to the user?

    def patch(self, request, *args, **kwargs):
        wfrun = self.get_object()
        old_status = wfrun.status
        new_status = request.data.get('status', None)

        if new_status:
            if old_status in (task_status.PROCESSING, task_status.RETRYING) and new_status == task_status.CANCELLED:
                response = self.partial_update(request, *args, **kwargs)  # may throw validation errors

                runjobs_to_revoke_query = RunJob.objects.filter(workflow_run=wfrun, status__in=(task_status.SCHEDULED, task_status.PROCESSING, task_status.WAITING_FOR_INPUT))
                runjobs_to_revoke_celery_id = runjobs_to_revoke_query.values_list('celery_task_id', flat=True)

                for celery_id in runjobs_to_revoke_celery_id:
                    if celery_id is not None:
                        revoke(celery_id, terminate=True)
                runjobs_to_revoke_query.update(status=task_status.CANCELLED)
                return response
            elif old_status in (task_status.CANCELLED, task_status.FAILED) and new_status == task_status.RETRYING:
                response = self.partial_update(request, *args, **kwargs)  # may throw validation errors

                runjobs_to_retry_query = RunJob.objects.filter(workflow_run=wfrun, status__in=(task_status.FAILED, task_status.CANCELLED))
                for rj in runjobs_to_retry_query:
                    rj.status = task_status.SCHEDULED
                    rj.error_summary = ''
                    rj.error_details = ''
                    original_settings = {}
                    for k, v in rj.job_settings.iteritems():
                        if not k.startswith('@'):
                            original_settings[k] = v
                    rj.job_settings = original_settings
                    rj.save(update_fields=['status', 'job_settings', 'error_summary', 'error_details'])

                registry.tasks['rodan.core.master_task'].apply_async((wfrun.uuid.hex,))

                return response
            elif new_status is not None:
                raise CustomAPIException({'status': ["Invalid status update"]}, status=status.HTTP_400_BAD_REQUEST)
            else:
                raise CustomAPIException({'status': ["Invalid status update"]}, status=status.HTTP_400_BAD_REQUEST)
        else:  # not updating status
            return self.partial_update(request, *args, **kwargs)
