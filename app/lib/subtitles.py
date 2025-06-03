import zipfile
import os
import tempfile
import chardet
from pysubs2 import SSAFile, load, FormatAutodetectionError
import re
import logging
from ..lib.ass_to_vtt import convert_ass_file_to_vtt_string, convert_ass_string_to_vtt_string, AssParsingError, VttConversionError

logger = logging.getLogger(__name__)


def detect_encoding(raw_data):
    """Detect the encoding of subtitle data."""
    result = chardet.detect(raw_data)
    encoding = result['encoding']
    confidence = result['confidence']
    
    logger.info(f"Detected encoding: {encoding} with confidence: {confidence}")
    
    # If confidence is low, try common encodings
    if confidence < 0.7:
        common_encodings = ['utf-8', 'utf-8-sig', 'cp1250', 'cp1252', 'latin1', 'iso-8859-1', 'iso-8859-2']
        for enc in common_encodings:
            try:
                raw_data.decode(enc)
                logger.info(f"Successfully decoded with {enc}")
                return enc
            except UnicodeDecodeError:
                continue
    
    return encoding or 'utf-8'


def convert_to_vtt(file_data, file_extension, encoding=None, fps=None):
    """
    Convert subtitle file to VTT format.
    
    Args:
        file_data: Raw binary data of the subtitle file
        file_extension: File extension (e.g. '.srt', '.ass')
        encoding: Optional encoding to use (None for auto-detection)
        fps: Optional frames per second for frame-based formats
    
    Returns:
        String containing WebVTT content
    """

    if encoding is None:
        encoding = detect_encoding(file_data)
    
    logger.info(f"Converting subtitle with encoding: {encoding}, FPS: {fps}")
    
    # Create a temporary file to work with
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
        temp_file.write(file_data)
        temp_file_path = temp_file.name
    
    try:
        if file_extension.lower() in ('ass', 'ssa'):
            # Use our custom ASS/SSA to VTT converter
            try:
                vtt_content = convert_ass_file_to_vtt_string(temp_file_path, input_encoding=encoding)
                return vtt_content
            except (AssParsingError, VttConversionError) as e:
                logger.error(f"Error converting ASS/SSA to VTT: {e}")
                # Fall back to pysubs2 if our converter fails
                subs = load(temp_file_path, encoding=encoding)
                return subs.to_string('vtt')
        else:
            # For SRT, SUB, etc. use pysubs2
            try:
                subs = load(temp_file_path, encoding=encoding, fps=fps)
            except FormatAutodetectionError:
                subs = load(temp_file_path, encoding=encoding, fps=fps, format_=file_extension)
            return subs.to_string('vtt')
    except Exception as e:
        logger.error(f"Error converting subtitle file: {e}")
        raise
    finally:
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)