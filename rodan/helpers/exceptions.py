

class RodanError(Exception):
    """ BagIt Errors """
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return repr(self.message)


class RodanJobError(RodanError):
    pass


class InvalidFirstJobError(RodanError):
    pass


class UUIDParseError(RodanError):
    pass


class WorkFlowTriedTooManyTimesError(RodanError):
    pass


class NeonTempDirectoryError(RodanError):
    pass


class BagNotValidError(RodanError):
    pass


class ObjectDeletedError(RodanError):
    pass


class PackageCancelledError(RodanError):
    pass
