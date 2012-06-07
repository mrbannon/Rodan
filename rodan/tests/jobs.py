from django.utils import unittest
from rodan.models.projects import Job

class TestTyping(unittest.TestCase):
    def setUp(self):
        self.binarise = Job.objects.get(name="Binarise (simple threshold)")
        self.rotate = Job.objects.get(name="Rotate")

    def runTest(self):
        # A simple test for now, until the real types are set up
        self.assertTrue(self.rotate in self.binarise.get_compatible_jobs())
        self.assertFalse(self.binarise in self.rotate.get_compatible_jobs())