from rodan.models.workflow import Workflow
from rest_framework import serializers
from rodan.serializers.page import PageSerializer


class WorkflowSerializer(serializers.HyperlinkedModelSerializer):
    project = serializers.HyperlinkedRelatedField(view_name="project-detail")
    pages = PageSerializer()
    uuid = serializers.Field(source='uuid')

    class Meta:
        model = Workflow
        read_only_fields = ('created', 'updated')
        fields = ("url",
                  "uuid",
                  "name",
                  "project",
                  'runs',
                  "pages",
                  "description",
                  "has_started",
                  "created",
                  "updated")
