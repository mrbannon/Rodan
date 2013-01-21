import os
import shutil
from django.db import models
from django.conf import settings
from rodan.models.project import Project
from django.contrib.auth.models import User
from uuidfield import UUIDField


class Page(models.Model):
    def upload_path(self, filename):
        _, ext = os.path.splitext(filename)
        return os.path.join("projects", str(self.project.uuid), "pages", str(self.uuid), "original_file{0}".format(ext.lower()))

    def compat_path(self, filename):
        _, ext = os.path.splitext(filename)
        return os.path.join("projects", str(self.project.uuid), "pages", str(self.uuid), "compat_file{0}".format(ext.lower()))

    uuid = UUIDField(primary_key=True, auto=True)
    project = models.ForeignKey(Project, related_name="pages")
    page_image = models.FileField(upload_to=upload_path, null=True)
    compat_page_image = models.FileField(upload_to=compat_path, null=True)
    page_order = models.IntegerField(null=True)
    image_file_size = models.IntegerField(null=True)  # in bytes
    processed = models.BooleanField(default=False)

    creator = models.ForeignKey(User, related_name="pages", null=True)

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        super(Page, self).save(*args, **kwargs)
        if not os.path.exists(self.thumb_path):
            os.makedirs(self.thumb_path)

    def delete(self, *args, **kwargs):
        if os.path.exists(self.image_path):
            shutil.rmtree(self.image_path)
        super(Page, self).delete(*args, **kwargs)

    class Meta:
        app_label = 'rodan'

    def __unicode__(self):
        return unicode(self.page_image.name)

    def thumb_filename(self, size):
        name, ext = os.path.splitext(self.filename)
        return "{0}_{1}{2}".format(name, size, ext.lower())

    @property
    def thumb_path(self):
        return os.path.join(self.image_path, "thumbnails")

    @property
    def thumb_url(self):
        return os.path.join(self.image_url, "thumbnails")

    @property
    def image_path(self):
        return os.path.dirname(self.page_image.path)

    @property
    def image_url(self):
        return os.path.dirname(self.page_image.url)

    @property
    def filename(self):
        return os.path.basename(self.page_image.path)

    @property
    def compat_file_path(self):
        return self.compat_page_image.path

    @property
    def compat_file_url(self):
        return self.compat_page_image.url

    @property
    def small_thumb_url(self):
        return os.path.join(self.thumb_url,
                            self.thumb_filename(size=settings.SMALL_THUMBNAIL))

    @property
    def medium_thumb_url(self):
        return os.path.join(self.thumb_url,
                            self.thumb_filename(size=settings.MEDIUM_THUMBNAIL))

    @property
    def large_thumb_url(self):
        return os.path.join(self.thumb_url,
                            self.thumb_filename(size=settings.LARGE_THUMBNAIL))