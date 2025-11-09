import re
import logging
from typing import Dict, List, Tuple, Optional, Any

logger = logging.getLogger(__name__)

# --- Constants ---
DEFAULT_ENCODING = 'utf-8'
SECTION_SCRIPT_INFO = "Script Info"
SECTION_STYLES_V4PLUS = "V4+ Styles"
SECTION_STYLES_V4 = "V4 Styles"
SECTION_EVENTS = "Events"
DEFAULT_STYLE_FORMAT = "Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding"
ALT_STYLE_FORMAT_SSA = "Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,TertiaryColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,AlphaLevel,Encoding"
DEFAULT_EVENT_FORMAT = "Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"
ALT_EVENT_FORMAT_MARKED = "Marked,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"
ASS_ALIGNMENT_MAP = {
    '1': ('end', 'start'), '2': ('end', 'center'), '3': ('end', 'end'),
    '4': ('middle', 'start'), '5': ('middle', 'center'), '6': ('middle', 'end'),
    '7': ('start', 'start'), '8': ('start', 'center'), '9': ('start', 'end'),
}
DEFAULT_ASS_ALIGNMENT = '2'


class AssConverterError(Exception):
    """Base exception for conversion errors."""
    pass


class AssParsingError(AssConverterError):
    """Error during ASS/SSA data parsing."""
    pass


class VttConversionError(AssConverterError):
    """Error during VTT generation."""
    pass


def _convert_ass_color_to_css(ass_color_str: Optional[str]) -> Optional[str]:
    """Converts ASS color format (&HAABBGGRR or &HBBGGRR) to CSS rgba() or #RRGGBB."""
    if not ass_color_str or not ass_color_str.startswith('&H'):
        return None
    hex_color = ass_color_str[2:].upper()
    try:
        if len(hex_color) == 8:
            alpha_hex, blue_hex, green_hex, red_hex = hex_color[0:2], hex_color[2:4], hex_color[4:6], hex_color[6:8]
            alpha_val = round(1.0 - (int(alpha_hex, 16) / 255.0), 3)
        elif len(hex_color) == 6:
            blue_hex, green_hex, red_hex = hex_color[0:2], hex_color[2:4], hex_color[4:6]
            alpha_val = 1.0
        else:
            logger.warning(f"Invalid ASS color format length: {ass_color_str}")
            return None
        r, g, b = int(red_hex, 16), int(green_hex, 16), int(blue_hex, 16)
        if alpha_val >= 0.999:
            return f"#{red_hex}{green_hex}{blue_hex}".lower()
        else:
            return f"rgba({r},{g},{b},{alpha_val})"
    except ValueError:
        logger.warning(f"Could not parse ASS color: {ass_color_str}")
        return None
    except Exception as e:
        logger.warning(f"Unexpected error parsing ASS color {ass_color_str}: {e}")
        return None


class AssParser:
    """Parses data in ASS or SSA format."""

    def __init__(self):
        self.sections: Dict[str, List[str]] = {}
        self.info: Dict[str, Any] = {'PlayResX': 0, 'PlayResY': 0, 'WrapStyle': '1'}
        self.styles: Dict[str, Dict[str, Any]] = {}
        self.events: List[Dict[str, Any]] = []
        self._style_format: List[str] = []
        self._event_format: List[str] = []
        self.filepath: Optional[str] = None

    def _read_file_content(self, filepath: str, encoding: Optional[str] = None) -> str:
        """Reads a file, trying different encodings, prioritizing utf-8-sig for BOM handling."""
        self.filepath = filepath
        encodings_to_try = [encoding] if encoding else ['utf-8-sig', DEFAULT_ENCODING, 'utf-16']

        logger.debug(f"Attempting to read '{filepath}' with encodings: {encodings_to_try}")

        successful_encoding = None
        file_content = None

        for enc in encodings_to_try:
            if enc is None: continue
            try:
                with open(filepath, 'r', encoding=enc) as f:
                    file_content = f.read()
                    successful_encoding = enc
                    logger.debug(f"Successfully read file {filepath} with encoding: {successful_encoding}")
                    break  # Stop after successful read
            except UnicodeDecodeError:
                logger.debug(f"Failed to read file {filepath} with encoding: {enc}. Trying next...")
            except FileNotFoundError:
                raise AssParsingError(f"File not found: {filepath}")
            except Exception as e:
                logger.error(f"An unexpected error occurred while reading file {filepath} with encoding {enc}: {e}")
                # Continue trying other encodings for robustness, unless it's FileNotFoundError

        if file_content is None:
            raise AssParsingError(
                f"Failed to read file {filepath} using any of the attempted encodings: {encodings_to_try}")

        # Double-check for BOM and remove manually if it somehow persisted
        if file_content.startswith('\ufeff'):
            logger.debug(
                "BOM detected at the beginning of the content despite reading attempts. Removing BOM manually.")
            file_content = file_content[1:]

        return file_content

    def parse_file(self, filepath: str, encoding: Optional[str] = None) -> bool:
        logger.debug(f"Starting parsing of file: {filepath}")
        try:
            content = self._read_file_content(filepath, encoding)
            return self._process_content(content)
        except AssParsingError as e:
            logger.error(f"Error parsing file: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during parsing of file {filepath}: {e}")
            raise AssParsingError(
                f"Unexpected error during parsing of file {filepath}: {e}")

    def parse_string(self, ass_content: str, play_res_x: Optional[int] = None,
                     play_res_y: Optional[int] = None) -> bool:
        logger.debug("Starting parsing from string.")
        self.filepath = None
        if play_res_x is not None: self.info['PlayResX'] = play_res_x
        if play_res_y is not None: self.info['PlayResY'] = play_res_y
        # Remove potential BOM from string input as well
        if ass_content.startswith('\ufeff'):
            logger.debug("Removing UTF-8 BOM from input string.")
            ass_content = ass_content[1:]
        try:
            return self._process_content(ass_content)
        except AssParsingError as e:
            logger.error(f"Error parsing string: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during parsing of string: {e}")
            raise AssParsingError(
                f"Unexpected error during parsing of string: {e}")

    def _process_content(self, content: str) -> bool:
        self.sections, self.styles, self.events = {}, {}, []
        self.info = {'PlayResX': self.info.get('PlayResX', 0), 'PlayResY': self.info.get('PlayResY', 0),
                     'WrapStyle': '1'}

        self._split_into_sections(content)

        if not self.sections and SECTION_EVENTS not in self.sections:
            logger.warning("No sections found or [Events] section is missing.")
            if not self.sections.get(SECTION_EVENTS): raise AssParsingError(
                "Missing [Events] section; other key sections might also be missing.")

        self._parse_script_info()
        self._parse_styles()
        self._parse_events()
        if not self.events: logger.warning("No events (Dialogue lines) parsed.")
        logger.debug("Parsing finished.")
        return True

    def _split_into_sections(self, content: str):
        current_section_name = None
        lines = content.splitlines()
        for line in lines:
            line = line.strip()  # Strips leading/trailing whitespace AND potentially BOM if not handled before
            if not line: continue
            # Check specifically for BOM just in case strip didn't get it
            line_to_check = line.lstrip('\ufeff')

            if line_to_check.startswith('[') and line_to_check.endswith(']'):
                current_section_name = line_to_check[1:-1]
                if current_section_name not in self.sections: self.sections[current_section_name] = []
                logger.debug(f"Switched to section: [{current_section_name}]")
            elif current_section_name and not line_to_check.startswith(';'):
                self.sections[current_section_name].append(line)  # Append original line (with potential whitespace)

    def _parse_script_info(self):
        # Using the version with enhanced logging from previous step
        if SECTION_SCRIPT_INFO not in self.sections:
            logger.warning(
                "Missing [Script Info] section. Using default values for resolution (if not provided otherwise).")
            self.info['PlayResX'] = self.info.get('PlayResX', 0)
            self.info['PlayResY'] = self.info.get('PlayResY', 0)
            return

        parsed_info_this_run = {}
        logger.debug(f"Parsing section: [{SECTION_SCRIPT_INFO}]")
        for line in self.sections[SECTION_SCRIPT_INFO]:
            if ':' in line:
                key, value = line.split(':', 1)
                stripped_key = key.strip()
                stripped_value = value.strip()
                parsed_info_this_run[stripped_key] = stripped_value
                logger.debug(f"  Found key: '{stripped_key}', value: '{stripped_value}'")
            elif not line.startswith(';'):
                logger.warning(f"  Ignoring unknown line in [Script Info]: {line}")

        for key, value in parsed_info_this_run.items(): self.info[key] = value
        logger.debug(f"Updated self.info after parsing [Script Info]: {self.info}")

        raw_resx = self.info.get('PlayResX')
        logger.debug(f"Attempting conversion for PlayResX. Raw: '{raw_resx}' (type: {type(raw_resx)})")
        try:
            stripped_resx = str(raw_resx).strip()
            logger.debug(f"Value after str().strip() for PlayResX: '{stripped_resx}'")
            self.info['PlayResX'] = int(stripped_resx)
            logger.debug(f"Successfully converted PlayResX to int: {self.info['PlayResX']}")
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning(
                f"Invalid or missing PlayResX value ('{raw_resx}'). Could not convert to int. Using 0. Error: {e}")
            self.info['PlayResX'] = 0

        raw_resy = self.info.get('PlayResY')
        logger.debug(f"Attempting conversion for PlayResY. Raw: '{raw_resy}' (type: {type(raw_resy)})")
        try:
            stripped_resy = str(raw_resy).strip()
            logger.debug(f"Value after str().strip() for PlayResY: '{stripped_resy}'")
            self.info['PlayResY'] = int(stripped_resy)
            logger.debug(f"Successfully converted PlayResY to int: {self.info['PlayResY']}")
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning(
                f"Invalid or missing PlayResY value ('{raw_resy}'). Could not convert to int. Using 0. Error: {e}")
            self.info['PlayResY'] = 0

        logger.debug(
            f"Final Script resolution after conversion attempt: {self.info.get('PlayResX')}x{self.info.get('PlayResY')}")

    def _parse_styles(self):
        styles_section_name, format_line_found = None, False
        if SECTION_STYLES_V4PLUS in self.sections:
            styles_section_name, self._style_format = SECTION_STYLES_V4PLUS, DEFAULT_STYLE_FORMAT.split(',')
        elif SECTION_STYLES_V4 in self.sections:
            styles_section_name, self._style_format = SECTION_STYLES_V4, ALT_STYLE_FORMAT_SSA.split(',')
        else:
            logger.warning("Missing styles section.")
            return
        logger.debug(f"Parsing section: [{styles_section_name}]")
        for line in self.sections[styles_section_name]:
            line_lower = line.lower()
            if line_lower.startswith("format:"):
                self._style_format, format_line_found = [h.strip() for h in
                                                         line[len("format:"):].strip().split(',')], True
                logger.debug(
                    f"Found custom style format: {self._style_format}")
            elif line_lower.startswith("style:"):
                if not format_line_found:
                    default_format = DEFAULT_STYLE_FORMAT if styles_section_name == SECTION_STYLES_V4PLUS else ALT_STYLE_FORMAT_SSA
                    self._style_format, format_line_found = default_format.split(','), True
                    logger.warning(f"Missing 'Format:' in styles. Using default for {styles_section_name}.")
                parts = line[len("style:"):].strip().split(',', len(self._style_format) - 1)
                if len(parts) != len(self._style_format):
                    logger.warning(f"Incorrect field count in style line: {line}. Ignoring.")
                    continue
                style_dict = {key: parts[i].strip() for i, key in enumerate(self._style_format)}
                style_name = style_dict.get('Name')
                if style_name:
                    for key in ['Fontsize', 'Bold', 'Italic', 'Underline', 'StrikeOut', 'ScaleX', 'ScaleY', 'Spacing',
                                'Angle', 'BorderStyle', 'Outline', 'Shadow', 'MarginL', 'MarginR', 'MarginV',
                                'Encoding', 'AlphaLevel']:
                        if key in style_dict:
                            try:
                                if key in ['Bold', 'Italic', 'Underline', 'StrikeOut']:
                                    style_dict[key] = int(style_dict[key])
                                elif key == 'Alignment':
                                    pass
                                else:
                                    style_dict[key] = float(style_dict[key])
                            except (ValueError, TypeError):
                                logger.warning(
                                    f"Invalid numeric value for '{key}' in style '{style_name}': {style_dict[key]}. Using 0.")
                                style_dict[key] = 0
                    normalized_style_name = style_name.replace(" ", "_")
                    self.styles[normalized_style_name] = style_dict
                    self.styles[normalized_style_name]['OriginalName'] = style_name
                    logger.debug(f"Parsed style: {normalized_style_name} (originally: {style_name})")
                else:
                    logger.warning(f"Ignoring style without a name: {line}")

    def _parse_events(self):
        if SECTION_EVENTS not in self.sections:
            logger.warning("Missing [Events] section. No subtitles.")
            self.events = []
            return
        self._event_format, format_line_found = DEFAULT_EVENT_FORMAT.split(','), False
        logger.debug(f"Parsing section: [{SECTION_EVENTS}]")
        for line in self.sections[SECTION_EVENTS]:
            line_lower = line.lower()
            if line_lower.startswith("format:"):
                self._event_format = [h.strip() for h in line[len("format:"):].strip().split(',')]
                if 'Marked' in self._event_format and 'Layer' not in self._event_format:
                    self._event_format = ['Layer' if h == 'Marked' else h for h in self._event_format]
                format_line_found = True
                logger.debug(f"Found custom event format: {self._event_format}")
            elif line_lower.startswith("dialogue:"):
                if not format_line_found:
                    self._event_format = DEFAULT_EVENT_FORMAT.split(',')
                    test_parts = line[len("dialogue:"):].strip().split(',', len(self._event_format) - 1)
                    if not (len(test_parts) > 0 and test_parts[0].isdigit()):
                        self._event_format = ALT_EVENT_FORMAT_MARKED.split(',')
                        if 'Marked' in self._event_format and 'Layer' not in self._event_format: self._event_format = [
                            'Layer' if h == 'Marked' else h for h in self._event_format]
                    logger.warning("Missing 'Format:' line in [Events]. Using default/inferred format.")
                    format_line_found = True
                parts = line[len("dialogue:"):].strip().split(',', len(self._event_format) - 1)
                if len(parts) != len(self._event_format):
                    logger.warning(f"Incorrect field count in Dialogue: {line}. Ignoring.")
                    continue
                event_dict = {}
                try:
                    for i, key in enumerate(self._event_format): event_dict[key] = parts[i].strip()
                    for key in ['MarginL', 'MarginR', 'MarginV']: event_dict[key] = int(event_dict.get(key, 0))
                    event_dict['Layer'] = int(event_dict.get('Layer', 0))
                    if 'Style' in event_dict: event_dict['Style'] = event_dict['Style'].replace(" ", "_")
                    self.events.append(event_dict)
                except ValueError:
                    logger.warning(f"Could not parse numeric values in Dialogue: {line}. Ignoring.")
                except Exception as e:
                    logger.warning(f"Error parsing Dialogue line: {line}. Error: {e}. Ignoring.")
            elif not line_lower.startswith("comment:"):
                logger.warning(f"Ignoring unknown line in [Events]: {line}")


class VttConverter:
    """Converts parsed ASS/SSA data to WebVTT format."""

    def __init__(self, info: Dict[str, Any], styles: Dict[str, Dict[str, Any]], events: List[Dict[str, Any]]):
        self.info, self.styles, self.events = info, styles, events
        self.play_res_x, self.play_res_y = info.get('PlayResX', 0), info.get('PlayResY', 0)
        self.default_style_name = next(iter(styles.keys()), None)
        if not self.default_style_name and styles: logger.warning("Could not determine a default style.")

    def _get_style(self, style_name: str) -> Dict[str, Any]:
        if style_name in self.styles: return self.styles[style_name]
        if self.default_style_name:
            logger.warning(f"Style '{style_name}' not found. Using default '{self.default_style_name}'.")
            return self.styles[self.default_style_name]
        logger.warning(f"Style '{style_name}' not found and no default style.")
        return {}

    def _convert_timestamp(self, ass_time: str) -> str:
        try:
            parts = ass_time.split('.')
            hms_parts = parts[0].split(':')
            h, m, s = int(hms_parts[0]), int(hms_parts[1]), int(hms_parts[2])
            cs = int(parts[1]) if len(parts) > 1 else 0
            ms = cs * 10
            return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
        except (IndexError, ValueError) as e:
            logger.error(f"Invalid ASS time format: {ass_time}. Error: {e}. Returning '00:00:00.000'.")
            return "00:00:00.000"

    def _map_ass_alignment_to_vtt(self, alignment_code: Optional[str], style_margin_v: int = 0) -> Tuple[str, str, Optional[float]]:
        alignment_code = alignment_code or DEFAULT_ASS_ALIGNMENT
        vertical_anchor, text_align = ASS_ALIGNMENT_MAP.get(str(alignment_code),
                                                            ASS_ALIGNMENT_MAP[DEFAULT_ASS_ALIGNMENT])
        line_offset_val: Optional[float] = None
        line_anchor_val: str = 'start'
        
        # Calculate margin offset if PlayResY is available
        margin_offset = 0.0
        if style_margin_v > 0 and self.play_res_y > 0:
            margin_offset = (style_margin_v / self.play_res_y) * 100
        
        if vertical_anchor == 'start':
            # Top alignment - add margin from top
            line_offset_val = max(2.0, margin_offset) if margin_offset > 0 else 2.0
            line_anchor_val = 'start'
        elif vertical_anchor == 'middle':
            line_offset_val, line_anchor_val = 50.0, 'center'
        elif vertical_anchor == 'end':
            # Bottom alignment - subtract margin from bottom
            line_offset_val = 100.0 - max(10.0, margin_offset) if margin_offset > 0 else 90.0
            line_anchor_val = 'end'
        return text_align, line_anchor_val, line_offset_val

    def _process_text_and_tags(self, text: str, style: Dict[str, Any], current_event_style_name: str) -> Tuple[
        str, Dict[str, Any]]:
        vtt_text, override_settings = "", {}
        segments = re.split(r'({[^{}]*})', text)
        is_bold, is_italic, is_underline = style.get('Bold', 0) in [-1, 1], style.get('Italic', 0) in [-1,
                                                                                                       1], style.get(
            'Underline', 0) in [-1, 1]
        active_tags = set()
        if is_bold: active_tags.add('b')
        if is_italic: active_tags.add('i')
        if is_underline: active_tags.add('u')

        def apply_tags(segment_text):
            prefix, suffix = "", ""
            if 'u' in active_tags:
                prefix += "<u>"
                suffix = "</u>" + suffix
            if 'i' in active_tags:
                prefix += "<i>"
                suffix = "</i>" + suffix
            if 'b' in active_tags:
                prefix += "<b>"
                suffix = "</b>" + suffix
            return prefix + segment_text + suffix if prefix else segment_text

        for segment in segments:
            if not segment: continue
            if segment.startswith('{') and segment.endswith('}'):
                tag_block = segment[1:-1]
                tags_in_block = tag_block.split('\\')
                for tag_content in tags_in_block:
                    if not tag_content: continue
                    tag_key, tag_val_str = tag_content, ""
                    if len(tag_content) > 1 and tag_content[1:].isdigit() and not tag_content.startswith(('an', 'pos')):
                        tag_key, tag_val_str = tag_content[0], tag_content[1:]
                    elif len(tag_content) > 2 and tag_content[2:].isdigit() and tag_content.startswith('an'):
                        tag_key, tag_val_str = tag_content[:2], tag_content[2:]
                    if tag_key == 'q':
                        if tag_val_str.isdigit():
                            logger.debug(f"WrapStyle \\q{tag_val_str} detected (VTT has limited wrap control)")
                    elif tag_key == 'b':
                        b_o = not tag_val_str or int(tag_val_str) > 0
                        (active_tags.add if b_o else active_tags.discard)('b')
                        is_bold = b_o
                    elif tag_key == 'i':
                        i_o = not tag_val_str or int(tag_val_str) > 0
                        (active_tags.add if i_o else active_tags.discard)('i')
                        is_italic = i_o
                    elif tag_key == 'u':
                        u_o = not tag_val_str or int(tag_val_str) > 0
                        (active_tags.add if u_o else active_tags.discard)('u')
                        is_underline = u_o
                    elif tag_key == 'an':
                        if tag_val_str.isdigit() and 1 <= int(tag_val_str) <= 9:
                            vtt_txt_align, vtt_ln_anchor, vtt_ln_offset = self._map_ass_alignment_to_vtt(tag_val_str)
                            override_settings['align'] = vtt_txt_align
                            override_settings['line'] = f"{vtt_ln_offset}%" if vtt_ln_offset is not None else 'auto'
                            override_settings['line-align'] = vtt_ln_anchor
                            override_settings['position'] = 'auto'
                            logger.debug(
                                f"Tag \\an{tag_val_str}: Set VTT align={vtt_txt_align}, line={override_settings['line']}, line-align={vtt_ln_anchor}")
                        else:
                            logger.warning(f"Ignoring invalid alignment tag: \\{tag_content}")
                    elif tag_content.startswith('pos('):
                        match = re.match(r'pos\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)', tag_content)
                        if match and self.play_res_x > 0 and self.play_res_y > 0:
                            try:
                                x, y = float(match.group(1)), float(match.group(2))
                                pos_p, line_p = (x / self.play_res_x) * 100, (y / self.play_res_y) * 100
                                
                                # Determine position-align based on x position
                                if pos_p < 33:
                                    pos_align = 'start'
                                    text_align = 'start'
                                elif pos_p > 66:
                                    pos_align = 'end'
                                    text_align = 'end'
                                else:
                                    pos_align = 'center'
                                    text_align = 'center'
                                
                                override_settings.update(
                                    {'position': f"{pos_p:.2f}%", 'line': f"{line_p:.2f}%", 'align': text_align,
                                     'line-align': 'start', 'position-align': pos_align})
                                logger.debug(f"Tag \\{tag_content}: Set VTT position={pos_p:.2f}%, line={line_p:.2f}%, position-align={pos_align}")
                            except ValueError:
                                logger.warning(f"Ignoring invalid values in tag \\{tag_content}")
                        else:
                            logger.warning(f"Ignoring tag \\{tag_content}. Missing PlayRes or invalid format.")
                    elif tag_content == 'r':
                        base_style = self._get_style(current_event_style_name)
                        is_bold, is_italic, is_underline = base_style.get('Bold', 0) in [-1, 1], base_style.get(
                            'Italic', 0) in [-1, 1], base_style.get('Underline', 0) in [-1, 1]
                        active_tags.clear()
                        if is_bold: active_tags.add('b')
                        if is_italic: active_tags.add('i')
                        if is_underline: active_tags.add('u')
                        override_settings = {}
                        logger.debug("Applied style reset (\\r)")
                    elif tag_key in ['c', '1c']:
                        color_css = _convert_ass_color_to_css(tag_val_str if tag_val_str else tag_content[len(tag_key):])
                        if color_css:
                            logger.debug(f"Inline primary color change to {color_css} (not directly supported in VTT)")
                    elif tag_key in ['2c', '3c', '4c']:
                        logger.debug(f"Inline color tag \\{tag_content} (not supported in VTT)")
                    elif tag_key == 'q':
                        logger.debug(f"WrapStyle tag \\q{tag_val_str} (limited VTT support)")
                    elif tag_content.startswith('fscx(') or tag_content.startswith('fscy('):
                        logger.debug(f"Font scale tag \\{tag_content} (not supported in VTT)")
                    elif tag_content.startswith('move('):
                        logger.debug(f"Move animation tag \\{tag_content} (not supported in VTT)")
                    elif tag_content.startswith('org('):
                        logger.debug(f"Origin tag \\{tag_content} (not supported in VTT)")
                    elif any(tag_content.startswith(p) for p in
                             ['&H', 'alpha', '1a', '2a', '3a', '4a', 'fs', 'fn', 'bord',
                              'shad', 'be', 'blur', 'fad', 'fade', 't', 'k', 'K', 'kf', 'ko', 'fscx', 'fscy']):
                        logger.debug(f"Ignoring ASS/SSA tag (unsupported in VTT): \\{tag_content}")
                    else:
                        logger.debug(f"Ignoring unknown/unsupported ASS/SSA tag: \\{tag_content}")
            else:
                vtt_text += apply_tags(segment.replace('\\n', '\n').replace('\\N', '\n').replace('\\h', ' '))
        return re.sub(r'<(b|i|u)></\1>', '', vtt_text).strip(), override_settings

    def _parse_ass_time_for_sorting(self, ass_time_str: str) -> Tuple[int, int, int, int]:
        try:
            main, cs_str = ass_time_str.split('.')
            h, m, s = map(int, main.split(':'))
            return h, m, s, int(cs_str)
        except ValueError:
            logger.error(f"Invalid time for sorting: {ass_time_str}. Using (0,0,0,0).")
            return 0, 0, 0, 0

    def _generate_css_styles(self) -> str:
        if not self.styles: return ""
        css_rules = ["STYLE"]
        play_res_y_for_calc = self.play_res_y if self.play_res_y > 0 else 720  # Fallback PlayResY for calculations if not set

        for style_name_norm, style_props in self.styles.items():
            rules_for_style = []
            primary_color = _convert_ass_color_to_css(style_props.get('PrimaryColour'))
            if primary_color: rules_for_style.append(f"color: {primary_color};")

            # ass_fontsize_val = style_props.get('Fontsize')
            # if ass_fontsize_val is not None and self.play_res_y > 0:
            #     try:
            #         ass_fontsize = float(ass_fontsize_val)
            #         font_size_percent = round((ass_fontsize / self.play_res_y) * 100, 2)
            #         if 2 <= font_size_percent <= 10:
            #             rules_for_style.append(f"font-size: {font_size_percent}%;")
            #         else:
            #             logger.debug(f"Font size {font_size_percent}% out of range for style '{style_name_norm}'")
            #     except ValueError:
            #         logger.warning(f"Invalid Fontsize value '{ass_fontsize_val}' for style '{style_name_norm}'.")


            outline_color_css = _convert_ass_color_to_css(style_props.get('OutlineColour'))
            outline_width_val = style_props.get('Outline')
            if outline_width_val is not None:
                try:
                    outline_width = float(outline_width_val)
                    if outline_width > 0 and outline_color_css:
                        rules_for_style.append(f"-webkit-text-stroke-width: {int(outline_width)}px;")
                    rules_for_style.append(f"-webkit-text-stroke-color: {outline_color_css};")
                except ValueError:
                    logger.warning(f"Invalid Outline width value '{outline_width_val}' for style '{style_name_norm}'.")

            border_style_val = style_props.get('BorderStyle')
            border_style = 1
            if border_style_val is not None:
                try:
                    border_style = int(float(border_style_val))
                except ValueError:
                    logger.warning(f"Invalid BorderStyle value '{border_style_val}' for style '{style_name_norm}'.")
            back_color_css = _convert_ass_color_to_css(style_props.get('BackColour'))
            shadow_depth_val = style_props.get('Shadow')
            shadow_depth = 0
            if shadow_depth_val is not None:
                try:
                    shadow_depth = int(float(shadow_depth_val))
                except ValueError:
                    logger.warning(f"Invalid Shadow value '{shadow_depth_val}' for style '{style_name_norm}'.")
            shadows_list = []
            if shadow_depth > 0:
                shadow_color_source = back_color_css if border_style == 1 else (
                    outline_color_css if outline_color_css else "rgba(0,0,0,0.5)")
                if not shadow_color_source and back_color_css:
                    shadow_color_source = back_color_css
                elif not shadow_color_source:
                    shadow_color_source = "rgba(0,0,0,0.5)"
                if shadow_color_source: shadows_list.append(
                    f"{shadow_color_source} {shadow_depth}px {shadow_depth}px 0px")
            if shadows_list: rules_for_style.append(f"text-shadow: {', '.join(shadows_list)};")
            if border_style == 3 and back_color_css: rules_for_style.append(f"background-color: {back_color_css};")

            spacing_val = style_props.get('Spacing')
            if spacing_val is not None:
                try:
                    spacing_px = float(spacing_val)
                    if spacing_px != 0: rules_for_style.append(f"letter-spacing: {spacing_px}px;")
                except ValueError:
                    logger.warning(f"Invalid Spacing value '{spacing_val}' for style '{style_name_norm}'.")

            if rules_for_style: css_rules.append(f"::cue(.{style_name_norm}) {{ {' '.join(rules_for_style)} }}")

        if len(css_rules) > 1: return "\n".join(css_rules) + "\n"
        return ""

    def generate_vtt(self) -> str:
        logger.debug("Starting WebVTT content generation.")
        if not self.events:
            logger.warning("No events to convert. Returning empty VTT header.")
            return "WEBVTT\n"
        try:
            sorted_events = sorted(self.events, key=lambda e: self._parse_ass_time_for_sorting(e['Start']))
        except KeyError:
            logger.error("Events missing 'Start' time. Proceeding unsorted.")
            sorted_events = self.events
        except Exception as e:
            logger.error(f"Error sorting events: {e}. Proceeding unsorted.")
            sorted_events = self.events
        vtt_buffer = ["WEBVTT", ""]
        css_styles_block = self._generate_css_styles()
        if css_styles_block: vtt_buffer.append(css_styles_block)
        processed_events, skipped_events = 0, 0
        for i, event in enumerate(sorted_events):
            if event.get('Layer', 0) != 0:
                skipped_events += 1
                continue
            if not event.get('Text', '').strip():
                skipped_events += 1
                continue
            start_time, end_time = self._convert_timestamp(event['Start']), self._convert_timestamp(event['End'])
            if start_time >= end_time:
                skipped_events += 1
                continue
            style_name = event.get('Style') or self.default_style_name
            style_props = self._get_style(style_name) if style_name else {}
            vtt_text_payload, override_settings = self._process_text_and_tags(event['Text'], style_props,
                                                                              style_name or "")
            if not vtt_text_payload.strip():
                skipped_events += 1
                continue
            cue_settings: Dict[str, Any] = {}
            ass_style_alignment = style_props.get('Alignment')
            style_margin_v = style_props.get('MarginV', 0)
            default_vtt_text_align, default_vtt_line_anchor, default_vtt_line_offset = self._map_ass_alignment_to_vtt(
                ass_style_alignment, style_margin_v)
            cue_settings['align'] = default_vtt_text_align
            cue_settings['line'] = f"{default_vtt_line_offset}%" if default_vtt_line_offset is not None else 'auto'
            cue_settings['line-align'] = default_vtt_line_anchor
            cue_settings['position'] = 'auto'
            cue_settings['position-align'] = default_vtt_text_align
            event_margin_v = event.get('MarginV', 0)
            if event_margin_v > 0 and self.play_res_y > 0:
                if ass_style_alignment in ['1', '2', '3']:
                    line_val_margin = ((self.play_res_y - event_margin_v) / self.play_res_y) * 100
                    cue_settings[
                        'line'] = f"{line_val_margin:.2f}%"
                    cue_settings['line-align'] = 'end'
                elif ass_style_alignment in ['7', '8', '9']:
                    line_val_margin = (event_margin_v / self.play_res_y) * 100
                    cue_settings[
                        'line'] = f"{line_val_margin:.2f}%"
                    cue_settings['line-align'] = 'start'
            cue_settings.update(override_settings)
            settings_parts = []
            vtt_spec_defaults = {'align': 'center', 'line': 'auto', 'line-align': 'start', 'position': 'auto',
                                 'position-align': 'auto'}
            current_align = cue_settings.get('align')
            if current_align is not None and (
                    current_align != vtt_spec_defaults['align'] or 'align' in override_settings): settings_parts.append(
                f"align:{current_align}")
            current_line = cue_settings.get('line')
            if current_line is not None and (
                    current_line != vtt_spec_defaults['line'] or 'line' in override_settings): settings_parts.append(
                f"line:{current_line}")
            current_line_align = cue_settings.get('line-align')
            if current_line_align is not None and (current_line_align != vtt_spec_defaults[
                'line-align'] or 'line-align' in override_settings): settings_parts.append(
                f"line-align:{current_line_align}")
            current_position = cue_settings.get('position')
            if current_position is not None and (current_position != vtt_spec_defaults[
                'position'] or 'position' in override_settings): settings_parts.append(f"position:{current_position}")
            current_position_align = cue_settings.get('position-align')
            if current_position_align is not None and (current_position_align != vtt_spec_defaults[
                'position-align'] or 'position-align' in override_settings or (
                                                               current_position_align != cue_settings.get(
                                                           'align') and 'position-align' not in override_settings and cue_settings.get(
                                                           'align') is not None)): settings_parts.append(
                f"position-align:{current_position_align}")
            settings_str = " " + " ".join(settings_parts) if settings_parts else ""
            actor = event.get('Name', '').strip()
            v_tag_open = "v"
            if style_name: v_tag_open += f".{style_name}"
            if actor: v_tag_open += f" {actor.replace('>', '>').replace('<', '<')}"
            if v_tag_open != "v": vtt_text_payload = f"<{v_tag_open}>{vtt_text_payload}</v>"
            if processed_events == 0 and css_styles_block and vtt_buffer[-1] == css_styles_block: vtt_buffer.append("")
            vtt_buffer.append(f"{processed_events + 1}")
            vtt_buffer.append(f"{start_time} --> {end_time}{settings_str}")
            vtt_buffer.append(vtt_text_payload)
            vtt_buffer.append("")
            processed_events += 1
        if css_styles_block and processed_events == 0 and len(vtt_buffer) > 0 and vtt_buffer[-1] == "":
            if len(vtt_buffer) > 1 and vtt_buffer[-2] == css_styles_block.strip(): vtt_buffer.pop()
        logger.debug(f"VTT generation finished. Processed {processed_events} events, skipped {skipped_events}.")
        return "\n".join(vtt_buffer)


def convert_ass_file_to_vtt_string(input_filepath: str, input_encoding: Optional[str] = None) -> str:
    parser = AssParser()
    try:
        parser.parse_file(input_filepath, encoding=input_encoding)
    except AssParsingError:
        raise
    except Exception as e:
        logger.error(f"Unexpected error parsing {input_filepath}: {e}")
        raise AssParsingError(
            f"Unexpected error parsing {input_filepath}: {e}")
    converter = VttConverter(parser.info, parser.styles, parser.events)
    try:
        return converter.generate_vtt()
    except Exception as e:
        logger.error(f"Unexpected error generating VTT from {input_filepath}: {e}")
        raise VttConversionError(
            f"Unexpected error generating VTT: {e}")


def convert_ass_file_to_vtt_file(input_filepath: str, output_filepath: str, input_encoding: Optional[str] = None,
                                 output_encoding: str = 'utf-8'):
    vtt_content = convert_ass_file_to_vtt_string(input_filepath, input_encoding)
    try:
        with open(output_filepath, 'w', encoding=output_encoding) as f:
            f.write(vtt_content)
        logger.debug(f"Successfully saved WebVTT file: {output_filepath}")
    except IOError as e:
        logger.error(f"Could not write output file {output_filepath}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error writing file {output_filepath}: {e}")
        raise IOError(
            f"Unexpected error writing file {output_filepath}: {e}")


def convert_ass_string_to_vtt_string(ass_content: str, play_res_x: Optional[int] = None,
                                     play_res_y: Optional[int] = None) -> str:
    parser = AssParser()
    try:
        parser.parse_string(ass_content, play_res_x=play_res_x, play_res_y=play_res_y)
    except AssParsingError:
        raise
    except Exception as e:
        logger.error(f"Unexpected error parsing ASS string: {e}")
        raise AssParsingError(
            f"Unexpected error parsing ASS string: {e}")
    converter = VttConverter(parser.info, parser.styles, parser.events)
    try:
        return converter.generate_vtt()
    except Exception as e:
        logger.error(f"Unexpected error generating VTT from ASS string: {e}")
        raise VttConversionError(
            f"Unexpected error generating VTT: {e}")
