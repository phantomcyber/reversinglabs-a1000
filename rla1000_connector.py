# --
# File: rla1000_connector.py
#
# Copyright (c) ReversingLabs Inc 2016-2018
#
# This unpublished material is proprietary to ReversingLabs Inc.
# All rights reserved.
# Reproduction or distribution, in whole
# or in part, is forbidden except by express written permission
# of ReversingLabs Inc.
#
# --

# Phantom imports
import phantom.app as phantom
from phantom.app import BaseConnector
from phantom.app import ActionResult
try:
    from phantom.vault import Vault
except BaseException:
    import phantom.vault as Vault

from rla1000_consts import *

# Other imports used by this connector
import os
import time
import inspect
import json
import requests
# import xmltodict
import uuid
import re
import magic
import shutil


def __unicode__(self):
    return unicode(self.some_field) or u''


class A1000Connector(BaseConnector):

    # The actions supported by this connector
    ACTION_ID_DETONATE_FILE = "detonate_file"
    ACTION_ID_GET_REPORT = "get_report"
    ACTION_ID_REANALYZE_FILE = "reanalyze_file"
    ACTION_ID_TEST_ASSET_CONNECTIVITY = 'test_asset_connectivity'

    MAGIC_FORMATS = [
      (re.compile('^PE.* Windows'), ['pe file'], '.exe'),
      (re.compile('^MS-DOS executable'), ['pe file'], '.exe'),
      (re.compile('^PDF '), ['pdf'], '.pdf'),
      (re.compile('^MDMP crash'), ['process dump'], '.dmp'),
      (re.compile('^Macromedia Flash'), ['flash'], '.flv'),
      (re.compile('^tcpdump capture'), ['pcap'], '.pcap'),
    ]

    FILE_UPLOAD_ERROR_DESC = {
            '401': 'API key invalid',
            '405': 'HTTP method Not Allowed',
            '413': 'Sample file size over max limit',
            '418': 'Sample file type is not supported',
            '419': 'Max number of uploads per day exceeded',
            '422': 'URL download error',
            '500': 'Internal error',
            '513': 'File upload failed'}

    GET_REPORT_ERROR_DESC = {
            '401': 'API key invalid',
            '404': 'The report was not found',
            '405': 'HTTP method Not Allowed',
            '419': 'Request report quota exceeded',
            '420': 'Insufficient arguments',
            '421': 'Invalid arguments',
            '500': 'Internal error'}

    GET_SAMPLE_ERROR_DESC = {
            '401': 'API key invalid',
            '403': 'Permission Denied',
            '404': 'The sample was not found',
            '405': 'HTTP method Not Allowed',
            '419': 'Request sample quota exceeded',
            '420': 'Insufficient arguments',
            '421': 'Invalid arguments',
            '500': 'Internal error'}

    PLATFORM_ID_MAPPING = {
            'Default': None,
            'Win XP, Adobe 9.3.3, Office 2003': 1,
            'Win XP, Adobe 9.4.0, Flash 10, Office 2007': 2,
            'Win XP, Adobe 11, Flash 11, Office 2010': 3,
            'Win 7 32-bit, Adobe 11, Flash11, Office 2010': 4,
            'Win 7 64 bit, Adobe 11, Flash 11, Office 2010': 5,
            'Android 2.3, API 10, avd2.3.1': 201}

    def __init__(self):

        # Call the BaseConnectors init first
        super(A1000Connector, self).__init__()

        self._api_token = None

    def initialize(self):

        config = self.get_config()

        # Base URL
        self._base_url = config[A1000_JSON_BASE_URL]
        if (self._base_url.endswith('/')):
            self._base_url = self._base_url[:-1]

        self._host = self._base_url[self._base_url.find('//') + 2:]

        # self._req_sess = requests.Session()

        return phantom.APP_SUCCESS

    def _parse_error(self, response, result, error_desc):

        status_code = response.status_code
        detail = response.text

        if (detail):
            return result.set_status(
                phantom.APP_ERROR,
                A1000_ERR_REST_API.format(
                    status_code=status_code,
                    detail=json.loads(detail)['message']))

        if (not error_desc):
            return result.set_status(
                phantom.APP_ERROR, A1000_ERR_REST_API.format(
                    status_code=status_code, detail='N/A'))

        detail = error_desc.get(str(status_code))

        if (not detail):
            # no detail
            return result.set_status(
                phantom.APP_ERROR, A1000_ERR_REST_API.format(
                    status_code=status_code, detail='N/A'))

        return result.set_status(
            phantom.APP_ERROR,
            A1000_ERR_REST_API.format(
                status_code=status_code,
                detail=detail))

    def _make_rest_call(
            self,
            endpoint,
            result,
            error_desc,
            method="get",
            params={},
            data={},
            filein=None,
            files=None,
            parse_response=True,
            additional_succ_codes={}):

        url = "{0}{1}".format(self._base_url, endpoint)

        config = self.get_config()

        if (files is None):
            files = dict()

        if (filein is not None):
            files = {'file': filein}

        # request_func = getattr(self._req_sess, method)

        # if (not request_func):
        # return (result.set_status(phantom.APP_ERROR, "Invalid method call: {0}
        # for requests module".format(method)), None)

        if method == 'post':
            try:
                r = requests.post(url,
                                  data=data,
                                  files=files,
                                  verify=config[phantom.APP_JSON_VERIFY],
                                  headers={'Authorization': 'Token %s' % config[A1000_JSON_API_KEY]})
            except Exception as e:
                return (
                    result.set_status(
                        phantom.APP_ERROR,
                        "REST Api to server failed",
                        e),
                    None)
        else:
            try:
                r = requests.get(
                    url,
                    verify=config[phantom.APP_JSON_VERIFY],
                    headers={
                        'Authorization': 'Token %s' % config[A1000_JSON_API_KEY]})
            except Exception as e:
                return (
                    result.set_status(
                        phantom.APP_ERROR,
                        "REST Api to server failed",
                        e),
                    None)

        # It's ok if r.text is None, dump that
        if (hasattr(result, 'add_debug_data')):
            result.add_debug_data({'r_text': r.text if r else 'r is None'})

        if (r.status_code in additional_succ_codes):
            response = additional_succ_codes[r.status_code]
            return (
                phantom.APP_SUCCESS,
                response if response is not None else r.text)

        # Look for errors
        if not 200 <= r.status_code < 300:  # pylint: disable=E1101
            #self._parse_error(r, result, error_desc)
            return (phantom.APP_ERROR, r)

        if (not parse_response):
            return (phantom.APP_SUCCESS, r)

        response_dict = json.loads(r.text)

        return (phantom.APP_SUCCESS, response_dict)

    def _get_file_dict(self, param, action_result):

        vault_id = param['vault_id']

        filename = param.get('file_name')
        if not filename:
            filename = vault_id

        try:
            if (hasattr(Vault, 'get_file_path')):
                payload = open(Vault.get_file_path(vault_id), 'rb')
            else:
                payload = open(
                    Vault.get_vault_file(vault_id),
                    'rb')  # pylint: disable=E1101
        except BaseException:
            return (
                action_result.set_status(
                    phantom.APP_ERROR,
                    'File not found in vault ("{}")'.format(vault_id)),
                None)

        files = {'file': (filename, payload)}

        return (phantom.APP_SUCCESS, files)

    def _test_connectivity(self, param):
        # get the file from the app directory
        dirpath = os.path.dirname(inspect.getfile(self.__class__))
        filename = A1000_TEST_PDF_FILE

        filepath = "{}/{}".format(dirpath, filename)

        try:
            payload = open(filepath, 'rb')
        except BaseException:
            self.set_status(phantom.APP_ERROR,
                            'Test pdf file not found at "{}"'.format(filepath))
            self.append_to_message('Test Connectivity failed')
            return self.get_status()

        try:
            self.save_progress(
                'Detonating test pdf file for checking connectivity')
            files = payload
            ret_val, response = self._make_rest_call(
                '/api/uploads/', self, self.FILE_UPLOAD_ERROR_DESC,
                method='post', filein=files)
        except BaseException:
            self.set_status(
                phantom.APP_ERROR,
                'Connectivity failed, check the server name and API key.\n')
            self.append_to_message('Test Connectivity failed.\n')
            return self.get_status()

        if (phantom.is_fail(ret_val)):
            self.append_to_message('Test Connectivity Failed')
            return self.get_status()

        return self.set_status_save_progress(
            phantom.APP_SUCCESS, 'Test Connectivity Passed')

    def _normalize_into_list(self, input_dict, key):
        if (not input_dict):
            return None

        if (key not in input_dict):
            return None

        if (type(input_dict[key] != list)):
            input_dict[key] = [input_dict[key]]
        input_dict[key.lower()] = input_dict.pop(key)

        return input_dict

    def _normalize_children_into_list(self, input_dict):

        if (not input_dict):
            return {}

        for key in input_dict.keys():
            if (not isinstance(input_dict[key], list)):
                input_dict[key] = [input_dict[key]]
            input_dict[key.lower()] = input_dict.pop(key)

        return input_dict

    def _check_detonated_report(self, task_id, action_result):
        """This function is different than other functions that get the report
        since it is supposed to check just once and return, also treat a 404 as error
        """

        data = {'hash_values': [task_id], 'fields': A1000_PARAM_LIST['fields']}

        success, ticloud_response = self._make_rest_call(
            '/api/samples/%s/ticloud/' % task_id, action_result, self.GET_REPORT_ERROR_DESC,
            method='get',
            additional_succ_codes={404: A1000_MSG_REPORT_PENDING})

        success, ticore_response = self._make_rest_call(
            '/api/samples/%s/ticore/' % task_id, action_result, self.GET_REPORT_ERROR_DESC,
            method='get',
            additional_succ_codes={404: A1000_MSG_REPORT_PENDING})

        # ticore extracted
        success, ef_response = self._make_rest_call(
            '/api/samples/%s/extracted-files/' % task_id, action_result, self.GET_REPORT_ERROR_DESC,
            method='get',
            additional_succ_codes={404: A1000_MSG_REPORT_PENDING})

        success, summary_data = self._make_rest_call(
            '/api/samples/list/', action_result, self.GET_REPORT_ERROR_DESC, data=data,
            method='post',
            additional_succ_codes={404: A1000_MSG_REPORT_PENDING})

        if summary_data is not None and len(summary_data) > 0 and 'count' in summary_data and summary_data['count'] > 0:
            summary_data = summary_data['results'][0]
            if "story" in ticore_response:
                summary_data["story"] = ticore_response["story"]

            # remove hashes other than sha1
            if summary_data is not None and 'classification_origin' in summary_data and summary_data['classification_origin'] is not None and 'sha1' in summary_data['classification_origin']:
                summary_data['classification_origin'] = {'sha1': summary_data['classification_origin']['sha1']}


        return {"ticloud": ticloud_response}, {"ticore": [ticore_response, ef_response]}, summary_data


        # parse if successfull
        # response = self._parse_report_status_msg(response, action_result, data)

        #if (response):
        #    return (phantom.APP_SUCCESS, response)

        #return (phantom.APP_ERROR, None)

    def _poll_task_status(self, task_id, action_result):
        polling_attempt = 0

        config = self.get_config()

        timeout = config[A1000_JSON_POLL_TIMEOUT_MINS]

        if (not timeout):
            timeout = A1000_MAX_TIMEOUT_DEF

        max_polling_attempts = (int(timeout) * 60) / A1000_SLEEP_SECS

        data = {'hash_values': [task_id]}

        while (polling_attempt < max_polling_attempts):

            polling_attempt += 1

            self.save_progress(
                "Polling attempt {0} of {1}".format(
                    polling_attempt,
                    max_polling_attempts))

            ret_val, response = self._make_rest_call(
                '/api/samples/status/', action_result, self.GET_REPORT_ERROR_DESC,
                method='post', data=data,
                additional_succ_codes={404: A1000_MSG_REPORT_PENDING})

            if (phantom.is_fail(ret_val)):
                return (action_result.get_status(), None)

            # if results not processed postpone
            if ("results" in response and len(response["results"]) > 0):
                if response["results"][0]["status"] != "processed":
                    time.sleep(A1000_SLEEP_SECS)
                    continue
                else:
                    return True


        self.save_progress("Reached max polling attempts.")
        return False

        #return (action_result.set_status(phantom.APP_ERROR,A1000_MSG_MAX_POLLS_REACHED),None)

    def _get_report(self, param):

        action_result = self.add_action_result(ActionResult(dict(param)))

        task_id = param[A1000_JSON_VAULT_ID]

        # Now poll for the result
        try:
            ticloud, ticore, summary_data = self._check_detonated_report(task_id, action_result)
        except:
            action_result.add_data({"test": "fail"})

        #ret_val, response = self._poll_task_status(task_id, action_result)

        try:
            action_result.add_data(ticloud)
        except:
            action_result.add_data({"ticloud": "result not found"})
        try:
            action_result.add_data(ticore)
        except:
            action_result.add_data({"ticore": "result not found"})

        try:
            summary = {'a1000_report_url': "{0}{1}".format(
                    self._base_url, "/" + task_id)}
            summary.update(summary_data)
        except BaseException:
            summary = {}

        action_result.set_summary(summary)
        #action_result.set_summary(summary)
        # The next part is the report
        # data.update(response['results'][0])

        # malware = data.get('file_info', {}).get('malware', 'no')

        # action_result.update_summary({A1000_JSON_MALWARE: malware})

        return action_result.set_status(phantom.APP_SUCCESS)

    def _reanalyze_file(self, param):

        action_result = self.add_action_result(ActionResult(dict(param)))

        vault_id = param[A1000_JSON_VAULT_ID]  # sha1

        data = {'analysis': 'cloud'}
        #data = {'hash_value': [vault_id], 'analysis': 'cloud'}

        ret_val, response = self._make_rest_call(
            '/api/samples/%s/analyze/' % vault_id, action_result, self.GET_REPORT_ERROR_DESC,
            method='post', data=data,
            additional_succ_codes={404: "File not found and could not be queued for analysis"})

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()

        # Set summary
        try:
            result = {"Response": response['message']}
            data = action_result.add_data(result)
            action_result.set_summary(result)
        except BaseException:
            data = action_result.add_data({'response': response})
            action_result.set_summary({'response': response})

        return action_result.set_status(phantom.APP_SUCCESS)

    def _save_file_to_vault(self, action_result, response, sample_hash):

        # Create a tmp directory on the vault partition
        guid = uuid.uuid4()
        local_dir = '/vault/tmp/{}'.format(guid)
        self.save_progress("Using temp directory: {0}".format(guid))

        try:
            os.makedirs(local_dir)
        except Exception as e:
            return action_result.set_status(
                phantom.APP_ERROR,
                "Unable to create temporary folder '/vault/tmp'.", e)

        file_path = "{0}/{1}".format(local_dir, sample_hash)

        # open and download the file
        with open(file_path, 'wb') as f:
            f.write(response.content)

        contains = []
        file_ext = ''
        magic_str = magic.from_file(file_path)
        for regex, cur_contains, extension in self.MAGIC_FORMATS:
            if regex.match(magic_str):
                contains.extend(cur_contains)
                if (not file_ext):
                    file_ext = extension

        file_name = '{}{}'.format(sample_hash, file_ext)

        # move the file to the vault
        vault_ret_dict = Vault.add_attachment(
            file_path, self.get_container_id(),
            file_name=file_name, metadata={'contains': contains})
        curr_data = {}

        if (vault_ret_dict['succeeded']):
            curr_data[phantom.APP_JSON_VAULT_ID] = vault_ret_dict[phantom.APP_JSON_HASH]
            curr_data[phantom.APP_JSON_NAME] = file_name
            action_result.add_data(curr_data)
            wanted_keys = [phantom.APP_JSON_VAULT_ID, phantom.APP_JSON_NAME]
            summary = {x: curr_data[x] for x in wanted_keys}
            if (contains):
                summary.update({'file_type': ','.join(contains)})
            action_result.update_summary(summary)
            action_result.set_status(phantom.APP_SUCCESS)
        else:
            action_result.set_status(
                phantom.APP_ERROR,
                phantom.APP_ERR_FILE_ADD_TO_VAULT)
            action_result.append_to_message(vault_ret_dict['message'])

        # remove the /tmp/<> temporary directory
        shutil.rmtree(local_dir)

        return action_result.get_status()

    def _get_platform_id(self, param):

        platform = param.get(A1000_JSON_PLATFORM)

        if (not platform):
            return None

        platform = platform.upper()

        if (platform not in self.PLATFORM_ID_MAPPING):
            return None

        return self.PLATFORM_ID_MAPPING[platform]

    def validate_parameters(self, param):
        """Do our own validations instead of BaseConnector doing it for us"""

        return phantom.APP_SUCCESS

    def _get_vault_file_sha256(self, vault_id, action_result):

        self.save_progress('Getting the sha256 of the file')

        sha256 = None
        metadata = None

        if (hasattr(Vault, 'get_file_info')):
            try:
                metadata = Vault.get_file_info(
                    container_id=self.get_container_id(),
                    vault_id=vault_id)[0]['metadata']
            except Exception as e:
                self.debug_print('Handled Exception:', e)
                metadata = None
        else:
            try:
                metadata = Vault.get_meta_by_hash(
                    self.get_container_id(),
                    vault_id, calculate=True)[0]
            except BaseException:
                self.debug_print('Handled Exception:', e)
                metadata = None

        if (not metadata):
            return (
                action_result.set_status(
                    phantom.APP_ERROR,
                    "Unable to get meta info of vault file"),
                None)

        try:
            sha256 = metadata['sha256']
        except Exception as e:
            self.debug_print('Handled exception', e)
            return (
                action_result.set_status(
                    phantom.APP_ERROR,
                    "Unable to get meta info of vault file"),
                None)

        return (phantom.APP_SUCCESS, sha256)

    def _detonate_file(self, param):

        action_result = self.add_action_result(ActionResult(dict(param)))

        ret_val, files = self._get_file_dict(param, action_result)

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()

        # get the sha256 of the file
        vault_id = param['vault_id']
        ret_val, sha256 = self._get_vault_file_sha256(vault_id, action_result)

        if (phantom.is_fail(ret_val)):
            return action_result.get_status()

        data = action_result.add_data({})
        self.save_progress(
            'Checking for prior detonations for' +
            vault_id +
            ' sha256 ' +
            sha256)
        # check if there is existing report already
        ticloud, ticore, summary_data = self._check_detonated_report(vault_id, action_result)

        # report does not exist yet
        if ticloud["ticloud"] == "Report Not Found"  or ticore["ticore"] == "Report Not Found":

            # Was not detonated before
            self.save_progress('Uploading the file')

            # upload the file to the upload service
            ret_val, response = self._make_rest_call(
                '/api/uploads/', action_result, self.FILE_UPLOAD_ERROR_DESC,
                method='post', filein=files['file'][1])
            startTime = time.time()

            if (phantom.is_fail(ret_val)):
                return self.get_status()

            # get the sha1
            task_id = response.get('sha1')
            if task_id is None:
                task_id = response.get('detail').get('sha1')

            # Now poll for the result
            finished = self._poll_task_status(task_id, action_result)


            if not finished:
                ticloud, ticore, summary_data = self._check_detonated_report(task_id, action_result)

                if ticloud is not None:
                    data["ticloud"] = ticloud
                if ticore is not None:
                    data["ticore"] = ticore

                data.update(data)

            analyze_time = round(time.time() - startTime, 3)
            try:
                summary = {'a1000_report_url': "{0}{1}".format(
                        self._base_url, "/" + sha256),
                        "sha1" : task_id,
                        "analyze duration" : analyze_time}
                summary.update(summary_data)
            except BaseException:
                summary = {}


            # Add the report
            try:
                polling_attempt = 0
                max_polling_attempts = 10
                ticloud, ticore, summary_data = self._check_detonated_report(sha256, action_result)
                while (polling_attempt < max_polling_attempts and summary_data["threat_status"] == "unknown"):
                    ticloud, ticore, summary_data = self._check_detonated_report(task_id, action_result)
                    polling_attempt += 1
                    time.sleep(1)

                data = {"ticore": ticore, "ticloud": ticloud}
                data.update(data)
            except BaseException:
                return action_result.set_status(phantom.APP_ERROR, "failed to update data")
                #error


            action_result.update_summary(summary)

            if (phantom.is_fail(ret_val)):
                return action_result.get_status()

        # Add the report
        polling_attempt = 0
        max_polling_attempts = 10
        try:
            # Now poll for the result
            try:
                ticloud, ticore, summary_data = self._check_detonated_report(sha256, action_result)
            except:
                action_result.add_data({"test0": "fail"})

            #ret_val, response = self._poll_task_status(task_id, action_result)

            try:
                action_result.add_data(ticloud)
            except:
                action_result.add_data({"ticloud": "result not found"})
            try:
                action_result.add_data(ticore)
            except:
                action_result.add_data({"ticore": "result not found"})
        except BaseException:
                return action_result.set_status(phantom.APP_ERROR, "failed to update data stage 2")
                #error

        try:
            summary = {'a1000_report_url': "{0}{1}".format(
                    self._base_url, "/" + sha256)}
            summary.update(summary_data)
        except BaseException:
            summary = {}

        action_result.update_summary(summary)
        return action_result.set_status(phantom.APP_SUCCESS)

    def handle_action(self, param):

        ret_val = phantom.APP_SUCCESS
        # Get the action that we are supposed to execute for this connector run
        action_id = self.get_action_identifier()

        self.debug_print("action_id", self.get_action_identifier())

        if (action_id == self.ACTION_ID_DETONATE_FILE):
            ret_val = self._detonate_file(param)
        elif (action_id == self.ACTION_ID_GET_REPORT):
            ret_val = self._get_report(param)
        elif (action_id == self.ACTION_ID_REANALYZE_FILE):
            ret_val = self._reanalyze_file(param)
        elif (action_id == self.ACTION_ID_TEST_ASSET_CONNECTIVITY):
            ret_val = self._test_connectivity(param)
        return ret_val


if __name__ == '__main__':

    import sys

    if (len(sys.argv) < 2):
        print "No test json specified as input"
        exit(0)

    with open(sys.argv[1]) as f:
        in_json = f.read()
        in_json = json.loads(in_json)
        print(json.dumps(in_json, indent=4))

        connector = A1000Connector()
        connector.print_progress_message = True
        injson = json.dumps(in_json)
        ret_val = connector._handle_action(injson, None)
        print json.dumps(json.loads(ret_val), indent=4)

    exit(0)
