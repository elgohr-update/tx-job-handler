# NOTE: This module name and function name are defined by the rq package and our own tx-enqueue-job package
# This code adapted by RJH June 2018 from tx-manager/client_webhook/ClientWebhook/process_webhook

# NOTE: rq_settings.py is executed at program start-up, reads some environment variables, and sets queue name, etc.
#       job() function (at bottom here) is executed by rq package when there is an available entry in the named queue.

# Python imports
import os
import tempfile
import json
from datetime import datetime, timedelta, date
from time import time
import sys
sys.setrecursionlimit(1500) # Default is 1,000 -- beautifulSoup hits this limit with UST
import traceback

# Library (PyPi) imports
import requests
from statsd import StatsClient # Graphite front-end

# Local imports
from rq_settings import prefix, debug_mode_flag
from general_tools.file_utils import unzip, remove_tree
from general_tools.url_utils import download_file
from global_settings.global_settings import GlobalSettings

from linters.obs_linter import ObsLinter
from linters.ta_linter import TaLinter
from linters.tn_linter import TnLinter, TnTsvLinter
from linters.tq_linter import TqLinter
from linters.tw_linter import TwLinter
from linters.markdown_linter import MarkdownLinter
# from linters.udb_linter import UdbLinter
# from linters.ulb_linter import UlbLinter
from linters.usfm_linter import UsfmLinter
from linters.lexicon_linter import LexiconLinter

from converters.md2html_converter import Md2HtmlConverter
from converters.tsv2html_converter import Tsv2HtmlConverter
from converters.usfm2html_converter import Usfm2HtmlConverter

# NOTE: The following two tables are each scanned in order
#       (so put 'other' entries lower)
# All searching of the tables is case-sensitive
# Columns are: 1/ linter name 2/ linter 3/ input formats 4/ resource types
LINTER_TABLE = (
    ('obs',      ObsLinter,      ('md',),      ('Open_Bible_Stories','obs'),              ),
    ('ta',       TaLinter,       ('md',),      ('Translation_Academy','ta'),              ),
    ('tn-tsv',   TnTsvLinter,    ('tsv',),     ('TSV_Translation_Notes','tn'),            ),
    ('tn',       TnLinter,       ('md',),      ('OBS_Translation_Notes',
                                                'Translation_Notes','tn'),                ),
    ('tq',       TqLinter,       ('md',),      ('Translation_Questions',
                                                'OBS_Translation_Questions','tq'),        ),
    ('tw',       TwLinter,       ('md',),      ('Translation_Words','tw'),                ),
    ('lexicon',  LexiconLinter,  ('md',),      ('Greek_Lexicon','Hebrew_Aramaic_Lexicon'), ),
    ('markdown', MarkdownLinter, ('md','txt'), ('Generic_Markdown','other'),              ),
    ('usfm',     UsfmLinter,     ('usfm',),    ('Bible','Aligned_Bible',
                                                'Greek_New_Testament','Hebrew_Old_Testament',
                                                'bible', 'reg', 'other'),                 ),
    )
# Columns are: 1/ converter name 2/ converter 3/ input formats 4/ resource types 5/ output format
CONVERTER_TABLE = (
    ('md2html',   Md2HtmlConverter,   ('md','markdown','txt','text'),
                    ('Generic_Markdown',
                    'Open_Bible_Stories','OBS_Translation_Notes','OBS_Translation_Questions','obs',
                    'Translation_Academy','ta', 'Translation_Questions','tq', 'Translation_Words',
                    'Translation_Words','tw', 'Translation_Notes','tn',
                    'Greek_Lexicon', 'Hebrew_Aramaic_Lexicon',
                'other',),                                                          'html'),
    ('tsv2html',  Tsv2HtmlConverter,  ('tsv',),
                    ('TSV_Translation_Notes','tn',
                    'other',),                                                      'html'),
    ('usfm2html', Usfm2HtmlConverter, ('usfm',),
                    ('Bible','Aligned_Bible',
                    'Greek_New_Testament','Hebrew_Old_Testament',
                    'bible', 'reg',
                    'other',),                                                      'html'),
    )


GlobalSettings(prefix=prefix)
if prefix not in ('', 'dev-'):
    GlobalSettings.logger.critical(f"Unexpected prefix: {prefix!r} -- expected '' or 'dev-'")
stats_prefix = f"tx.{'dev' if prefix else 'prod'}.job-handler"


# Get the Graphite URL from the environment, otherwise use a local test instance
graphite_url = os.getenv('GRAPHITE_HOSTNAME', 'localhost')
stats_client = StatsClient(host=graphite_url, port=8125, prefix=stats_prefix)



def get_linter_module(glm_job):
    """
    :param dict glm_job:
    :return linter name and linter class:
    """
    # Search the table to find the appropriate linter
    for linter_name, linter_class, input_formats, resource_types in LINTER_TABLE:
        if glm_job['input_format'] in input_formats:
            if glm_job['resource_type'] in resource_types:
                return linter_name, linter_class
            if 'other' in resource_types:
                GlobalSettings.logger.warning(f"Got linter from 'other' for input_format='{glm_job['input_format']}' and resource_type='{glm_job['resource_type']}'")
                return linter_name, linter_class
    #linters = TxModule.query().filter(TxModule.type == 'linter') \
        #.filter(TxModule.input_format.contains(glm_job['input_format']))
    #linter = linters.filter(TxModule.resource_types.contains(glm_job['resource_type'])).first()
    #if not linter:
        #linter = linters.filter(TxModule.resource_types.contains('other')).first()
    return None, None
# end of get_linter_module function


def do_linting(param_dict, source_dir, linter_name, linter_class):
    """
    :param dict param_dict: Will be updated for build log!
    :param str linter_name:
    """
    GlobalSettings.logger.debug(f"do_linting( {param_dict}, {source_dir}, {linter_name}, {linter_class} )")
    param_dict['status'] = 'linting'

    # TODO: Why does the linter download the (zip) file again???
    #linter = linter_class(source_url=param_dict['source'])
    # TODO: Why does the linter not find books if we give it the preprocessed files???
    linter = linter_class(repo_subject=param_dict['resource_type'], source_dir=source_dir)
    lint_result = linter.run()
    linter.close()  # do cleanup after run
    param_dict['linter_success'] = lint_result['success']
    param_dict['linter_warnings'] = lint_result['warnings']
    param_dict['status'] = 'linted'
    # GlobalSettings.logger.debug(f"do_linting is returning with {param_dict}")
    #return param_dict
# end of do_linting function


def get_converter_module(gcm_job):
    """
    :param dict gcm_job:
    :return TxModule:
    """
    for converter_name, converter_class, input_formats, resource_types, output_format in CONVERTER_TABLE:
        if gcm_job['input_format'] in input_formats and  output_format == gcm_job['output_format']:
            if gcm_job['resource_type'] in resource_types:
                return converter_name, converter_class
            if 'other' in resource_types:
                GlobalSettings.logger.warning(f"Got converter from 'other' for input_format='{gcm_job['input_format']}' and resource_type='{gcm_job['resource_type']}'")
                return converter_name, converter_class
    #converters = TxModule.query().filter(TxModule.type == 'converter') \
        #.filter(TxModule.input_format.contains(gcm_job['input_format'])) \
        #.filter(TxModule.output_format.contains(gcm_job['output_format']))
    #converter = converters.filter(TxModule.resource_types.contains(gcm_job['resource_type'])).first()
    #if not converter:
        #converter = converters.filter(TxModule.resource_types.contains('other')).first()
    return None, None
# end if get_converter_module function


def do_converting(param_dict, source_dir, converter_name, converter_class):
    """
    :param dict param_dict: Will be updated for build log!
    :param str converter_name:
    """
    GlobalSettings.logger.debug(f"do_converting( {len(param_dict)} fields, {source_dir}, {converter_name}, {converter_class} )")
    param_dict['status'] = 'converting'

    cdn_file_key = param_dict['output'].split('cdn.door43.org/')[1] # Get the last part
    converter = converter_class( param_dict['resource_type'],
                                 source_dir=source_dir,
                                 cdn_file_key=cdn_file_key) # Key for uploading
    convert_result_dict = converter.run()
    converter.close() # do cleanup after run
    param_dict['converter_success'] = convert_result_dict['success']
    param_dict['converter_info'] = convert_result_dict['info']
    param_dict['converter_warnings'] = convert_result_dict['warnings']
    param_dict['converter_errors'] = convert_result_dict['errors']
    param_dict['status'] = 'converted'
    # GlobalSettings.logger.debug(f"do_converting is returning with {param_dict}")
    #return param_dict
# end of do_converting function


def download_source_file(source_url, destination_folder):
    """
    Downloads the specified source file
        and unzips it if necessary.

    :param str source_url: The URL of the file to download
    :param str destination_folder:   The directory where the downloaded file should be unzipped
    :return: None
    """
    GlobalSettings.logger.debug(f"download_source_file( {source_url}, {destination_folder} )")
    source_filepath = os.path.join(destination_folder, source_url.rpartition(os.path.sep)[2])
    GlobalSettings.logger.info(f"source_filepath: {source_filepath}")

    try:
        GlobalSettings.logger.debug(f"Downloading {source_url} …")

        # if the file already exists, remove it, we want a fresh copy
        if os.path.isfile(source_filepath):
            os.remove(source_filepath)

        download_file(source_url, source_filepath)
    finally:
        GlobalSettings.logger.debug("Downloading finished.")

    if source_url.lower().endswith('.zip'):
        try:
            GlobalSettings.logger.debug(f"Unzipping {source_filepath} …")
            # TODO: This is unsafe if the zipfile comes from an untrusted source
            unzip(source_filepath, destination_folder)
        finally:
            GlobalSettings.logger.debug("Unzipping finished.")

        # clean up the downloaded zip file
        if os.path.isfile(source_filepath):
            os.remove(source_filepath)

    str_filelist = str(os.listdir(destination_folder))
    str_filelist_adjusted = str_filelist if len(str_filelist)<1500 \
                            else f'{str_filelist[:1000]} …… {str_filelist[-500:]}'
    GlobalSettings.logger.debug(f"Destination folder '{destination_folder}' now has: {str_filelist_adjusted}")
#end of download_source_file function


def process_tx_job(pj_prefix, queued_json_payload):
    """
    pj_prefix is normally 'dev-' or ''

    queued_json_payload MUST have the following fields:
        job_id (string)
        source (url string of zip file)
        resource_type = a subject as specified in https://api.door43.org/v3/subjects
        input_format (e.g., md, usfm, tsv)
        output_format (currently only 'html' is recognised)
    The following OPTIONAL fields are used if present:
        identifier (string)
        options (dict)
        callback (url string)
    The following fields are included by the Door43 Job Handler but ignored here:
        user_token
        door43_webhook_received_at

    Conversion and linting are now initiated by sending a request to each.

    This code is "successful" once the conversion/linting jobs are all completed.

    Does a callback (if requested) to advise of completion.

    The given payload will be appended to the 'failed' queue
        if an exception is thrown in this module.
    """
    GlobalSettings.logger.debug(f"Processing {pj_prefix+' ' if pj_prefix else ''}job: {queued_json_payload}")
    job_descriptive_name = f"{queued_json_payload['resource_type']}({queued_json_payload['input_format']})"
    if 'identifier' in queued_json_payload and queued_json_payload['identifier'] \
    and queued_json_payload['identifier'] != queued_json_payload['job_id']:
        job_descriptive_name = f"{queued_json_payload['identifier']} {job_descriptive_name}"

    # Create a build log
    build_log_dict = queued_json_payload.copy()
    # Delete unneeded fields from our response
    for fieldname in ('callback',):
        if fieldname in build_log_dict:
            del build_log_dict[fieldname]
    build_log_dict['started_at'] = datetime.utcnow()
    if 'expires_at' not in build_log_dict:
        build_log_dict['expires_at'] = build_log_dict['started_at'] + timedelta(days=1)
    if 'eta' not in build_log_dict:
        build_log_dict['eta'] = build_log_dict['started_at'] + timedelta(minutes=5)
    build_log_dict['status'] = 'started'
    build_log_dict['message'] = 'tX job started…'

    # Setup a temp folder to use
    # Move everything down one directory level for simple delete
    base_temp_dir_name = os.path.join(tempfile.gettempdir(), f"tX_job_{queued_json_payload['job_id']}")
    GlobalSettings.logger.debug(f"base_temp_dir_name = {base_temp_dir_name}")
    try:
        os.makedirs(base_temp_dir_name)
    except:
        GlobalSettings.logger.critical(f"Oh, folder {base_temp_dir_name} already existed!")
        GlobalSettings.logger.info(f"It contained {os.listdir(base_temp_dir_name)}")

    # Download and unzip the specified source file
    GlobalSettings.logger.debug(f"Getting source file from {queued_json_payload['source']} …")
    download_source_file(queued_json_payload['source'], base_temp_dir_name)

    # Find correct source folder
    source_folder_path = base_temp_dir_name
    dirList = os.listdir(base_temp_dir_name)
    str_dirList = str(dirList)
    str_dirList_adjusted = str_dirList if len(str_dirList)<1500 \
                            else f'{str_dirList[:1000]} …… {str_dirList[-500:]}'
    GlobalSettings.logger.debug(f"Discovering source folder from"
                                f" '{base_temp_dir_name}' with {str_dirList_adjusted} …")
    if len(dirList) == 1:
        tryFolder = os.path.join(base_temp_dir_name, dirList[0])
        if os.path.isdir(tryFolder):
            GlobalSettings.logger.debug(f"Switching source folder to {tryFolder}")
            source_folder_path = tryFolder
    if source_folder_path != base_temp_dir_name:
        GlobalSettings.logger.info(f"Source folder '{source_folder_path}'"
                                   f" contains {os.listdir(source_folder_path)}")

    # Save some stats
    stats_client.incr(f"jobs.format.{queued_json_payload['input_format']}_{queued_json_payload['output_format']}")
    stats_client.incr(f"jobs.identifier.{queued_json_payload['resource_type']}")


    # Find the correct linter and converter
    GlobalSettings.logger.debug(f"Finding linter and converter for {queued_json_payload['input_format']}"
                                f" '{queued_json_payload['resource_type']}'")
    linter_name, linter = get_linter_module(queued_json_payload)
    GlobalSettings.logger.info(f"Got linter = {linter_name}")
    converter_name, converter = get_converter_module(queued_json_payload)
    GlobalSettings.logger.info(f"Got converter = {converter_name}")

    # Run the linter first
    if linter:
        build_log_dict['lint_module'] = linter_name
        # Log dict gets updated by the following line
        do_linting(build_log_dict, source_folder_path, linter_name, linter)
    else:
        warning_message = f"No linter was found to lint {queued_json_payload['input_format']}" \
                          f" {queued_json_payload['resource_type']}"
        GlobalSettings.logger.warning(warning_message)
        build_log_dict['lint_module'] = 'NO LINTER'
        build_log_dict['linter_success'] = 'false'
        build_log_dict['linter_warnings'] = [warning_message]

    # Now run the converter
    if converter:
        build_log_dict['convert_module'] = converter_name
        # Log dict gets updated by the following line
        do_converting(build_log_dict, source_folder_path, converter_name, converter)
    else:
        error_message = f"No converter was found to convert {queued_json_payload['resource_type']}" \
                        f" from {queued_json_payload['input_format']} to {queued_json_payload['output_format']}"
        GlobalSettings.logger.error(error_message)
        build_log_dict['convert_module'] = 'NO CONVERTER'
        build_log_dict['converter_success'] = 'false'
        build_log_dict['converter_info'] = []
        build_log_dict['converter_warnings'] = []
        build_log_dict['converter_errors'] = [error_message]


    # Do the callback (if requested) to advise the caller of our results
    if 'callback' in queued_json_payload:
        GlobalSettings.logger.info(f"tX JobHandler about to do callback to {queued_json_payload['callback']} …")
        # Copy the build log but convert times to strings
        callback_payload = build_log_dict
        for key, value in callback_payload.items():
            if isinstance(value, (datetime, date)):
                callback_payload[key] = value.strftime('%Y-%m-%dT%H:%M:%SZ')

        stats_client.incr('callbacks.attempted')
        try:
            response = requests.post(queued_json_payload['callback'], json=callback_payload)
        except requests.exceptions.ConnectionError as e:
            GlobalSettings.logger.critical(f"Callback connection error: {e}")
            response = None
        if response:
            #GlobalSettings.logger.info(f"response.status_code = {response.status_code}, response.reason = {response.reason}")
            #GlobalSettings.logger.debug(f"response.headers = {response.headers}")
            try:
                GlobalSettings.logger.info(f"response.json = {response.json()}")
            except json.decoder.JSONDecodeError:
                GlobalSettings.logger.info("No valid response JSON found")
                GlobalSettings.logger.debug(f"response.text = {response.text}")
            if response.status_code != 200:
                GlobalSettings.logger.critical(f"Failed to submit callback to Door43:"
                                               f" {response.status_code}={response.reason}")
        else: # no response
            error_msg = "Submission of callback job to Door43 system got no response"
            GlobalSettings.logger.critical(error_msg)
            #raise Exception(error_msg) # Is this the best thing to do here?
    else:
        GlobalSettings.logger.info("No callback requested.")

    if prefix and debug_mode_flag:
        GlobalSettings.logger.debug(f"Temp folder '{base_temp_dir_name}' has been left on disk for debugging!")
    else:
        remove_tree(base_temp_dir_name)  # cleanup
    str_build_log = str(build_log_dict)
    str_build_log_adjusted = str_build_log if len(str_build_log)<1500 \
                            else f'{str_build_log[:1000]} …… {str_build_log[-500:]}'
    GlobalSettings.logger.info(f"{prefix}process_tx_job() for {job_descriptive_name} is returning with {str_build_log_adjusted}")
    return job_descriptive_name
#end of process_tx_job function


def job(queued_json_payload):
    """
    This function is called by the rq package to process a job in the queue(s).

    The job is removed from the queue before the job is started,
        but if the job throws an exception or times out (timeout specified in enqueue process)
            then the job gets added to the 'failed' queue.
    """
    GlobalSettings.logger.info("tX JobHandler received a job" + (" (in debug mode)" if debug_mode_flag else ""))
    start_time = time()
    stats_client.incr('jobs.attempted')

    #current_job = get_current_job()
    #print(f"Current job: {current_job}") # Mostly just displays the job number and payload
    #print("dir",dir(current_job))
    #print("id",current_job.id) # Displays job number
    #print("origin",current_job.origin) # Displays queue name
    #print("meta",current_job.meta) # Empty dict

    #print(f"Got a job from {current_job.origin} queue: {queued_json_payload}")
    #print(f"\nGot job {current_job.id} from {current_job.origin} queue")
    #queue_prefix = 'dev-' if current_job.origin.startswith('dev-') else ''
    #assert queue_prefix == prefix
    try:
        job_descriptive_name = process_tx_job(prefix, queued_json_payload)
    except Exception as e:
        # Catch most exceptions here so we can log them to CloudWatch
        prefixed_name = f"{prefix}tX_JobHandler"
        GlobalSettings.logger.critical(f"{prefixed_name} threw an exception while processing: {queued_json_payload}")
        GlobalSettings.logger.critical(f"{e}: {traceback.format_exc()}")
        GlobalSettings.close_logger() # Ensure queued logs are uploaded to AWS CloudWatch
        # Now attempt to log it to an additional, separate FAILED log
        import logging
        from boto3 import Session
        from watchtower import CloudWatchLogHandler
        logger2 = logging.getLogger(prefixed_name)
        test_mode_flag = os.getenv('TEST_MODE', '')
        travis_flag = os.getenv('TRAVIS_BRANCH', '')
        log_group_name = f"FAILED_{'' if test_mode_flag or travis_flag else prefix}tX" \
                         f"{'_DEBUG' if debug_mode_flag else ''}" \
                         f"{'_TEST' if test_mode_flag else ''}" \
                         f"{'_TravisCI' if travis_flag else ''}"
        aws_access_key_id = os.environ['AWS_ACCESS_KEY_ID']
        boto3_session = Session(aws_access_key_id=aws_access_key_id,
                            aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'],
                            region_name='us-west-2')
        watchtower_log_handler = CloudWatchLogHandler(boto3_session=boto3_session,
                                                    use_queues=False,
                                                    log_group=log_group_name,
                                                    stream_name=prefixed_name)
        logger2.addHandler(watchtower_log_handler)
        logger2.setLevel(logging.DEBUG)
        logger2.info(f"Logging to AWS CloudWatch group '{log_group_name}' using key '…{aws_access_key_id[-2:]}'.")
        logger2.critical(f"{prefixed_name} threw an exception while processing: {queued_json_payload}")
        logger2.critical(f"{e}: {traceback.format_exc()}")
        watchtower_log_handler.close()
        raise e # We raise the exception again so it goes into the failed queue

    elapsed_milliseconds = round((time() - start_time) * 1000)
    stats_client.timing('job.duration', elapsed_milliseconds)
    if elapsed_milliseconds < 2000:
        GlobalSettings.logger.info(f"{prefix}tX job handling for {job_descriptive_name} completed in {elapsed_milliseconds:,} milliseconds.")
    else:
        GlobalSettings.logger.info(f"{prefix}tX job handling for {job_descriptive_name} completed in {round(time() - start_time)} seconds.")

    stats_client.incr('jobs.completed')
    GlobalSettings.close_logger() # Ensure queued logs are uploaded to AWS CloudWatch
# end of job function

# end of webhook.py
