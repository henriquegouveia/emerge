"""
Contains the implementation of the C# language parser and a relevant keyword enum.
"""

# Authors: Henrique Gouveia <hgouveia@icloud.com>

from typing import Dict, List
from enum import Enum, unique
import logging
from pathlib import Path

import pyparsing as pp
import coloredlogs
import re

from emerge.languages.abstractparser import AbstractParser, ParsingMixin, Parser, CoreParsingKeyword, LanguageType
from emerge.results import FileResult, EntityResult
from emerge.abstractresult import AbstractResult, AbstractFileResult, AbstractEntityResult
from emerge.stats import Statistics
from emerge.log import Logger

LOGGER = Logger(logging.getLogger('parser'))
coloredlogs.install(level='E', logger=LOGGER.logger(), fmt=Logger.log_format)


@unique
class CSharpParsingKeyword(Enum):
    CLASS = "class"
    STRUCT = "struct"
    INTERFACE = "interface"
    ENUM = "enum"
    NAMESPACE = "namespace"
    USING = "using"
    OPEN_SCOPE = "{"
    CLOSE_SCOPE = "}"
    INLINE_COMMENT = "//"
    START_BLOCK_COMMENT = "/*"
    STOP_BLOCK_COMMENT = "*/"


class CSharpParser(AbstractParser, ParsingMixin):

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
            ".": ' . ',
        }

        # WORKAROUND: filter out entities that resulted from obvious parsing errors
        self._ignore_entity_keywords: List[str] = [
            'class', 'struct', 'interface', 'enum', 'namespace', 'using', 'public', 'private', 'protected',
            'internal', 'static', 'readonly', 'virtual', 'override', 'abstract', 'new', 'this',
            'base', 'event', 'delegate', 'operator', 'implicit', 'explicit'
        ]

    @classmethod
    def parser_name(cls) -> str:
        return Parser.CSHARP_PARSER.name

    @classmethod
    def language_type(cls) -> str:
        return LanguageType.CSHARP.name

    @property
    def results(self) -> Dict[str, AbstractResult]:
        return self._results

    @results.setter
    def results(self, value):
        self._results = value

    def preprocess_csharp_source(self, scanned_tokens) -> str:
        source_string_no_comments = self._filter_source_tokens_without_comments(
            scanned_tokens,
            CSharpParsingKeyword.INLINE_COMMENT.value,
            CSharpParsingKeyword.START_BLOCK_COMMENT.value,
            CSharpParsingKeyword.STOP_BLOCK_COMMENT.value
        )
        filtered_list_no_comments = self.preprocess_file_content_and_generate_token_list_by_mapping(source_string_no_comments, self._token_mappings)
        preprocessed_source_string = " ".join(filtered_list_no_comments)
        return preprocessed_source_string

    def generate_file_result_from_analysis(self, analysis, *, file_name: str, full_file_path: str, file_content: str) -> None:
        LOGGER.debug('generating file results...')

        scanned_tokens: List[str] = self.preprocess_file_content_and_generate_token_list(file_content)

        # make sure to create unique names by using the relative analysis path as a base for the result
        parent_analysis_source_path = f"{Path(analysis.source_directory).parent}/"
        relative_file_path_to_analysis = full_file_path.replace(parent_analysis_source_path, "")

        file_result = FileResult.create_file_result(
            analysis=analysis,
            scanned_file_name=relative_file_path_to_analysis,
            relative_file_path_to_analysis=relative_file_path_to_analysis,
            absolute_name=full_file_path,
            display_name=file_name,
            module_name="",
            scanned_by=self.parser_name(),
            scanned_language=LanguageType.CSHARP,
            scanned_tokens=scanned_tokens,
            source=file_content,
            preprocessed_source=""
        )

        self._add_namespace_to_result(file_result)
        self._results[file_result.unique_name] = file_result

    def after_generated_file_results(self, analysis) -> None:
        self._add_usings_to_file_results(analysis)

    def create_unique_entity_name(self, entity: AbstractEntityResult) -> None:
        # Entity naming convention in C# already includes namespaces
        # So we can directly use the entity name here
        return entity.entity_name

    def generate_entity_results_from_analysis(self, analysis):
        LOGGER.debug('generating entity results...')
        filtered_results: Dict[str, FileResult] = {k: v for (k, v) in self.results.items() \
            if v.analysis is analysis and isinstance(v, AbstractFileResult)}

        result: FileResult
        for _, result in filtered_results.items():
            scanned_source_code = result.scanned_tokens

            for line in iter(scanned_source_code):
                if any(keyword in line for keyword in [CSharpParsingKeyword.CLASS.value,
                                                       CSharpParsingKeyword.STRUCT.value,
                                                       CSharpParsingKeyword.INTERFACE.value,
                                                       CSharpParsingKeyword.ENUM.value]):

                    entity_keywords: List[str] = [
                        CSharpParsingKeyword.CLASS.value,
                        CSharpParsingKeyword.STRUCT.value,
                        CSharpParsingKeyword.INTERFACE.value,
                        CSharpParsingKeyword.ENUM.value
                    ]
                    entity_name = pp.Word(pp.alphanums + CoreParsingKeyword.DOT.value + CoreParsingKeyword.UNDERSCORE.value)

                    match_expression = (
                        pp.Keyword(CSharpParsingKeyword.CLASS.value) |
                        pp.Keyword(CSharpParsingKeyword.STRUCT.value) |
                        pp.Keyword(CSharpParsingKeyword.INTERFACE.value) |
                        pp.Keyword(CSharpParsingKeyword.ENUM.value)) + \
                        entity_name.setResultsName(CoreParsingKeyword.ENTITY_NAME.value) + \
                        pp.Optional(pp.Keyword(CoreParsingKeyword.COLON.value)) + pp.SkipTo(
                        pp.FollowedBy(CSharpParsingKeyword.OPEN_SCOPE.value))

                    comment_keywords: Dict[str, str] = {
                        CoreParsingKeyword.LINE_COMMENT.value: CSharpParsingKeyword.INLINE_COMMENT.value,
                        CoreParsingKeyword.START_BLOCK_COMMENT.value: CSharpParsingKeyword.START_BLOCK_COMMENT.value,
                        CoreParsingKeyword.STOP_BLOCK_COMMENT.value: CSharpParsingKeyword.STOP_BLOCK_COMMENT.value
                    }

                    entity_results_unfiltered = result.generate_entity_results_from_scopes(entity_keywords, match_expression,
                                                                                         comment_keywords)
                    entity_results: List[AbstractEntityResult] = []

                    # WORKAROUND: filter out entities that resulted from obvious parsing errors
                    filtered_entity_results = [x for x in entity_results_unfiltered if
                                                not x.entity_name in self._ignore_entity_keywords]

                    # filter even more on the basis of a configured ignore list
                    for entity_result in filtered_entity_results:
                        if self.is_entity_in_ignore_list(entity_result.entity_name, analysis):
                            pass
                        else:
                            # add dependencies based on the full file, as the way the entity is parsed, using statements are not included
                            entity_result_with_dependencies = self._add_usings_to_single_entity_result(entity_result,scanned_source_code)
                            entity_results.append(entity_result_with_dependencies)

                    for entity_result in entity_results:
                        LOGGER.debug(f'{entity_result.entity_name=}')
                        self._add_inheritance_to_entity_result(entity_result)
                        self._results[entity_result.entity_name] = entity_result


    def _add_inheritance_to_entity_result(self, result: AbstractEntityResult) -> None:
        LOGGER.debug(f'extracting inheritance from entity result {result.entity_name}...')
        parent_name = ''

        for current_token, next_token in zip(result.scanned_tokens, result.scanned_tokens[1:] + [""]):
            if current_token == CoreParsingKeyword.COLON.value:
                parent_name = next_token
                break

        if parent_name:
            result.scanned_inheritance_dependencies.append(parent_name)

    def _add_usings_to_single_entity_result(self,entity_result,scanned_tokens) -> AbstractEntityResult:
        """In C#, using statements are scoped to the file level.
        This method iterates through each entity's scanned tokens
        to find and add using statements as import dependencies.
        """
        LOGGER.debug('adding usings to entity result...')

        for _, obj, following in self._gen_word_read_ahead(scanned_tokens):
            if obj == CSharpParsingKeyword.USING.value:
                try:
                    read_ahead_string = self.create_read_ahead_string(obj, following)
                    import_name = read_ahead_string.split(';')[0].strip()
                    entity_result.scanned_import_dependencies.append(import_name.split(' ')[1].strip())
                except Exception as ex:
                    LOGGER.warning(
                        f"Error extracting using statement from entity {entity_result.entity_name}: {ex}"
                    )
            elif any(keyword in obj for keyword in [CSharpParsingKeyword.NAMESPACE.value,
                                                    CSharpParsingKeyword.CLASS.value,
                                                    CSharpParsingKeyword.STRUCT.value,
                                                    CSharpParsingKeyword.INTERFACE.value,
                                                    CSharpParsingKeyword.ENUM.value]):
                break
        return entity_result

    def _add_usings_to_entity_results(self, analysis) -> None:
        """In C#, using statements are scoped to the file level.
        This method iterates through each entity's scanned tokens
        to find and add using statements as import dependencies.
        """

        LOGGER.debug('adding usings to entity result...')
        entity_results: Dict[str, AbstractEntityResult] = {
            k: v for (k, v) in self.results.items()
            if v.analysis is analysis and isinstance(v, AbstractEntityResult)
        }

        for _, entity_result in entity_results.items():
            for _, obj, following in self._gen_word_read_ahead(entity_result.scanned_tokens):
                if obj == CSharpParsingKeyword.USING.value:
                    try:
                        read_ahead_string = self.create_read_ahead_string(obj, following)
                        import_name = read_ahead_string.split(';')[0].strip()
                        entity_result.scanned_import_dependencies.append(import_name)
                    except Exception as ex:
                        LOGGER.warning(
                            f"Error extracting using statement from entity {entity_result.entity_name}: {ex}"
                        )
    def _add_usings_to_file_results(self, analysis) -> None:
        LOGGER.debug('adding usings to file results...')
        namespace_pattern = r'^\s*using\s+[a-zA-Z0-9_.]+$'
        file_results: Dict[str, FileResult] = {
            k: v for (k, v) in self.results.items()
            if v.analysis is analysis and isinstance(v, FileResult)
        }

        for _, file_result in file_results.items():
            for _, obj, following in self._gen_word_read_ahead(file_result.scanned_tokens):
                if obj == CSharpParsingKeyword.USING.value:
                    try:
                        read_ahead_string = self.create_read_ahead_string(obj, following)
                        import_name = read_ahead_string.split(';')[0].strip()
                        if re.match(namespace_pattern, import_name):
                            file_result.scanned_import_dependencies.append(import_name.split(' ')[1].strip())
                    except Exception as ex:
                        LOGGER.warning(f"Error extracting using statement from file {file_result.unique_name}: {ex}")

    def _add_namespace_to_result(self, result: FileResult):
        """Extracts the namespace from a C# file and adds it to the result.

        Args:
            result (FileResult): The FileResult object to add the namespace to.
        """
        LOGGER.debug(f'extracting namespace from file result {result.scanned_file_name}...')

        namespace_keyword = CSharpParsingKeyword.NAMESPACE.value
        for index, token in enumerate(result.scanned_tokens):
            if token == namespace_keyword:
                try:
                    namespace_parts = []
                    current_index = index + 1
                    while result.scanned_tokens[current_index] != CSharpParsingKeyword.OPEN_SCOPE.value:
                        namespace_parts.append(result.scanned_tokens[current_index])
                        current_index += 1
                    result.module_name = ".".join(namespace_parts)
                    LOGGER.debug(f'added namespace: {result.module_name} to result')
                    break  # Assuming one namespace declaration per file
                except IndexError:
                    LOGGER.warning(
                        f"Incomplete namespace declaration found in file: {result.scanned_file_name}"
                    )
                    break

if __name__ == "__main__":
    LEXER = CSharpParser()
    print(f'{LEXER.results=}')
