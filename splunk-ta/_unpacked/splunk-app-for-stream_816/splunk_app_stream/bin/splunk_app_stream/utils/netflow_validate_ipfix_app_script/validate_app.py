import fnmatch
import json
import logging
import os
import re
import tempfile

from jsonschema import Draft3Validator
from lxml import etree

try:
    import xml.etree.cElementTree as ET
except:
    import defusedxml.ElementTree as ET

APP_PATH = "/opt/splunk/etc/apps/splunk_app_stream_ipfix_ckp"

mapping_file_name = "ipfixmap.conf"


def check_app_regex():
    if os.path.exists(APP_PATH):
        app_name = APP_PATH.split("/")[-1]
        regex_result_ipfix = re.match("^splunk_app_stream_ipfix_", app_name)
        return regex_result_ipfix
    else:
        return False


class Vocabulary:
    def __init__(self):
        self.DEFAULT_PATH = APP_PATH + "/default/"
        self.LOCAL_PATH = APP_PATH + "/local/"

    def fetch_terms(self, filePath):
        try:
            all_terms = []
            xml_data = open(filePath, "rb").read()

            root = ET.fromstring(xml_data)
            for terms in root.find("{http://purl.org/cloudmeter/config}Vocabulary"):
                for term in terms.iter("{http://purl.org/cloudmeter/config}Term"):
                    all_terms.append(term.attrib.get("id"))

            return all_terms
        except Exception as e:
            print(f"Error : {e}")

    def validate_xml(self, path):
        try:
            xml_data = open(path, "rb").read()
            result = self.validateXML(xml_data)

            if result["is_valid"] == False:
                isValidVocabulary = False
                for e in result["error"]:
                    print(f"Error : {e}  File Path : {path}")
                return False
            else:
                return True
        except Exception as e:
            print(f"Error : {e}")
            return False

    def vocabulary_apply_layering(
        self,
    ):
        isVocabValid = True
        default_files = set()
        local_files = set()
        full_app_name = APP_PATH.split("/")[-1]
        app_short_name = full_app_name.split("splunk_app_stream_ipfix_")[-1]
        final_vocabs = []

        if os.path.exists(self.DEFAULT_PATH):
            for file in os.listdir(self.DEFAULT_PATH):
                if file.endswith(".xml"):
                    default_files.add(file)

        if os.path.exists(self.LOCAL_PATH):
            for file in os.listdir(self.LOCAL_PATH):
                if file.endswith(".xml"):
                    local_files.add(file)

        matched_file_names = list(default_files & local_files)
        if len(matched_file_names):
            for fileName in matched_file_names:

                isDefaultValid = self.validate_xml(os.path.join(self.DEFAULT_PATH, fileName))
                isLocalValid = self.validate_xml(os.path.join(self.LOCAL_PATH, fileName))

                if isDefaultValid == False or isLocalValid == False:
                    return list(default_files), list(local_files), final_vocabs, False

                default_terms = self.fetch_terms(os.path.join(self.DEFAULT_PATH, fileName))
                # if not default_terms:
                #     isVocabValid = False
                #     break

                local_terms = self.fetch_terms(os.path.join(self.LOCAL_PATH, fileName))
                # if not local_terms:
                #     isVocabValid = False
                #     break

                matched_terms = list(set(default_terms) & set(local_terms))

                ET.register_namespace("", "http://purl.org/cloudmeter/config")
                combinedVocab = ET.Element("Vocabulary")

                tree = ET.parse(os.path.join(self.DEFAULT_PATH, fileName))
                vocab = tree.find("{http://purl.org/cloudmeter/config}Vocabulary")
                for term in vocab.findall("{http://purl.org/cloudmeter/config}Term"):
                    element_id = term.attrib.get("id")
                    if element_id not in matched_terms:
                        combinedVocab.append(term)

                local_tree = ET.parse(os.path.join(self.LOCAL_PATH, fileName))
                local_vocab = local_tree.find("{http://purl.org/cloudmeter/config}Vocabulary")
                for term in local_vocab.findall("{http://purl.org/cloudmeter/config}Term"):
                    combinedVocab.append(term)

                xmlOut = ET.ElementTree(ET.Element("CmConfig"))
                xml_schema_data = open(os.path.join(self.DEFAULT_PATH, fileName), "rb").read()
                root = ET.fromstring(xml_schema_data)
                version = root.attrib.get("version")
                xmlOut.getroot().set("version", version)

                xmlOut.getroot().append(combinedVocab)

                temp = tempfile.NamedTemporaryFile(suffix=fileName, prefix="vocabs_")
                xmlOut.write(temp)
                temp.seek(0)
                content = temp.read().decode("utf-8")
                vocab_content = {
                    "fileName": str(app_short_name) + "_" + str(fileName.split(".")[0]),
                    "content": content,
                }
                final_vocabs.append(vocab_content)

        return list(default_files), list(local_files), final_vocabs, True

    def validateXML(self, xml_data):
        errors = []
        invalid_vocab = {}
        error_flag = False
        try:
            xml_schema_data = open("./vocabulary_schema", "rb").read()
            schema_root = etree.XML(xml_schema_data)
            schema = etree.XMLSchema(schema_root)
            xmlparser = etree.XMLParser(schema=schema)

            root = ET.fromstring(xml_data, xmlparser)

            list_of_elems = []
            list_of_types = set()
            allowed_types = [
                "string",
                "blob",
                "object",
                "datetime",
                "uint16",
                "uint32",
                "uint8",
                "shortstring",
                "double",
                "uint64",
                "int64",
            ]

            for terms in root.find("{http://purl.org/cloudmeter/config}Vocabulary"):
                for term in terms.iter("{http://purl.org/cloudmeter/config}Term"):
                    for eachType in term.iter("{http://purl.org/cloudmeter/config}Type"):
                        list_of_types.add(eachType.text)

                    if term.attrib.get("id"):
                        list_of_elems.append(terms.attrib.get("id"))

            if None in list_of_types:
                error_flag = True
                errors.append("Type is not valid")

            for eachType in list_of_types:
                if eachType not in allowed_types:
                    error_flag = True
                    errors.append(str(eachType) + " Type is not valid")

            if len(list_of_elems) != len(set(list_of_elems)):
                error_flag = True
                errors.append("Found duplicate element id")

            if error_flag:
                return {"is_valid": False, "error": errors}
            else:
                return {"is_valid": True, "error": "None"}

        except etree.XMLSyntaxError as e:
            errors.append("XML Syntax Error: " + str(e))
            return {"is_valid": False, "error": errors}
        except Exception as e:
            errors.append(str(e))
            return {"is_valid": False, "error": errors}

    def get_Vocabs(
        self,
    ):
        isValidVocabulary = True
        (
            default_files,
            local_files,
            final_vocabs,
            isValidVocabulary,
        ) = self.vocabulary_apply_layering()
        default_vocabs = list(set(default_files) - set(local_files))
        local_vocabs = list(set(local_files) - set(default_files))

        default_tempArr = []
        if len(default_vocabs):
            for fileName in default_vocabs:
                default_tempArr.append(os.path.join(self.DEFAULT_PATH, str(fileName)))

        local_tempArr = []
        if len(local_vocabs):
            for fileName in local_vocabs:
                local_tempArr.append(os.path.join(self.LOCAL_PATH, str(fileName)))

        default_local_tempArr = default_tempArr + local_tempArr

        for i in range(len(default_local_tempArr)):
            isValidVocab = self.validate_xml(default_local_tempArr[i])
            if isValidVocab == False:
                isValidVocabulary = False

        if isValidVocabulary and len(final_vocabs):
            for vocab in final_vocabs:
                xml_data = vocab["content"]
                try:
                    result = self.validateXML(xml_data)

                    if result["is_valid"] == False:
                        isValidVocabulary = False
                        for e in result["error"]:
                            print(f"Error : {e}")

                except Exception as e:
                    print("Error : {}".format(e))

        return isValidVocabulary


class Configurations:
    def __init__(self):
        self.DEFAULT_PATH = APP_PATH + "/default/"
        self.LOCAL_PATH = APP_PATH + "/local/"

    def clean_data(self, body):
        initial_data = re.split("\n", body)

        data_clean = [ele for ele in initial_data if ele.strip()]
        temp = []

        for i in range(len(data_clean)):
            data_clean[i] = data_clean[i].strip()

        for i in data_clean:
            if i[0] == "#":
                temp.append(i)

        for i in temp:
            data_clean.remove(i)

        return data_clean

    def fetch_terms(self):
        try:
            all_terms = []
            ET.register_namespace("", "http://purl.org/cloudmeter/config")
            combinedVocab = ET.Element("Vocabulary")

            if os.path.exists(self.DEFAULT_PATH):

                for fileName in os.listdir(self.DEFAULT_PATH):
                    if fileName.endswith(".xml"):
                        tree = ET.parse(self.DEFAULT_PATH + os.sep + fileName)
                        vocab = tree.find("{http://purl.org/cloudmeter/config}Vocabulary")
                        for term in vocab.findall("{http://purl.org/cloudmeter/config}Term"):
                            combinedVocab.append(term)

            if os.path.exists(self.LOCAL_PATH):

                for fileName in os.listdir(self.LOCAL_PATH):
                    if fileName.endswith(".xml"):
                        tree = ET.parse(self.LOCAL_PATH + os.sep + fileName)
                        vocab = tree.find("{http://purl.org/cloudmeter/config}Vocabulary")
                        for term in vocab.findall("{http://purl.org/cloudmeter/config}Term"):
                            combinedVocab.append(term)

            xmlOut = ET.ElementTree(ET.Element("CmConfig"))
            xmlOut.getroot().append(combinedVocab)

            temp = tempfile.NamedTemporaryFile(suffix="new", prefix="vocabs_")
            xmlOut.write(temp)
            temp.seek(0)
            content = temp.read().decode("utf-8")
            root = ET.fromstring(content)

            if root.find("{http://purl.org/cloudmeter/config}Vocabulary") != None:
                for terms in root.find("{http://purl.org/cloudmeter/config}Vocabulary"):
                    for term in terms.iter("{http://purl.org/cloudmeter/config}Term"):
                        all_terms.append(term.attrib.get("id"))

            return all_terms
        except Exception as e:
            print(f"Error : {e}")

    def configuration_apply_layering(self):
        default_files = set()
        local_files = set()
        isValidConfiguration = True
        final_configs = []

        if os.path.exists(self.DEFAULT_PATH):
            for fileName in os.listdir(self.DEFAULT_PATH):
                if fnmatch.fnmatch(fileName, mapping_file_name):
                    default_files.add(fileName)

        if os.path.exists(self.LOCAL_PATH):
            for fileName in os.listdir(self.LOCAL_PATH):
                if fnmatch.fnmatch(fileName, mapping_file_name):
                    local_files.add(fileName)

        matched_file_names = list(default_files & local_files)
        Unmatch_default_files = list(default_files - local_files)
        Unmatch_local_files = list(local_files - default_files)

        if len(Unmatch_default_files):

            for fileName in Unmatch_default_files:

                default_mapping = self.fetch_mappings(os.path.join(self.DEFAULT_PATH, fileName))
                default_mapping = self.validate(default_mapping)

                if default_mapping["is_valid"] == False:
                    isValidConfiguration = False
                    for e in default_mapping["error"]:
                        print(f"Error : {e} file Path : {self.DEFAULT_PATH}{fileName}")

        if len(Unmatch_local_files):
            for fileName in Unmatch_local_files:
                local_mapping = self.fetch_mappings(os.path.join(self.LOCAL_PATH, fileName))
                local_mapping = self.validate(local_mapping)

                if local_mapping["is_valid"] == False:
                    isValidConfiguration = False
                    for e in local_mapping["error"]:
                        print(f"Error : {e}  file Path : {self.LOCAL_PATH}{fileName}")
                    break

        if len(matched_file_names):
            for fileName in matched_file_names:
                default_mapping = self.fetch_mappings(os.path.join(self.DEFAULT_PATH, fileName))
                local_mapping = self.fetch_mappings(os.path.join(self.LOCAL_PATH, fileName))

                temp_mappings = {}

                if default_mapping["is_valid"] == False:
                    isValidConfiguration = False
                    for e in default_mapping["error"]:
                        print(f"Error : {e} file Path : {self.DEFAULT_PATH}{fileName}")
                default_mappings = default_mapping["data"]

                if local_mapping["is_valid"] == False:
                    isValidConfiguration = False
                    for e in local_mapping["error"]:
                        print(f"Error1 : {e}  file Path : {self.LOCAL_PATH}{fileName}")

                local_mappings = local_mapping["data"]

                count = len(local_mappings)

                for x in default_mappings.keys():

                    for y in local_mappings.keys():

                        if default_mappings[x] == local_mappings[y]:
                            default_mappings[x] = [
                                default_mappings[x][0],
                                default_mappings[x][1],
                                default_mappings[x][2],
                                default_mappings[x][3],
                                True,
                            ]
                            break

                for x in default_mappings.keys():

                    if default_mappings[x][4] == False:
                        count = count + 1
                        temp_mappings.update(
                            {
                                count: [
                                    default_mappings[x][0],
                                    default_mappings[x][1],
                                    default_mappings[x][2],
                                    default_mappings[x][3],
                                    False,
                                ]
                            }
                        )

                local_mappings.update(temp_mappings)
                term_count = 0
                content = ""
                for x in local_mappings.values():
                    if x[0] != False:
                        content = content + f"netflowElement.{term_count}.enterpriseid = {x[0]}\n"
                    if x[1] != False:
                        content = content + f"netflowElement.{term_count}.id = {x[1]}\n"
                    if x[2] != False:
                        content = content + f"netflowElement.{term_count}.termid = {x[2]}\n"
                    if x[3] != False:
                        content = content + f"netflowElement.{term_count}.termtype = {x[3]}\n"
                    term_count = term_count + 1
                final_mappings = {}
                existing_numbers = []
                mapping_count = 0
                content_mappings_arr = self.clean_data(content)
                all_terms = self.fetch_terms()

                result = self.create_dict(
                    final_mappings,
                    content_mappings_arr,
                    existing_numbers,
                    mapping_count,
                    all_terms,
                )

                final_result = self.validate(result)
                if final_result["is_valid"] == False:
                    isValidConfiguration = False
                    for e in final_result["error"]:
                        print(f"Error : {e}  fileName: {fileName}")
                    break
                temp = fileName.split(".")
                full_app_name = APP_PATH.split("/")[-1]
                app_short_name = full_app_name.split("splunk_app_stream_ipfix_")[-1]
                config = {
                    "fileName": app_short_name + "_" + temp[0],
                    "content": content,
                }
                final_configs.append(config)

        return list(default_files), list(local_files), isValidConfiguration, final_configs

    def create_dict(
        self, final_mappings, content_mappings_arr, existing_numbers, mapping_count, all_terms
    ):
        # Regex for validation of different types of terms
        enterpriseid_regex = "(^(netflowElement.)\d+(.enterpriseid)\s*(=)\s*\d+$)"
        id_regex = "(^(netflowElement.)\d+(.id)\s*(=)\s*\d+$)"
        termid_regex = "(^(netflowElement.)\d+(.termid)\s*(=)\s*[a-zA-Z]+.[a-zA-Z]+)"
        termtype_regex = "(^(netflowElement.)\d+(.termtype)\s*(=)\s*(ipaddress\s*|macaddress\s*))$"
        error_flag = False
        errors = []
        unique_error = []
        for i in range(len(content_mappings_arr)):

            outer_number = content_mappings_arr[i].split(".")
            regex_result_1 = re.search(enterpriseid_regex, content_mappings_arr[i])
            regex_result_2 = re.search(id_regex, content_mappings_arr[i])
            regex_result_3 = re.search(termid_regex, content_mappings_arr[i])
            regex_result_4 = re.search(termtype_regex, content_mappings_arr[i])
            count = 0
            unique_error_flag = False
            result = {"is_valid": None, "error": None}
            inner_regex_1 = 0
            inner_regex_2 = 0
            inner_regex_3 = 0
            inner_regex_4 = 0

            if regex_result_1 or regex_result_2 or regex_result_3 or regex_result_4:

                if outer_number[1] not in existing_numbers:

                    for j in range(len(content_mappings_arr)):
                        inner_number = content_mappings_arr[j].split(".")

                        if outer_number[1] == inner_number[1]:

                            if re.search(enterpriseid_regex, content_mappings_arr[j]):
                                inner_regex_1 = content_mappings_arr[j].split("=")

                            if re.search(id_regex, content_mappings_arr[j]):
                                inner_regex_2 = content_mappings_arr[j].split("=")

                            if re.search(termid_regex, content_mappings_arr[j]):
                                vocab_single_term = content_mappings_arr[j].split("=")

                                if vocab_single_term[1].strip() in all_terms:
                                    inner_regex_3 = content_mappings_arr[j].split("=")
                                else:
                                    error_flag = True
                                    result["is_valid"] = False
                                    if inner_number[1] not in unique_error:
                                        unique_error.append(inner_number[1])
                                        unique_error_flag = True
                                        errors.append(
                                            f"Validation Error: Vocab for {vocab_single_term[1]} term id not found"
                                        )

                            if re.search(termtype_regex, content_mappings_arr[j]):
                                inner_regex_4 = content_mappings_arr[j].split("=")

                            count = count + 1

                            if count > 4:
                                error_flag = True
                                result["is_valid"] = False
                                error_msg = (
                                    "Validation Error: Have more than 4 terms for same inner-id"
                                )
                                if error_msg not in errors:
                                    errors.append(error_msg)

            else:
                error_flag = True
                result["is_valid"] = False
                error_msg = "Validation Error: bad data request the format is not appropriate"
                if error_msg not in errors:
                    errors.append(error_msg)

            if (
                (count == 2 and inner_regex_2 and inner_regex_3)
                or (count == 3 and inner_regex_1 and inner_regex_2 and inner_regex_3)
                or (
                    count == 4
                    and inner_regex_1
                    and inner_regex_2
                    and inner_regex_3
                    and inner_regex_4
                )
            ):
                existing_numbers.append(outer_number[1])
                if count == 2:
                    final_mappings.update(
                        {
                            mapping_count: [
                                False,
                                inner_regex_2[1].strip(),
                                inner_regex_3[1].strip(),
                                False,
                                False,
                            ]
                        }
                    )
                    mapping_count = mapping_count + 1

                elif count == 3:
                    final_mappings.update(
                        {
                            mapping_count: [
                                inner_regex_1[1].strip(),
                                inner_regex_2[1].strip(),
                                inner_regex_3[1].strip(),
                                False,
                                False,
                            ]
                        }
                    )
                    mapping_count = mapping_count + 1

                elif count == 4:
                    final_mappings.update(
                        {
                            mapping_count: [
                                inner_regex_1[1].strip(),
                                inner_regex_2[1].strip(),
                                inner_regex_3[1].strip(),
                                inner_regex_4[1].strip(),
                                False,
                            ]
                        }
                    )
                    mapping_count = mapping_count + 1

                continue

            elif outer_number[1] not in existing_numbers:
                error_flag = True
                result["is_valid"] = False
                if unique_error_flag:
                    errors.append(
                        "Validation Error: bad data request the terms don't match the required format"
                    )

        if not error_flag:
            result["is_valid"] = True
            result["data"] = final_mappings
            result["mapping_count"] = mapping_count
        else:
            result["is_valid"] = False
            result["error"] = errors
            result["data"] = final_mappings
            result["mapping_count"] = mapping_count
        return result

    def fetch_mappings(self, filePath):
        try:
            final_mappings = {}
            existing_numbers = []
            mapping_count = 0

            content_mappings = open(filePath, "r").read()
            content_mappings_arr = self.clean_data(content_mappings)
            all_terms = self.fetch_terms()

            result = self.create_dict(
                final_mappings,
                content_mappings_arr,
                existing_numbers,
                mapping_count,
                all_terms,
            )
            return result
        except Exception as e:
            print(f"Error : {e}")
            return {"is_valid": False, "error": "Validation Error " + str(e)}

    def validate(self, result):
        errors = result["error"]
        if errors is None:
            errors = []
        error_flag = not result["is_valid"]
        for x in result["data"].values():
            for y in result["data"].values():

                if x[2] == y[2] and x[0] == y[0] and x[0] != False and y[0] != False:
                    if x[1] != y[1]:
                        error_flag = True
                        error_msg = "Validation Error: bad data request, two terms in same enterprise id, have same term.id and different id"
                        if error_msg not in errors:
                            errors.append(error_msg)
                    else:
                        continue

                elif x[1] == y[1] and x[0] == y[0] and x[0] != False and y[0] != False:

                    if x[2] != y[2]:
                        error_flag = True
                        error_msg = "Validation Error: bad data request, two terms in same enterprise id, have same id and different term.id"
                        if error_msg not in errors:
                            errors.append(error_msg)
                    else:
                        continue
        if not error_flag:
            return {"is_valid": True, "error": "None"}
        else:
            return {"is_valid": False, "error": errors}

    def get_configurations(self, isVocabValid):
        isValidConfiguration = True
        if isVocabValid:
            (
                default_files,
                local_files,
                isValidConfiguration,
                final_configs,
            ) = self.configuration_apply_layering()

        return isValidConfiguration


class Streams:
    def __init__(self):
        self.DEFAULT_PATH = APP_PATH + "/default/"
        self.LOCAL_PATH = APP_PATH + "/local/"

    def validate_aggregation_config(self, stream_json):
        fields = stream_json["fields"]
        valid_agg_types = {
            "dc",
            "max",
            "mean",
            "median",
            "min",
            "mode",
            "stdev",
            "stdevp",
            "sum",
            "sumsq",
            "values",
            "var",
            "varp",
        }
        valid = True
        error_msg = ""
        for field in fields:
            agg_type = field["aggType"]
            if not (agg_type in ("key", "value") or set(agg_type).issubset(valid_agg_types)):
                valid = False
                error_msg = (
                    "Invalid aggregation type for field for stream with id %s" % stream_json["id"]
                )
                return (valid, error_msg)
            if len(agg_type) == 0:
                valid = False
                error_msg = (
                    "No aggregation type set for field for stream with id %s" % stream_json["id"]
                )
                return (valid, error_msg)
        return (valid, error_msg)

    # validate aggregate streams for topX configuration
    # topLimit and topSortBy are optional fields
    # for topX feature both the fields need to be present for topX configuration
    # topSortBy field has to be of a supported numeric agg_type or "count" field
    # logging IDs here is fine since this function is called after stream_json['id'] is validated
    def validate_topx_config(self, stream_json):
        is_aggregated = False
        if "aggregated" in stream_json:
            is_aggregated = stream_json["aggregated"]
        extras = stream_json["extras"]
        valid = True
        error_msg = ""
        if is_aggregated:
            if "topLimit" not in extras and "topSortBy" not in extras:
                return (valid, error_msg)
            elif "topLimit" not in extras:
                valid = False
                error_msg = "Missing topLimit for stream with id " + stream_json["id"]
            elif "topSortBy" not in extras:
                valid = False
                error_msg = "Missing topSortBy for stream with id " + stream_json["id"]
            else:
                if extras["topLimit"] <= 0:
                    valid = False
                    error_msg = (
                        "topLimit value should be greater than 0 for stream with id "
                        + stream_json["id"]
                    )
                    return (valid, error_msg)
                topSortBy = extras["topSortBy"]
                if topSortBy != "count":
                    split_index = topSortBy.index("(")
                    agg_type = topSortBy[:split_index]
                    topSortBy = topSortBy[split_index + 1 : -1]
                    fields = stream_json["fields"]
                    valid = False
                    error_msg = (
                        "topSortBy should be either a 'count' field or a numeric aggregation type field for stream with id "
                        + stream_json["id"]
                    )
                    for field in fields:
                        if field["name"] == topSortBy:
                            numeric_agg_types = [
                                "dc",
                                "max",
                                "mean",
                                "median",
                                "min",
                                "mode",
                                "stdev",
                                "stdevp",
                                "sum",
                                "sumsq",
                                "var",
                                "varp",
                            ]
                            # logger.debug("agg_type is %s for topSortBy field %s for stream %s", agg_type, topSortBy, stream_json['id'])
                            # Since we don't know what topSortBy might be, let's not log it, just in case
                            print(
                                f"checking agg_type for a topSortBy field for stream {stream_json['id']}",
                            )
                            if (
                                agg_type in numeric_agg_types
                                and agg_type in field["aggType"]
                                and field["enabled"]
                            ):
                                valid = True
                                error_msg = ""
                            else:
                                if (
                                    agg_type not in numeric_agg_types
                                    or agg_type not in field["aggType"]
                                ):
                                    error_msg = (
                                        "topSortBy should be an enabled numeric aggregation type field for stream with id "
                                        + stream_json["id"]
                                    )
                                else:
                                    error_msg = (
                                        "topSortBy should be enabled for stream with id "
                                        + stream_json["id"]
                                    )
                else:
                    # topSortBy is count; can log it
                    print("topSortBy field %s for stream %s", topSortBy, stream_json["id"])
        else:
            if "topSortBy" in extras or "topLimit" in extras:
                valid = False
                error_msg = (
                    "top configuration cannot be configured for non aggregated stream with id "
                    + stream_json["id"]
                )

        return (valid, error_msg)

    def date_field_check(self, stream_json):
        if "createDate" in stream_json and "expirationDate" in stream_json:
            return stream_json["expirationDate"] > stream_json["createDate"]
        else:
            return True

    def is_valid_stream_definition(self, stream_json, all_terms):

        schema_data = open("./stream_schema", "rb").read()
        stream_schema = dict(json.loads(schema_data.decode("utf-8")))
        validator = Draft3Validator(stream_schema)
        error_messages = []
        valid_stream_id_regex = "^\w+$"
        vocab_terms = list()
        error_flag = False

        if not re.compile(valid_stream_id_regex).match(stream_json["id"]):
            error_msg = (
                "Invalid Stream definition for stream with id %s --  only letters, digits and underscores ('_') allowed for Id"
                % (stream_json["id"])
            )
            error_messages.append(error_msg)
            error_flag = True

        if not validator.is_valid(stream_json):
            for error in sorted(validator.iter_errors(stream_json), key=str):
                error_msg = (
                    "Invalid Stream definition for stream with id %s -- Validation Error %s"
                    % (stream_json["id"], error.message)
                )
                error_messages.append(error_msg)
                error_flag = True
        else:

            (valid_agg_config, error_msg) = self.validate_aggregation_config(stream_json)
            if not valid_agg_config:
                error_flag = True
                error_messages.append(error_msg)

            (valid_topx_config, error_msg) = self.validate_topx_config(stream_json)
            if not valid_topx_config:
                print(f"Error : {error_msg}")
                error_flag = True
                error_messages.append(error_msg)
                return False, error_messages

            fields = stream_json["fields"]
            invalid_terms = []
            invalid_regexes = []
            field_names = []

            if all_terms:
                vocab_terms = all_terms

            for field in fields:
                field_names.append(field["name"])
                if not field["term"] in vocab_terms:
                    invalid_terms.append(field["term"])

                if "transformation" in field and field["transformation"]["type"] == "regex":
                    # check for validity of regex
                    regex = field["transformation"]["value"]
                    try:
                        re.compile(regex)
                    except Exception:
                        print("Exception : transformation regex is invalid")
                        invalid_regexes.append(field)

            duplicate_field_names = set([x for x in field_names if field_names.count(x) > 1])
            invalid_dates = not self.date_field_check(stream_json)

            if invalid_terms or invalid_regexes or duplicate_field_names or invalid_dates:
                # Don't log anything that hasn't already been validated
                if invalid_terms:
                    error_flag = True
                    error_msg = (
                        "Invalid Stream definition for stream with id %s -- "
                        "Terms do not have matching vocabulary entries" % stream_json["id"]
                    )
                    # print(invalid_terms)
                    error_messages.append(error_msg)

                if invalid_regexes:
                    error_flag = True
                    error_msg = (
                        "Invalid Stream definition for stream with id %s -- "
                        "Extraction rules with invalid regexes were found" % stream_json["id"]
                    )
                    error_messages.append(error_msg)

                if duplicate_field_names:
                    error_flag = True
                    error_msg = (
                        "Invalid Stream definition for stream with id %s -- "
                        "Field names are duplicated" % stream_json["id"]
                    )
                    error_messages.append(error_msg)

                if invalid_dates:
                    error_flag = True
                    error_msg = (
                        "Invalid Stream definition for stream with id %s -- "
                        "Expiration Date cannot be earlier than the Create Date"
                        % stream_json["id"]
                    )
                    error_messages.append(error_msg)

                for msg in error_messages:
                    print(f"Error : {msg}")

        if not error_flag:
            return True, None
        else:
            return False, error_messages

    def get_all_vocab_terms(self, app_full_path):
        default_path = os.path.join(app_full_path, "default")
        local_path = os.path.join(app_full_path, "local")
        try:
            fileName = ""
            ET.register_namespace("", "http://purl.org/cloudmeter/config")
            combinedVocab = ET.Element("Vocabulary")

            for file in os.listdir(default_path):
                if file.endswith(".xml"):
                    fileName = file
                    tree = ET.parse(os.path.join(default_path, file))
                    vocab = tree.find("{http://purl.org/cloudmeter/config}Vocabulary")
                    for term in vocab.findall("{http://purl.org/cloudmeter/config}Term"):
                        combinedVocab.append(term)

            for file in os.listdir(local_path):
                if file.endswith(".xml"):
                    fileName = file
                    tree = ET.parse(os.path.join(local_path, file))
                    vocab = tree.find("{http://purl.org/cloudmeter/config}Vocabulary")
                    for term in vocab.findall("{http://purl.org/cloudmeter/config}Term"):
                        combinedVocab.append(term)

            xmlOut = ET.ElementTree(ET.Element("CmConfig"))
            xmlOut.getroot().append(combinedVocab)

            try:
                temp = tempfile.TemporaryFile()

                try:
                    xmlOut.write(temp, xml_declaration=True, encoding="UTF-8")
                    temp.seek(0)
                    content = temp.read().decode("utf-8")
                finally:
                    temp.close()
                    return content

            except Exception:
                print("Exception : IOerror, unable to create temp file")

        except Exception as e:
            print(f"Error : {e}  fileName : {default_path}{fileName}")

    def validateStreamFile(self, file_path, app_full_path):
        try:
            content = open(file_path, "rb").read()
            stream_json = json.loads(content)
            all_terms = self.get_all_vocab_terms(app_full_path)
            is_valid_stream, stream_validation_messages = self.is_valid_stream_definition(
                stream_json, all_terms
            )
            return is_valid_stream, stream_validation_messages
        except Exception as e:
            error_message = str(e) + "\t" + file_path
            return (False, error_message)

    def fetch_terms(self):
        try:
            all_terms = []
            ET.register_namespace("", "http://purl.org/cloudmeter/config")
            combinedVocab = ET.Element("Vocabulary")

            if os.path.exists(self.DEFAULT_PATH):

                for fileName in os.listdir(self.DEFAULT_PATH):
                    if fileName.endswith(".xml"):
                        tree = ET.parse(self.DEFAULT_PATH + os.sep + fileName)
                        vocab = tree.find("{http://purl.org/cloudmeter/config}Vocabulary")
                        for term in vocab.findall("{http://purl.org/cloudmeter/config}Term"):
                            combinedVocab.append(term)

            if os.path.exists(self.LOCAL_PATH):

                for fileName in os.listdir(self.LOCAL_PATH):
                    if fileName.endswith(".xml"):
                        tree = ET.parse(self.LOCAL_PATH + os.sep + fileName)
                        vocab = tree.find("{http://purl.org/cloudmeter/config}Vocabulary")
                        for term in vocab.findall("{http://purl.org/cloudmeter/config}Term"):
                            combinedVocab.append(term)

            xmlOut = ET.ElementTree(ET.Element("CmConfig"))
            xmlOut.getroot().append(combinedVocab)

            temp = tempfile.NamedTemporaryFile(suffix="new", prefix="vocabs_")
            xmlOut.write(temp)
            temp.seek(0)
            content = temp.read().decode("utf-8")
            root = ET.fromstring(content)

            if root.find("{http://purl.org/cloudmeter/config}Vocabulary") != None:
                for terms in root.find("{http://purl.org/cloudmeter/config}Vocabulary"):
                    for term in terms.iter("{http://purl.org/cloudmeter/config}Term"):
                        all_terms.append(term.attrib.get("id"))

            return all_terms
        except Exception as e:
            print(f"Error : {e}")

    def fetch_fields(self, filePath):
        try:
            if not filePath:
                return "Please provide absolute file path"

            all_fields = []
            with open(filePath) as fp:
                data = json.load(fp)
                if len(data):
                    for index in range(len(data["fields"])):
                        all_fields.append(data["fields"][index]["term"])
            return all_fields

        except (OSError, ValueError):
            print("Exception occured while fetching fields from streams")
            print(OSError)

    def streams_apply_layering(self):
        default_files = set()
        local_files = set()
        final_streams = []
        isStreamValid = True
        stream_validation_messages = None
        if os.path.exists(self.DEFAULT_PATH):
            for fileName in os.listdir(self.DEFAULT_PATH):
                if fileName.endswith(".json"):
                    default_files.add(fileName)

                    file_path = os.path.join(self.DEFAULT_PATH, fileName)
                    is_valid_stream, stream_validation_messages = self.validateStreamFile(
                        file_path, APP_PATH
                    )
                    if not is_valid_stream:
                        isStreamValid = False
                        break

        if os.path.exists(self.LOCAL_PATH) and isStreamValid:
            for fileName in os.listdir(self.LOCAL_PATH):
                if fileName.endswith(".json"):
                    local_files.add(fileName)

                    file_path = os.path.join(self.LOCAL_PATH, fileName)
                    is_valid_stream, stream_validation_messages = self.validateStreamFile(
                        file_path, APP_PATH
                    )
                    if not is_valid_stream:
                        isStreamValid = False
                        break

        if isStreamValid == False:
            return (
                list(default_files),
                list(local_files),
                final_streams,
                isStreamValid,
                stream_validation_messages,
            )

        matched_file_names = list(default_files & local_files)
        Unmatch_default_files = list(default_files - local_files)
        Unmatch_local_files = list(local_files - default_files)

        if len(Unmatch_default_files):
            for fileName in Unmatch_default_files:
                default_fields = self.fetch_fields(os.path.join(self.DEFAULT_PATH, fileName))
                all_terms = self.fetch_terms()

                foundUnmatchedTermsInDefault = set(default_fields) - set(all_terms)
                if len(foundUnmatchedTermsInDefault):
                    stream_validation_messages = "Some of the term that is present in the stream file, which is not matching with vocabulary terms\nFile location: {}".format(
                        os.path.join(self.DEFAULT_PATH, fileName)
                    )
                    isStreamValid = False
                    break
        if len(Unmatch_local_files):
            for fileName in Unmatch_local_files:
                local_fields = self.fetch_fields(os.path.join(self.LOCAL_PATH, fileName))
                all_terms = self.fetch_terms()

                foundUnmatchedTermsInLocal = set(local_fields) - set(all_terms)
                if len(foundUnmatchedTermsInLocal):
                    stream_validation_messages = "Some of the term that is present in the stream file, which is not matching with vocabulary terms\nFile location: {}".format(
                        os.path.join(self.LOCAL_PATH, fileName)
                    )
                    isStreamValid = False
                    break

        if len(matched_file_names) and isStreamValid == True:
            for fileName in matched_file_names:
                default_fields = self.fetch_fields(os.path.join(self.DEFAULT_PATH, fileName))
                local_fields = self.fetch_fields(os.path.join(self.LOCAL_PATH, fileName))

                all_terms = self.fetch_terms()

                foundUnmatchedTermsInDefault = set(default_fields) - set(all_terms)
                foundUnmatchedTermsInLocal = set(local_fields) - set(all_terms)

                if len(foundUnmatchedTermsInDefault):
                    isStreamValid = False
                    stream_validation_messages = "Some of the term that is present in the stream file, which is not matching with vocabulary terms\nFile location: {}".format(
                        os.path.join(self.DEFAULT_PATH, fileName)
                    )
                    break

                if len(foundUnmatchedTermsInLocal):
                    isStreamValid = False
                    stream_validation_messages = "Some of the term that is present in the stream file, which is not matching with vocabulary terms\nFile location: {}".format(
                        os.path.join(self.LOCAL_PATH, fileName)
                    )
                    break

                matched_field = list(set(default_fields) & set(local_fields))
                updated_fields = []
                updated_streams = {}

                with open(os.path.join(self.DEFAULT_PATH, fileName)) as fp:
                    data = json.load(fp)
                    updated_streams = data.copy()
                    updated_fields = updated_streams["fields"]

                    if len(data):
                        for index in range(len(data["fields"])):
                            term = data["fields"][index]["term"]
                            if term in matched_field:
                                updated_fields[index] = False

                with open(os.path.join(self.LOCAL_PATH, fileName)) as fp:
                    data = json.load(fp)
                    updated_streams = data.copy()
                    if len(data):
                        for index in range(len(data["fields"])):
                            term = data["fields"][index]["term"]
                            updated_fields.append(data["fields"][index])
                try:
                    while True:
                        updated_fields.remove(False)
                except ValueError:
                    pass

            updated_streams["fields"] = updated_fields

            final_streams = updated_streams
        return (
            list(default_files),
            list(local_files),
            final_streams,
            isStreamValid,
            stream_validation_messages,
        )

    def get_streams(self, isVocabValid):
        isValidStreams = True
        error_message = None
        (
            default_files,
            local_files,
            final_streams,
            isStreamValid,
            error_message,
        ) = self.streams_apply_layering()
        isValidStreams = isStreamValid

        if not isVocabValid:
            isValidStreams = False

        if not isValidStreams and not isinstance(error_message, list):
            print(f"Error : {error_message}")
        return isValidStreams


if __name__ == "__main__":
    print("*******************************************************************************")
    answer = check_app_regex()
    if bool(answer):
        vocabObject = Vocabulary()
        isVocabValid = vocabObject.get_Vocabs()

        confObject = Configurations()
        isConfValid = confObject.get_configurations(isVocabValid)

        streamObject = Streams()
        isStreamValid = streamObject.get_streams(isConfValid)

        if isVocabValid and isConfValid and isStreamValid:
            print("App is Valid")
        else:
            print("APP is Not Valid")
    else:
        if not os.path.exists(APP_PATH):
            print("APP Path Not Exist")
        else:
            print("App Name is Not Valid")
    print("*******************************************************************************")
