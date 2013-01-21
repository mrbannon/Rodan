from django.db import models
from django_extensions.db.fields import json
from uuidfield import UUIDField


class Job(models.Model):
    uuid = UUIDField(primary_key=True, auto=True)
    name = models.CharField(max_length=255)
    author = models.CharField(max_length=255, blank=True, null=True)
    category = models.CharField(max_length=255, blank=True, null=True)

    input_types = json.JSONField(blank=True, null=True)
    output_types = json.JSONField(blank=True, null=True)
    arguments = json.JSONField(blank=True, null=True)

    enabled = models.BooleanField()

    def __unicode__(self):
        return u"{0}".format(self.name)

    class Meta:
        app_label = 'rodan'