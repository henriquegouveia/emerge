"""
Contains the implementation of the XML language parser and a relevant keyword enum.
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
class XMLParsingKeyword(Enum):
    OPEN_TAG = "<"
    CLOSE_TAG = ">"
    CLOSE_OPEN_TAG = "/>"
    END_TAG = "</"
    ATTRIBUTE_ASSIGNMENT = "="
    ATTRIBUTE_VALUE = "\""
    COMMENT_START = "<!--"
    COMMENT_END = "-->"
    TAG_NAME = "tag_name"
    ATTRIBUTE_NAME = "attribute_name"


class XMLParser(AbstractParser, ParsingMixin):
    def __init__(self):
        self._results: Dict[str, AbstractResult] = {}
        self._token_mappings: Dict[str, str] = {
            '<': ' < ',
            '>': ' > ',
            '/': ' / ',
            '=': ' = ',
            '"': ' " ',
            '!--': ' <!-- ',
            '--': ' -- ',
        }

    @classmethod
    def parser_name(cls) -> str:
        return Parser.XML_PARSER.name

    @classmethod
    def language_type(cls) -> str:
        return LanguageType.XML.name

    @property
    def results(self) -> Dict[str, AbstractResult]:
        return self._results

    @results.setter
    def results(self, value):
        self._results = value

    def generate_file_result_from_analysis(self, analysis, *, file_name: str, full_file_path: str, file_content: str) -> None:
        LOGGER.debug('Generating file results...')
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
            scanned_language=LanguageType.XML,
            scanned_tokens=scanned_tokens,
            source=file_content,
            preprocessed_source=""
        )

        self._add_tags_to_result(file_result)
        self._results[file_result.unique_name] = file_result

    def after_generated_file_results(self, analysis) -> None:
        # This method can be used to curate results after all files have been processed.
        LOGGER.debug('Curating results after file generation...')
        # Implement any required logic to manipulate the results here.

    def generate_entity_results_from_analysis(self, analysis):
        LOGGER.debug('Generating entity results...')
        filtered_results = {k: v for (k, v) in self.results.items() if v.analysis is analysis and isinstance(v, FileResult)}

        for _, result in filtered_results.items():
            entity_keywords: List[str] = [XMLParsingKeyword.TAG_NAME.value]
            tag_name = pp.Word(pp.alphanums + "_-")
            match_expression = pp.Keyword(XMLParsingKeyword.OPEN_TAG.value) + \
                tag_name.setResultsName(CoreParsingKeyword.ENTITY_NAME.value) + \
                pp.Optional(pp.SkipTo(XMLParsingKeyword.CLOSE_TAG.value | XMLParsingKeyword.CLOSE_OPEN_TAG.value))

            entity_results = result.generate_entity_results_from_scopes(entity_keywords, match_expression)

            for entity_result in entity_results:
                self.create_unique_entity_name(entity_result)
                self._results[entity_result.unique_name] = entity_result

    def create_unique_entity_name(self, entity: AbstractEntityResult) -> None:
        entity.unique_name = entity.entity_name

    def _add_tags_to_result(self, result: FileResult):
        LOGGER.debug('Extracting tags from file result...')
        tokens = result.scanned_tokens
        for token in tokens:
            if token.startswith(XMLParsingKeyword.OPEN_TAG.value):
                tag_name = token[1:].split(XMLParsingKeyword.CLOSE_TAG.value)[0].strip()
                result.scanned_import_dependencies.append(tag_name)
                LOGGER.debug(f'Found tag: {tag_name}')

    def _add_imports_to_entity_result(self, entity_result: EntityResult):
        LOGGER.debug('Adding imports to entity result...')
        # Since XML does not have imports like Java, you may implement logic for dependencies if necessary.

    def _add_imports_to_result(self, result: FileResult, analysis):
        LOGGER.debug('Extracting imports from file result...')
        # XML does not use imports like Java, but if you have inter-file dependencies, implement that logic here.

    def _add_package_name_to_result(self, result: FileResult):
        LOGGER.debug('XML does not have a concept of packages like Java, skipping package extraction.')

    def _add_inheritance_to_entity_result(self, entity: AbstractEntityResult):
        LOGGER.debug('XML does not support inheritance like Java, skipping inheritance extraction.')

if __name__ == "__main__":
    LEXER = XMLParser()
    print(f'{LEXER.results=}')