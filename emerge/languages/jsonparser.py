"""
Contains the implementation of the JSON language parser and a relevant keyword enum.
"""

# Authors: Yohan Araujo <yaraujo@ciandt.com>
# License: MIT

from typing import Dict, List
from enum import Enum, unique
import logging
from pathlib import Path

import pyparsing as pp
import coloredlogs

from emerge.languages.abstractparser import AbstractParser, ParsingMixin, Parser, CoreParsingKeyword, LanguageType
from emerge.results import EntityResult, FileResult
from emerge.abstractresult import AbstractResult, AbstractEntityResult
from emerge.stats import Statistics
from emerge.log import Logger

LOGGER = Logger(logging.getLogger('parser'))
coloredlogs.install(level='E', logger=LOGGER.logger(), fmt=Logger.log_format)

@unique
class JSONParsingKeyword(Enum):
    OBJECT_START = "{"
    OBJECT_END = "}"
    ARRAY_START = "["
    ARRAY_END = "]"
    COLON = ":"
    COMMA = ","
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    NULL = "null"
    KEY = "key"

class JSONParser(AbstractParser, ParsingMixin):
    def __init__(self):
        self._results: Dict[str, AbstractResult] = {}
        self._token_mappings: Dict[str, str] = {
            ':': ' : ',
            ',': ' , ',
            '{': ' { ',
            '}': ' } ',
            '[': ' [ ',
            ']': ' ] ',
            '"': ' " ',
        }

    @classmethod
    def parser_name(cls) -> str:
        return Parser.JSON_PARSER.name

    @classmethod
    def language_type(cls) -> str:
        return LanguageType.JSON.name

    @property
    def results(self) -> Dict[str, AbstractResult]:
        return self._results

    @results.setter
    def results(self, value):
        self._results = value

    def generate_file_result_from_analysis(self, analysis, *, file_name: str, full_file_path: str, file_content: str) -> None:
        LOGGER.debug('generating file results...')
        scanned_tokens = self.preprocess_file_content_and_generate_token_list_by_mapping(file_content, self._token_mappings)

        parent_analysis_source_path = f"{Path(analysis.source_directory).parent}/"
        relative_file_path_to_analysis = full_file_path.replace(parent_analysis_source_path, "")

        file_result = FileResult.create_file_result(
            analysis=analysis,
            scanned_file_name=file_name,
            relative_file_path_to_analysis=relative_file_path_to_analysis,
            absolute_name=full_file_path,
            display_name=file_name,
            module_name="",
            scanned_by=self.parser_name(),
            scanned_language=LanguageType.JSON,
            scanned_tokens=scanned_tokens,
            source=file_content,
            preprocessed_source=""
        )

        self._results[file_result.unique_name] = file_result

    def after_generated_file_results(self, analysis) -> None:
        # JSON doesn't have imports, but you can implement any specific logic here
        filtered_results = {k: v for (k, v) in self.results.items() if v.analysis is analysis and isinstance(v, FileResult)}
        # No imports to curate in JSON

    def create_unique_entity_name(self, entity: AbstractEntityResult) -> None:
        # Implement unique naming logic if necessary
        entity.unique_name = entity.entity_name

    def generate_entity_results_from_analysis(self, analysis):
        LOGGER.debug('generating entity results...')
        filtered_results = {k: v for (k, v) in self.results.items() if v.analysis is analysis and isinstance(v, FileResult)}

        result: FileResult
        for _, result in filtered_results.items():
            # Define JSON parsing expressions
            json_key = pp.quotedString.setResultsName(CoreParsingKeyword.ENTITY_NAME.value)
            json_value = pp.Group(pp.Or([
                pp.quotedString.setResultsName(CoreParsingKeyword.VALUE.value),
                pp.Word(pp.nums).setResultsName(CoreParsingKeyword.VALUE.value),
                pp.Keyword("true").setResultsName(CoreParsingKeyword.VALUE.value),
                pp.Keyword("false").setResultsName(CoreParsingKeyword.VALUE.value),
                pp.Keyword("null").setResultsName(CoreParsingKeyword.VALUE.value),
                pp.Empty().setResultsName(CoreParsingKeyword.VALUE.value),  # For empty values
            ]))

            object_expression = pp.Suppress(JSONParsingKeyword.OBJECT_START.value) + \
                pp.Dict(pp.OneOrMore(json_key + pp.Suppress(JSONParsingKeyword.COLON.value) + json_value + pp.Optional(JSONParsingKeyword.COMMA.value)))

            # Parse the JSON object
            try:
                entity_results = object_expression.parseString(result.source)
                for key, value in entity_results.items():
                    entity_result = EntityResult(entity_name=key, scanned_tokens=value)
                    self.create_unique_entity_name(entity_result)
                    self._results[entity_result.unique_name] = entity_result
            except pp.ParseException as exception:
                result.analysis.statistics.increment(Statistics.Key.PARSING_MISSES)
                LOGGER.warning(f'warning: could not parse result {result=}\n{exception}')

    def _add_imports_to_entity_result(self, entity_result: EntityResult):
        # JSON does not have imports, so this is a no-op
        pass

    def _add_imports_to_result(self, result: FileResult, analysis):
        # JSON does not have imports, so this is a no-op
        pass

    def _add_package_name_to_result(self, result: FileResult):
        # JSON does not have package names, so this is a no-op
        pass

    def _add_inheritance_to_entity_result(self, result: AbstractEntityResult):
        # JSON does not have inheritance, so this is a no-op
        pass

if __name__ == "__main__":
    LEXER = JSONParser()
    print(f'{LEXER.results=}')