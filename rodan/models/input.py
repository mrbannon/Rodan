from django.db import models
from uuidfield import UUIDField


class Input(models.Model):
    class Meta:
        app_label = 'rodan'

    uuid = UUIDField(primary_key=True, auto=True)
    input_port = models.ForeignKey('rodan.InputPort')
    resource = models.ForeignKey('rodan.Resource')
    run_job = models.ForeignKey('rodan.RunJob')

    def __unicode__(self):
        return u"<Input {0}>".format(str(self.uuid))
