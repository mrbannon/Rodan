from rodan.jobs.utils import rodan_multi_page_task
from rodan.celery_models.jobtype import JobType
from rodan.celery_models.jobbase import JobBase
from mei_resources.meicombine import MeiCombiner


@rodan_multi_page_task(inputs='mei')
def combine_mei(mei_paths, **kwargs):
    mc = MeiCombiner(mei_paths)
    mc.combine()
    combined_mei = mc.get_mei()

    return {
        'mei': combined_mei,
    }


class CombineMei(JobBase):
    name = 'Combine all MEI files'
    slug = 'combine-mei'
    input_type = JobType.CORRECTED_MEI
    output_type = JobType.END
    description = 'Make a single MEI file out of all images'
    show_during_wf_create = True
    is_automatic = True
    outputs_image = False
    task = combine_mei
    all_pages = True
