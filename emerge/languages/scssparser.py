"""
Contains the implementation of the SCSS language parser and a relevant keyword enum.
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
class SCSSParsingKeyword(Enum):
    Mixin = "mixin"
    Extend = "extend"
    Import = "import"
    Include = "include"
    Variable = "$"
    OpenScope = "{"
    CloseScope = "}"
    InlineComment = "//"
    BlockCommentStart = "/*"
    BlockCommentEnd = "*/"
    Namespace = "namespace"  # Added for package-like functionality

class SCSSParser(AbstractParser, ParsingMixin):
    def __init__(self):
        self._results: Dict[str, AbstractResult] = {}
        self._token_mappings: Dict[str, str] = {
            ':': ' : ',
            ';': ' ; ',
            '{': ' { ',
            '}': ' } ',
            '(': ' ( ',
            ')': ' ) ',
            '[': ' [ ',
            ']': ' ] ',
            '?': ' ? ',
            '!': ' ! ',
            ',': ' , ',
            '<': ' < ',
            '>': ' > ',
            '"': ' " ',
        }

    @classmethod
    def parser_name(cls) -> str:
        return Parser.SCSS_PARSER.name

    @classmethod
    def language_type(cls) -> str:
        return LanguageType.SCSS.name

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
            scanned_language=LanguageType.SCSS,
            scanned_tokens=scanned_tokens,
            source=file_content,
            preprocessed_source=""
        )

        self._add_imports_to_result(file_result, analysis)
        self._results[file_result.unique_name] = file_result

    def after_generated_file_results(self, analysis) -> None:
        filtered_results = {k: v for (k, v) in self.results.items() if v.analysis is analysis and isinstance(v, FileResult)}

        result: FileResult
        for _, result in filtered_results.items():
            # Additional logic for SCSS can be added here.
            pass

    def create_unique_entity_name(self, entity: AbstractEntityResult) -> None:
        entity.unique_name = entity.entity_name

    def generate_entity_results_from_analysis(self, analysis):
        LOGGER.debug('generating entity results...')
        filtered_results = {k: v for (k, v) in self.results.items() if v.analysis is analysis and isinstance(v, FileResult)}

        result: FileResult
        for _, result in filtered_results.items():
            entity_keywords: List[str] = [SCSSParsingKeyword.Mixin.value, SCSSParsingKeyword.Variable.value]
            entity_name = pp.Word(pp.alphanums + "_-")
            match_expression = (
                pp.Keyword(SCSSParsingKeyword.Mixin.value) +
                entity_name.setResultsName(CoreParsingKeyword.ENTITY_NAME.value) +
                pp.Optional(pp.Keyword(SCSSParsingKeyword.Extend.value) + entity_name.setResultsName(CoreParsingKeyword.INHERITED_ENTITY_NAME.value)) +
                pp.SkipTo(pp.FollowedBy(SCSSParsingKeyword.OpenScope.value))
            )

            entity_results = result.generate_entity_results_from_scopes(entity_keywords, match_expression, {})

            for entity_result in entity_results:
                self._add_inheritance_to_entity_result(entity_result)
                self.create_unique_entity_name(entity_result)
                self._results[entity_result.unique_name] = entity_result

    def _add_imports_to_result(self, result: FileResult, analysis):
        LOGGER.debug('extracting imports from file result {result.scanned_file_name}...')
        list_of_words_with_newline_strings = result.scanned_tokens

        for _, obj, following in self._gen_word_read_ahead(list_of_words_with_newline_strings):
            if obj == SCSSParsingKeyword.Import.value:
                read_ahead_string = self.create_read_ahead_string(obj, following)

                imported_entity_name = pp.Word(pp.alphanums + '._')
                expression_to_match = (
                    pp.Keyword(SCSSParsingKeyword.Import.value) +
                    imported_entity_name.setResultsName(CoreParsingKeyword.IMPORT_ENTITY_NAME.value) +
                    pp.FollowedBy(CoreParsingKeyword.SEMICOLON.value)
                )

                try:
                    parsing_result = expression_to_match.parseString(read_ahead_string)
                except pp.ParseException as exception:
                    result.analysis.statistics.increment(Statistics.Key.PARSING_MISSES)
                    LOGGER.warning(f'warning: could not parse result {result=}\n{exception}')
                    continue

                result.scanned_import_dependencies.append(getattr(parsing_result, CoreParsingKeyword.IMPORT_ENTITY_NAME.value))
                result.analysis.statistics.increment(Statistics.Key.PARSING_HITS)

    def _add_imports_to_entity_result(self, entity_result: EntityResult):
        LOGGER.debug('adding imports to entity result...')
        for scanned_import in entity_result.parent_file_result.scanned_import_dependencies:
            if scanned_import not in entity_result.scanned_import_dependencies:
                entity_result.scanned_import_dependencies.append(scanned_import)

    def _add_package_name_to_result(self, result: FileResult):
        LOGGER.debug(f'extracting package or namespace from result {result.scanned_file_name}...')
        # SCSS does not have packages in the same way as Java, but we can consider namespaces if needed.
        list_of_words = result.scanned_tokens
        for _, obj, following in self._gen_word_read_ahead(list_of_words):
            if obj == SCSSParsingKeyword.Namespace.value:
                read_ahead_string = self.create_read_ahead_string(obj, following)

                namespace_name = pp.Word(pp.alphanums + "_")
                expression_to_match = (
                    pp.Keyword(SCSSParsingKeyword.Namespace.value) +
                    namespace_name.setResultsName(CoreParsingKeyword.ENTITY_NAME.value) +
                    pp.FollowedBy(CoreParsingKeyword.SEMICOLON.value)
                )

                try:
                    parsing_result = expression_to_match.parseString(read_ahead_string)
                except pp.ParseException as exception:
                    result.analysis.statistics.increment(Statistics.Key.PARSING_MISSES)
                    LOGGER.warning(f'warning: could not parse result {result=}\n{exception}')
                    continue

                result.module_name = getattr(parsing_result, CoreParsingKeyword.ENTITY_NAME.value)
                result.analysis.statistics.increment(Statistics.Key.PARSING_HITS)
                LOGGER.debug(f'namespace found: {result.module_name} and added to result')

    def _add_inheritance_to_entity_result(self, result: AbstractEntityResult):
        LOGGER.debug(f'extracting inheritance from entity result {result.entity_name}...')
        list_of_words = result.scanned_tokens
        for _, obj, following in self._gen_word_read_ahead(list_of_words):
            if obj == SCSSParsingKeyword.Extend.value:
                read_ahead_string = self.create_read_ahead_string(obj, following)

                inherited_entity_name = pp.Word(pp.alphanums + "_-")
                expression_to_match = (
                    pp.Keyword(SCSSParsingKeyword.Extend.value) +
                    inherited_entity_name.setResultsName(CoreParsingKeyword.INHERITED_ENTITY_NAME.value) +
                    pp.SkipTo(pp.FollowedBy(SCSSParsingKeyword.OpenScope.value))
                )

                try:
                    parsing_result = expression_to_match.parseString(read_ahead_string)
                except pp.ParseException as exception:
                    result.analysis.statistics.increment(Statistics.Key.PARSING_MISSES)
                    LOGGER.warning(f'warning: could not parse result {result=}\n{exception}')
                    continue

                if getattr(parsing_result, CoreParsingKeyword.INHERITED_ENTITY_NAME.value):
                    result.scanned_inheritance_dependencies.append(getattr(parsing_result, CoreParsingKeyword.INHERITED_ENTITY_NAME.value))
                    result.analysis.statistics.increment(Statistics.Key.PARSING_HITS)
                    LOGGER.debug(f'found inheritance entity {getattr(parsing_result, CoreParsingKeyword.INHERITED_ENTITY_NAME.value)} for entity name: {result.entity_name}')

if __name__ == "__main__":
    LEXER = SCSSParser()
    print(f'{LEXER.results=}')