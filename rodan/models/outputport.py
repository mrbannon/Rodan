from django.db import models
from uuidfield import UUIDField


class OutputPort(models.Model):
    """
    Represents what a `WorkflowJob` will produce when it is executed.

    The number of `OutputPort`s for a particular `OutputPortType` must be within the
    associated `OutputPortType.minimum` and `OutputPortType.maximum` values.

    **Fields**

    - `uuid`
    - `workflow_job` -- a foreign key reference to the associated `WorkflowJob`.
    - `output_port_type` -- a foreign key reference to associated `OutputPortType`.
    - `label` -- an optional name unique to the other `OutputPort`s in the `WorkflowJob`
      (only for the user).

    **Methods**

    - `save` and `delete` -- invalidate the associated `Workflow`.
    - `save` -- set `label` to the name of its associated `OutputPortType` as a
      default value.
    """
    class Meta:
        app_label = 'rodan'

    uuid = UUIDField(primary_key=True, auto=True)
    workflow_job = models.ForeignKey('rodan.WorkflowJob', related_name='output_ports')
    output_port_type = models.ForeignKey('rodan.OutputPortType')
    label = models.CharField(max_length=255, null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.label:
            self.label = self.output_port_type.name
        super(OutputPort, self).save(*args, **kwargs)

        wf = self.workflow_job.workflow
        wf.valid = False
        wf.save()  # always touch workflow to update the `update` field.

    def delete(self, *args, **kwargs):
        wf = self.workflow_job.workflow
        super(OutputPort, self).delete(*args, **kwargs)
        wf.valid = False
        wf.save()  # always touch workflow to update the `update` field.

    def __unicode__(self):
        return u"<OutputPort {0}>".format(str(self.uuid))
