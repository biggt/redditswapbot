import sys
import os
from configparser import SafeConfigParser
import logging

# load config file
containing_dir = os.path.abspath(os.path.dirname(sys.argv[0]))
cfg_file = SafeConfigParser()
path_to_cfg = os.path.join(containing_dir, 'config.cfg')
cfg_file.read(path_to_cfg)
SENTRY = cfg_file.get('logging', 'sentry')


try:
    import sentry_sdk
except ImportError:
    # sentry_sdk not installed, skip sentry even though config exists
    SENTRY = ""


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances.keys():
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)

        return cls._instances[cls]


class LoggerManager(metaclass=Singleton):  # pylint: disable=too-few-public-methods
    _loggers = {}

    def __init__(self, *_args, **kwargs):
        if SENTRY and "disable_sentry" not in kwargs:
            sentry_sdk.init(SENTRY)

    @staticmethod
    def getLogger(name=None):  # pylint: disable=invalid-name
        LoggerManager._loggers[name] = logging.getLogger(name)
        LoggerManager._loggers[name].setLevel(logging.INFO)

        fileh = logging.FileHandler('actions.log')
        fileh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(module)s - %(message)s'))
        LoggerManager._loggers[name].addHandler(fileh)

        requests_log = logging.getLogger("requests")
        requests_log.setLevel(logging.WARNING)

        return LoggerManager._loggers[name]
