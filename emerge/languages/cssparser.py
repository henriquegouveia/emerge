"""
Contains the implementation of the CSS language parser and a relevant keyword enum.
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
class CSSParsingKeyword(Enum):
    SELECTOR = "selector"
    OPEN_BRACE = "{"
    CLOSE_BRACE = "}"
    PROPERTY = "property"
    VALUE = "value"
    COMMENT = "/*"
    END_COMMENT = "*/"
    IMPORT = "@import"

class CSSParser(AbstractParser, ParsingMixin):
    def __init__(self):
        self._results: Dict[str, AbstractResult] = {}
        self._token_mappings: Dict[str, str] = {
            '{': ' { ',
            '}': ' } ',
            ':': ' : ',
            ';': ' ; ',
            '/*': ' /* ',
            '*/': ' */ ',
            '@import': '@import ',
            ',': ' , ',
        }

    @classmethod
    def parser_name(cls) -> str:
        return Parser.CSS_PARSER.name

    @classmethod
    def language_type(cls) -> str:
        return LanguageType.CSS.name

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
            scanned_language=LanguageType.CSS,
            scanned_tokens=scanned_tokens,
            source=file_content,
            preprocessed_source=""
        )

        self._results[file_result.unique_name] = file_result

    def after_generated_file_results(self, analysis) -> None:
        """Process any dependencies in the generated CSS results."""
        LOGGER.debug('Post-processing generated file results...')
        filtered_results = {k: v for (k, v) in self.results.items() if v.analysis is analysis and isinstance(v, FileResult)}

        for _, result in filtered_results.items():
            # Extracting any @import dependencies
            for token in result.scanned_tokens:
                if token.startswith(CSSParsingKeyword.IMPORT.value):
                    import_statement = token[len(CSSParsingKeyword.IMPORT.value):].strip()
                    cleaned_import = import_statement.split(';')[0].strip().strip("'").strip('"')
                    result.scanned_import_dependencies.append(cleaned_import)
                    LOGGER.debug(f'Found import dependency: {cleaned_import}')

    def generate_entity_results_from_analysis(self, analysis):
        LOGGER.debug('generating entity results...')
        filtered_results = {k: v for (k, v) in self.results.items() if v.analysis is analysis and isinstance(v, FileResult)}

        result: FileResult
        for _, result in filtered_results.items():
            match_expression = pp.Group(pp.Word(pp.alphanums + '-')) + \
                               pp.Suppress(CSSParsingKeyword.OPEN_BRACE.value) + \
                               pp.Group(pp.delimitedList(pp.Keyword(CSSParsingKeyword.PROPERTY.value) + pp.Word(pp.alphanums + '-:;') + pp.Suppress(CSSParsingKeyword.VALUE.value))) + \
                               pp.Suppress(CSSParsingKeyword.CLOSE_BRACE.value)

            entity_results = result.generate_entity_results_from_scopes([CSSParsingKeyword.SELECTOR.value], match_expression)

            for entity_result in entity_results:
                self._add_imports_to_entity_result(entity_result)
                self.create_unique_entity_name(entity_result)
                self._results[entity_result.unique_name] = entity_result

    def create_unique_entity_name(self, entity: AbstractEntityResult) -> None:
        entity.unique_name = entity.entity_name

    def _add_imports_to_entity_result(self, entity_result: EntityResult):
        """Add import dependencies to an entity result."""
        LOGGER.debug('adding imports to entity result...')
        for import_dependency in entity_result.parent_file_result.scanned_import_dependencies:
            if import_dependency not in entity_result.scanned_import_dependencies:
                entity_result.scanned_import_dependencies.append(import_dependency)

    def _add_imports_to_result(self, result: FileResult, analysis):
        """Extract and add import dependencies to the file result."""
        LOGGER.debug(f'extracting imports from file result {result.scanned_file_name}...')
        for token in result.scanned_tokens:
            if token.startswith(CSSParsingKeyword.IMPORT.value):
                import_statement = token[len(CSSParsingKeyword.IMPORT.value):].strip()
                cleaned_import = import_statement.split(';')[0].strip().strip("'").strip('"')
                result.scanned_import_dependencies.append(cleaned_import)
                LOGGER.debug(f'Added import dependency to result: {cleaned_import}')

    def _add_package_name_to_result(self, result: FileResult):
        """This could be relevant for namespaces in CSS, if applicable."""
        # CSS does not have a package structure like Java, but you might apply a similar concept for context.
        LOGGER.debug(f'Package name concept is not typically applicable to CSS. Skipping for {result.scanned_file_name}.')

    def _add_inheritance_to_entity_result(self, entity: AbstractEntityResult):
        """In CSS, this could refer to nested selectors."""
        LOGGER.debug(f'checking for inheritance in entity result {entity.entity_name}...')
        # Example logic to handle nested selectors (inheritance in CSS)
        if ' ' in entity.entity_name:  # A space indicates potential nested selectors
            nested_selectors = entity.entity_name.split(' ')
            entity.scanned_inheritance_dependencies.extend(nested_selectors)
            LOGGER.debug(f'Added nested selectors to inheritance: {nested_selectors}')

    def _add_comments_to_result(self, result: FileResult):
        LOGGER.debug(f'extracting comments from result {result.scanned_file_name}...')
        list_of_words = result.scanned_tokens
        for _, obj, following in self._gen_word_read_ahead(list_of_words):
            if obj == CSSParsingKeyword.COMMENT.value:
                read_ahead_string = self.create_read_ahead_string(obj, following)
                # Process comments here if needed
                pass

if __name__ == "__main__":
    LEXER = CSSParser()
    print(f'{LEXER.results=}')