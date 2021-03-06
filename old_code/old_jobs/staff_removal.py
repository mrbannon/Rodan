from rodan.jobs.utils import rodan_task
from rodan.celery_models.jobtype import JobType
from rodan.celery_models.jobbase import JobBase

import gamera.core
import gamera.toolkits.musicstaves
gamera.core.init_gamera()


@rodan_task(inputs='tiff')
def remove_staves(image_filepath, **kwargs):
    #the constructor converts to onebit if its not ONEBIT. Note that it will simply convert, no binarisation process
    music_staves = gamera.toolkits.musicstaves.MusicStaves_rl_roach_tatem(gamera.core.load_image(image_filepath), 0, 0)
    music_staves.remove_staves('all', 0)

    output_image = music_staves.image

    return {
        'tiff': output_image
    }


class StaffRemoval(JobBase):
    name = 'Staff removal'
    slug = 'staff-remove'
    input_type = JobType.SEGMENTED_IMAGE
    output_type = JobType.NEUME_IMAGE
    description = 'Remove stafflines from an image.'
    show_during_wf_create = True
    parameters = {
    }
    task = remove_staves
    is_automatic = True
