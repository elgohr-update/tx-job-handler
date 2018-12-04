import sys
import os
import logging
import re

# from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from aws_tools.s3_handler import S3Handler
from boto3 import Session
from watchtower import CloudWatchLogHandler

from rq_settings import debug_mode_flag


# TODO: Investigate if this GlobalSettings (was tx-Manager App) class still needs to be resetable now
def resetable(cls):
    cls._resetable_cache_ = cls.__dict__.copy()
    return cls


def reset_class(cls):
    #print("reset_class()!!!")
    cache = cls._resetable_cache_  # raises AttributeError on class without decorator
    # Remove any class variables that weren't in the original class as first instantiated
    for key in [key for key in cls.__dict__ if key not in cache and key != '_resetable_cache_']:
        delattr(cls, key)
    # Reset the items to original values
    for key, value in cache.items():
        try:
            if key != '_resetable_cache_':
                setattr(cls, key, value)
        except AttributeError: # When/Why would we get this
            pass
    cls.dirty = False


def setup_logger(logger, watchtower_log_handler, level):
    """
    Logging for the app, and turn off boto logging.
    Set here so automatically ready for any logging calls
    :param logger:
    :param level:
    :return:
    """
    for h in logger.handlers:
        logger.removeHandler(h)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s: %(message)s'))
    logger.addHandler(sh)
    logger.addHandler(watchtower_log_handler)
    logger.setLevel(level)
    # Change these loggers to only report errors:
    logging.getLogger('boto3').setLevel(logging.ERROR)
    logging.getLogger('botocore').setLevel(logging.ERROR)


@resetable
class GlobalSettings:
    """
    For all things used for by this app, from DB connection to global handlers
    """
    _resetable_cache_ = {}
    name = 'tx-job-handler' # Only used for logging and for testing GlobalSettings resets
    dirty = False

    # Stage Variables, defaults
    prefix = ''
    # api_url = 'https://api.door43.org'
    # pre_convert_bucket_name = 'tx-webhook-client'
    cdn_bucket_name = 'cdn.door43.org'
    # door43_bucket_name = 'door43.org'
    # module_table_name = 'modules'
    # language_stats_table_name = 'language-stats'
    linter_messaging_name = 'linter_complete'

    # Prefixing vars
    # All variables that we change based on production, development and testing environments.
    # prefixable_vars = ['api_url', 'pre_convert_bucket_name', 'cdn_bucket_name', 'door43_bucket_name', 'language_stats_table_name',
    #                    'linter_messaging_name', 'db_name', 'db_user']
    prefixable_vars = ['cdn_bucket_name', 'linter_messaging_name',]

    # DB related
    Base = declarative_base()  # To be used in all model classes as the parent class: GlobalSettings.ModelBase
    auto_setup_db = True
    manifest_table_name = 'manifests'
    # job_table_name = 'jobs'
    db_echo = False  # Whether or not to echo DB queries to the debug log. Useful for debugging. Set before setup_db()
    echo = False

    # Credentials -- get the secret ones from environment variables
    aws_access_key_id = os.environ['AWS_ACCESS_KEY_ID']
    aws_secret_access_key = os.environ['AWS_SECRET_ACCESS_KEY']
    aws_region_name = 'us-west-2'

    # Handlers
    # _db_engine = None
    # _db_session = None
    _cdn_s3_handler = None
    # _door43_s3_handler = None
    # _pre_convert_s3_handler = None
    # _language_stats_db_handler = None

    # Logger
    logger = logging.getLogger(name)
    log_group_name = f"{name}{'_TEST' if debug_mode_flag else ''}" \
                    f"{'_TravisCI' if os.getenv('TRAVIS_BRANCH', '') else ''}"
    boto3_session = Session(aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
                        aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'],
                        region_name='us-west-2')
    # NOTE: We have this code here coz we need to keep a reference to watchtower_log_handler
    #           (for closing it later)
    watchtower_log_handler = CloudWatchLogHandler(boto3_session=boto3_session,
                                                # use_queues=False, # Because this forked process is quite transient
                                                log_group=log_group_name)
    setup_logger(logger, watchtower_log_handler,
                            logging.DEBUG if debug_mode_flag else logging.INFO)
    logger.info(f"Logging to AWS CloudWatch group '{log_group_name}'.")


    def __init__(self, **kwargs):
        """
        Using init to set the class variables with GlobalSettings(var=value)
        :param kwargs:
        """
        #print("GlobalSettings.__init__({})".format(kwargs))
        self.init(**kwargs)

    @classmethod
    def init(cls, reset=True, **kwargs):
        """
        Class init method to set all vars
        :param bool reset:
        :param kwargs:
        """
        #print("GlobalSettings.init(reset={}, {})".format(reset,kwargs))
        if cls.dirty and reset:
            # GlobalSettings.db_close()
            reset_class(GlobalSettings)
        if 'prefix' in kwargs and kwargs['prefix'] != cls.prefix:
            cls.__prefix_vars(kwargs['prefix'])
        cls.set_vars(**kwargs)

    @classmethod
    def __prefix_vars(cls, prefix):
        """
        Prefixes any variables in GlobalSettings.prefixable_variables. This includes URLs
        :return:
        """
        if prefix:
            setup_logger(cls.logger, cls.watchtower_log_handler, logging.DEBUG)
        cls.logger.debug(f"GlobalSettings.prefix_vars with '{prefix}'")
        url_re = re.compile(r'^(https*://)')  # Current prefix in URLs
        for var in cls.prefixable_vars:
            value = getattr(GlobalSettings, var)
            if re.match(url_re, value):
                value = re.sub(url_re, r'\1{0}'.format(prefix), value)
            else:
                value = prefix + value
            #print("  With prefix now {}={!r}".format(var,value))
            setattr(GlobalSettings, var, value)
        cls.prefix = prefix
        cls.dirty = True


    @classmethod
    def set_vars(cls, **kwargs):
        #print("GlobalSettings.set_vars()…")
        # Sets all the given variables for the class, and then marks it as dirty
        for var, value in kwargs.items():
            if hasattr(GlobalSettings, var):
                setattr(GlobalSettings, var, value)
                cls.dirty = True


    @classmethod
    def cdn_s3_handler(cls):
        #print("GlobalSettings.cdn_s3_handler()…")
        if not cls._cdn_s3_handler:
            cls._cdn_s3_handler = S3Handler(bucket_name=cls.cdn_bucket_name,
                                            aws_access_key_id=cls.aws_access_key_id,
                                            aws_secret_access_key=cls.aws_secret_access_key,
                                            aws_region_name=cls.aws_region_name)
        return cls._cdn_s3_handler


    @classmethod
    def close_logger(cls):
        # Flushes queued log entries to AWS
        cls.watchtower_log_handler.close()
