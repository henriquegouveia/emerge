from enum import Enum, unique
from typing import Dict, List
import re
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


class VBNetParsingKeyword(Enum):
    CLASS = "Class"
    STRUCT = "Structure"
    INTERFACE = "Interface"
    ENUM = "Enum"
    NAMESPACE = "Namespace"
    IMPORT = "Imports"
    CLOSE_SCOPE = "End"
    SUB = "Sub"
    FUNCTION = "Function"
    IF = "If" 
    INLINE_COMMENT = "'"
    START_BLOCK_COMMENT = "''"
    STOP_BLOCK_COMMENT = "''"
    REGION = "Region"
    INHERITANCE = "Inherits"

class VBNetParser (AbstractParser, ParsingMixin):
    def __init__(self):
        self._results: Dict[str, AbstractResult] = {}
        
        self._token_mappings: Dict[str, str] = {
            ':': ' : ',
            ';': ' ; ',
            '(': ' ( ',
            ')': ' ) ',
            '{': ' { ',
            '}': ' } ',
            '[': ' [ ',
            ']': ' ] ',
            '?': ' ? ',
            '!': ' ! ',
            ',': ' , ',
            '<': ' < ',
            '>': ' > ',
            '"': ' " ',

        }

        self._ignore_entity_keywords: List[str] = [
            'Class', 'Structure', 'Interface', 'Enum', 'Namespace', 'Imports', 'Public', 'Private', 'Protected',
            'Friend', 'Static', 'ReadOnly', 'Overridable', 'MustOverride', 'NotOverridable', 'Shadows', 'New', 'Me',
            'MyBase', 'Event', 'Delegate', 'Operator', 'Implicit', 'Explicit'
        ]

    @classmethod
    def parser_name(cls) -> str:
         return Parser.VBNET_PARSER.name

    @classmethod
    def language_type(cls) -> str:
        return LanguageType.VBNET.name

    @property
    def results(self) -> Dict[str, AbstractResult]:
        return self._results

    @results.setter
    def results(self, value):
        self._results = value

    def remove_bom(self, input_string: str) -> str:
        # Check if the string starts with the BOM character sequence and remove it
        if input_string.startswith('ï»¿'):
            return input_string[3:]  # Return the string without the BOM
        return input_string  # Return the original string if no BOM is present  

    def preprocess_vbnet_source(self, scanned_tokens) -> List[str]:
        # Filter out #Region and #End Region tokens along with their names
        filtered_tokens = []

        region_start_block = "#"+VBNetParsingKeyword.REGION.value
        region_end_block= "#"+VBNetParsingKeyword.CLOSE_SCOPE.value + " " + VBNetParsingKeyword.REGION.value

        token_before = ''
        
        for current_token, next_token in zip(scanned_tokens, scanned_tokens[1:] + [""]):
            valid_token = True

            if(current_token == region_start_block):
                valid_token = False
            if(token_before == region_start_block and current_token.strip().startswith('"')):
                valid_token = False
            if((current_token + " " + next_token) == region_end_block ):
                valid_token = False
            if (valid_token):
                filtered_tokens.append(current_token)
            token_before = current_token

        source_string_no_comments = self._filter_source_tokens_without_comments(
            filtered_tokens,
            VBNetParsingKeyword.INLINE_COMMENT.value,
            VBNetParsingKeyword.START_BLOCK_COMMENT.value,
            VBNetParsingKeyword.STOP_BLOCK_COMMENT.value
        )
        filtered_list_no_comments = self.preprocess_file_content_and_generate_token_list_by_mapping(source_string_no_comments, self._token_mappings)

        return filtered_list_no_comments

    def generate_file_result_from_analysis(self, analysis, *, file_name: str, full_file_path: str, file_content: str) -> None:

        file_content = self.remove_bom(file_content)
        scanned_tokens: List[str] = self.preprocess_file_content_and_generate_token_list(file_content)
        
        scanned_tokens = self.preprocess_vbnet_source(scanned_tokens)
        
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
            scanned_language=LanguageType.VBNET,
            scanned_tokens=scanned_tokens,
            source=file_content,
            preprocessed_source=""
        )

        self._results[file_result.unique_name] = file_result

    def generate_entity_results_from_analysis(self, analysis) -> None:
        logging.debug('Generating entity results...')
        filtered_results: Dict[str, FileResult] = {k: v for (k, v) in self.results.items() if isinstance(v, AbstractFileResult)}

        for result in filtered_results.values():
            scanned_source_code = result.scanned_tokens

            # Define keywords and match expression for entity identification
            entity_keywords: List[str] = [
                VBNetParsingKeyword.CLASS.value,
                VBNetParsingKeyword.STRUCT.value,
                VBNetParsingKeyword.INTERFACE.value,
                VBNetParsingKeyword.ENUM.value
            ]

             # Define ParseElements for matching entity declarations
            entity_name = pp.Word(pp.alphanums + '_')
            match_expression = (pp.Keyword(VBNetParsingKeyword.CLASS.value) |
                                pp.Keyword(VBNetParsingKeyword.STRUCT.value) |
                                pp.Keyword(VBNetParsingKeyword.INTERFACE.value) |
                                pp.Keyword(VBNetParsingKeyword.ENUM.value)) + \
                               entity_name.setResultsName('entity_name')

            
            # Define comment keywords for filtering comments
            comment_keywords: Dict[str, str] = {
                'line_comment': VBNetParsingKeyword.INLINE_COMMENT.value,
                'start_block_comment': VBNetParsingKeyword.START_BLOCK_COMMENT.value,
                'stop_block_comment': VBNetParsingKeyword.STOP_BLOCK_COMMENT.value
            }

            # Use the helper method to generate entity results from scopes
            entity_results_unfiltered = self.generate_entity_results_from_scopes(result,entity_keywords, match_expression, comment_keywords)

            # Filter out entities that resulted from obvious parsing errors
            entity_results: List[AbstractEntityResult] = []
            for entity_result in entity_results_unfiltered:
                if entity_result.entity_name not in self._ignore_entity_keywords:
                    logging.debug(f'Valid entity found: {entity_result.entity_name}')
                    self._add_imports_to_single_entity_result(entity_result, scanned_source_code, analysis)
                    entity_results.append(entity_result)

            # Store the valid entity results
            for entity_result in entity_results:
                self._add_inheritance_to_entity_result(entity_result)
                self._results[entity_result.entity_name] = entity_result

    def _add_imports_to_single_entity_result(self, entity_result: AbstractEntityResult, scanned_tokens: List[str], analysis) -> None:
        """In VB.NET, Imports statements are scoped to the file level.
        This method iterates through each entity's scanned tokens
        to find and add Imports statements as import dependencies.
        """
        logging.debug('Adding Imports to entity result...')

        for _, obj, following in self._gen_word_read_ahead(scanned_tokens):
            if obj == VBNetParsingKeyword.IMPORT.value:
                try:
                    read_ahead_string = self.create_read_ahead_string(obj, following)
                    import_name = read_ahead_string.split('\n')[0].strip()
                    entity_result.scanned_import_dependencies.append(import_name.split(' ')[1].strip())
                    logging.debug(f'Adding import: {import_name}')
                except Exception as ex:
                    logging.warning(f"Error extracting Imports statement from entity {entity_result.entity_name}: {ex}")
            elif any(keyword in obj for keyword in [VBNetParsingKeyword.NAMESPACE.value,
                                                    VBNetParsingKeyword.CLASS.value,
                                                    VBNetParsingKeyword.STRUCT.value,
                                                    VBNetParsingKeyword.INTERFACE.value,
                                                    VBNetParsingKeyword.ENUM.value]):
                break
    def _add_inheritance_to_entity_result(self, result: AbstractEntityResult) -> None:
        LOGGER.debug(f'extracting inheritance from entity result {result.entity_name}...')
        parent_name = ''
        classOrInterfaceName = ''
        for current_token, next_token in zip(result.scanned_tokens, result.scanned_tokens[1:] + [""]):
            if any(keyword in current_token for keyword in [VBNetParsingKeyword.CLASS.value,
                                                    VBNetParsingKeyword.INTERFACE.value]):
                classOrInterfaceName = next_token
                
            if current_token == VBNetParsingKeyword.INHERITANCE.value and classOrInterfaceName != '':
                parent_name = next_token
                classOrInterfaceName = ''
                break

        if parent_name:
            result.scanned_inheritance_dependencies.append(parent_name)


    def after_generated_file_results(self, analysis) -> None:
        self._add_imports_to_file_results(analysis)

    def create_unique_entity_name(self, entity: AbstractEntityResult) -> None:
        return entity.entity_name

    def _filter_source_tokens_without_comments(self, list_of_words, line_comment_string, start_comment_string, stop_comment_string) -> str:
        source = " ".join(list_of_words)
        source_lines = source.splitlines()
        source_lines_without_comments = []
        active_block_comment = False


        for line in source_lines:
            # Skip lines containing #Region (with name) and #End Region
            if line.strip().startswith('#Region') or line.strip().startswith('#End Region'):
                continue
                
            if line.strip().startswith(start_comment_string):
                active_block_comment = True
                continue
            if line.strip().startswith(stop_comment_string):
                active_block_comment = False
                continue
            if line.strip().startswith(line_comment_string):
                continue

            if not active_block_comment:
                source_lines_without_comments.append(line)

        return "\n".join(source_lines_without_comments)

    def preprocess_file_content_and_generate_token_list_by_mapping(self, file_content, mapping_dict):
        for origin, mapped in mapping_dict.items():
            file_content = file_content.replace(origin, mapped)
        return re.findall(r'\S+|\n', file_content)


    def _add_imports_to_file_results(self, analysis) -> None:
        file_results: Dict[str, FileResult] = {
            k: v for (k, v) in self.results.items()
            if v.analysis is analysis and isinstance(v, FileResult)
        }

        for _, file_result in file_results.items():
            for _, obj, following in self._gen_word_read_ahead(file_result.scanned_tokens):
                if obj == VBNetParsingKeyword.IMPORT.value:
                    try:
                        read_ahead_string = self.create_read_ahead_string(obj, following)
                        import_name = read_ahead_string.split('\n')[0].strip()
                        file_result.scanned_import_dependencies.append(import_name.split(' ')[1].strip())
                    except Exception as ex:
                        logging.warning(f"Error extracting import statement from entity {file_result.display_name}: {ex}")

    @staticmethod
    def _gen_word_read_ahead(list_of_words):
        following = None
        length = len(list_of_words)
        for index, obj in enumerate(list_of_words):
            if index < (length - 1):
                following = list_of_words[index + 1:]
            yield index, obj, following

    @staticmethod
    def create_read_ahead_string(obj, following):
        read_ahead = [obj]
        read_ahead += following
        return " ".join(read_ahead)
    
    def generate_entity_results_from_scopes(self, result, entity_keywords, entity_expression, comment_keywords) -> List[EntityResult]:
        """Generate entity results by extracting everything within a scope that begins with an entity keyword."""
        close_scope_character: str = VBNetParsingKeyword.CLOSE_SCOPE.value

        line_comment_keyword: str = comment_keywords[CoreParsingKeyword.LINE_COMMENT.value]
        start_block_comment_keyword: str = comment_keywords[CoreParsingKeyword.START_BLOCK_COMMENT.value]
        stop_block_comment_keyword: str = comment_keywords[CoreParsingKeyword.STOP_BLOCK_COMMENT.value]

        found_entities: Dict[str, List[str]] = {}
        created_entity_results: List[EntityResult] = []

        list_of_words_with_newline_strings = result.scanned_tokens
        source_string_no_comments = self._filter_source_tokens_without_comments(
            list_of_words_with_newline_strings, line_comment_keyword, start_block_comment_keyword, stop_block_comment_keyword)

        # workaround to bypass scope false positives
        source_string_no_comments = source_string_no_comments.replace("{}", "")
        source_string_no_comments = source_string_no_comments.replace("{ }", "")

        filtered_list_no_comments = self.preprocess_file_content_and_generate_token_list(source_string_no_comments)

        previous_obj = ''
        for _, obj, following in self._gen_word_read_ahead(filtered_list_no_comments):
            if obj in entity_keywords and previous_obj != close_scope_character:
                read_ahead_string = self.create_read_ahead_string(obj, following)

                try:
                    parsing_result = entity_expression.parseString(read_ahead_string)
                except pp.ParseException:
                    result.analysis.statistics.increment(Statistics.Key.PARSING_MISSES)
                    LOGGER.warning(f'warning: could not parse result {result=}')
                    LOGGER.warning(f'next tokens: {[obj] + following[:ParsingMixin.Constants.MAX_DEBUG_TOKENS_READAHEAD.value]}')
                    continue

                LOGGER.debug(f'entity definition found: {parsing_result.entity_name}')
                result.analysis.statistics.increment(Statistics.Key.PARSING_HITS)

                scope_level = 0
                found_entities[parsing_result.entity_name] = []
                all_tokens = [obj] + following
                following_tokens = all_tokens[1:]+[""]

                iterTokens = 0
                iterNextTokens = 0
                while iterTokens < len(all_tokens) and iterNextTokens < len(following_tokens):
                    token = all_tokens[iterTokens]
                    next_token = following_tokens[iterNextTokens]
                    if any(keyword in token for keyword in [VBNetParsingKeyword.NAMESPACE.value,
                                                    VBNetParsingKeyword.CLASS.value,
                                                    VBNetParsingKeyword.STRUCT.value,
                                                    VBNetParsingKeyword.INTERFACE.value,
                                                    VBNetParsingKeyword.ENUM.value,
                                                    VBNetParsingKeyword.FUNCTION.value,
                                                    VBNetParsingKeyword.SUB.value,
                                                    VBNetParsingKeyword.IF.value]):
                        scope_level += 1

                    if token == close_scope_character and any(keyword in next_token for keyword in [VBNetParsingKeyword.NAMESPACE.value,
                                                    VBNetParsingKeyword.CLASS.value,
                                                    VBNetParsingKeyword.STRUCT.value,
                                                    VBNetParsingKeyword.INTERFACE.value,
                                                    VBNetParsingKeyword.ENUM.value,
                                                    VBNetParsingKeyword.FUNCTION.value,
                                                    VBNetParsingKeyword.SUB.value,
                                                    VBNetParsingKeyword.IF.value]):
                        scope_level -= 1
                        if scope_level == 0:
                            break
                        iterTokens+=2
                        iterNextTokens+=2

                    if parsing_result.entity_name in found_entities:
                        found_entities[parsing_result.entity_name].append(token)                       
                    iterTokens+=1
                    iterNextTokens+=1
            previous_obj = obj

        for entity_name, tokens in found_entities.items():

            unique_entity_name = result.absolute_name + "/" + entity_name
            entity_result = EntityResult(
                analysis=result.analysis,
                scanned_file_name=result.scanned_file_name,
                absolute_name=unique_entity_name,
                display_name=entity_name,
                scanned_by=result.scanned_by,
                scanned_language=result.scanned_language,
                scanned_tokens=tokens,
                scanned_import_dependencies=[],
                entity_name=entity_name,
                module_name=result.module_name,
                unique_name=entity_name,
                parent_file_result=result
            )

            created_entity_results.append(entity_result)
        return created_entity_results
    


if __name__ == "__main__":
    parser = VBNetParser()
    print(f'{parser.results=}')