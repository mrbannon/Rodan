from rodan.utils import remove_prefixes


# These are not actual Django models
class JobBase:
    is_automatic = False
    is_required = False
    outputs_image = True
    name = ''
    slug = ''
    description = ''
    template = ''
    """A dict of parameters to pass to a celery task"""
    parameters = {}
    """The celery task to execute"""
    task = None
    enabled = True
    """ True if this job requires all of the pages to be at this step
    before it is run (i.e. multi-page jobs) """
    all_pages = False

    def get_name(self):
        return self.name or remove_prefixes(self.__class__.__name__)

    def get_slug(self):
        """If the child class defines a slug, use that; otherwise, take the
        class name and just convert it to lowercase.
        """
        return self.slug or self.get_name().lower().replace(" ", "-")

    def get_context(self, page):
        """
        Override this if you want to pass custom variables to the template.
        Will be accessible in the template as "context" (so if you return
        {'blah': 'blah'}, then it's accessible through {{ context.blah }} in
        the template.
        """
        return {}

    def on_post(self, result_id, **kwargs):
        """
        If you want to perform a custom action after submit that is
        not a celery task, override this.
        In the case of a multi-page job, a list of result_ids will be passed
        into the result_id parameter.
        """
        self.task.delay(result_id, **kwargs)

    def set_unknown_param_type(self, unknown_value):
        """
        This is used if you want to get an unknown_value, returning it with a new type,
        either a float if it is a number or a string if it is not. This is used because
        request.POST returns values of type <unicode>
        """
        try:
            return float(unknown_value)
        except ValueError:
            return str(unknown_value)

    def get_parameters(self, job_object, input_values, **kwargs):
        """
        Populates the kwargs with job_object parameters. If there exists a parameter
        that has no default type/value in the job definition then it gets a type from
        the input value using set_unknown_param_type. Also if there is a default value
        not in request.POST that is in the job definition then it adds that to kwargs
        with the default
        """

        default_inputs = ['csrfmiddlewaretoken', 'submit']
        default_parameters = job_object.parameters

        for parameter in input_values:
            if parameter not in default_inputs:
                value = input_values[parameter]

                if parameter in default_parameters:
                    param_type = type(default_parameters[parameter])
                    kwargs[parameter] = param_type(value)
                else:
                    kwargs[parameter] = self.set_unknown_param_type(value)
        for parameter, default in default_parameters.iteritems():
            if parameter not in input_values:
                kwargs[parameter] = default
        return kwargs
