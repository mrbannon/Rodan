from django.utils import unittest
from django.conf import settings

from rodan.models.jobs import JobType
from rodan.models.projects import JobItem, RodanUser, Page
from rodan.models.results import Result, Parameter, ResultFile


class TestResult(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ji = JobItem.objects.get(pk=3)
        cls.user = RodanUser.objects.get(pk=1)
        cls.page = Page.objects.get(pk=1)
        cls.result = Result(job_item=cls.ji, user=cls.user, page=cls.page)
        cls.result.save()

    def testSaveParams(self):
        params = {"param1": "v1",
                  "param2": "v2"
                 }
        self.result.save_parameters(**params)
        savedParams = self.result.parameter_set.all()

        self.assertEqual(2, len(savedParams))
        # Because params are unordered, we don't know how they're
        # saved. Just check generally
        self.assertTrue(savedParams[0].key in ["param1", "param2"])
        self.assertTrue(savedParams[0].value in ["v1", "v2"])

    def testCreateFile(self):
        self.result.create_file(settings.MEDIA_ROOT + "testfilename", 'tiff')

        self.assertEqual(1, len(self.result.resultfile_set.all()))
        files = self.result.resultfile_set.all()
        self.assertEqual("testfilename", files[0].filename)
        # Default
        self.assertEqual('tiff', files[0].result_type)

        self.result.create_file(settings.MEDIA_ROOT + "anotherfile", 'mei')
        self.assertEqual(2, len(self.result.resultfile_set.all()))
        files = self.result.resultfile_set.all()
        self.assertEqual('mei', files[1].result_type)
