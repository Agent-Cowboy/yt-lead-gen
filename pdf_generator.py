"""
pdf_generator.py — FPDF2-based PDF generation from screenshot images.
Creates a multi-page PDF where each page has the channel name as a header
and the screenshot below, scaled to fit while maintaining aspect ratio.
"""

import os
import logging
from fpdf import FPDF
from PIL import Image

logger = logging.getLogger(__name__)

# PDF page dimensions (A4 landscape in mm)
PAGE_WIDTH_MM = 297
PAGE_HEIGHT_MM = 210
MARGIN_MM = 5
HEADER_HEIGHT_MM = 12  # space for the channel name


class LeadGenPDF(FPDF):
    """Custom PDF class with channel name headers."""

    def __init__(self):
        super().__init__(orientation='L', unit='mm', format='A4')
        self.set_auto_page_break(auto=False)


def generate_pdf(entries: list[dict], output_path: str) -> str:
    """
    Generate a PDF from a list of screenshot entries.
    Each entry gets its own page with the channel name header.

    Args:
        entries: List of dicts with 'path' (image file path) and
                 'channel_name' (display name). Also accepts plain
                 string paths for backward compatibility.
        output_path: Output file path for the generated PDF

    Returns:
        The output_path of the generated PDF

    Raises:
        ValueError: If no valid images provided
    """
    if not entries:
        raise ValueError("No images provided for PDF generation")

    # Normalize entries: accept both dicts and plain strings
    normalized = []
    for entry in entries:
        if isinstance(entry, dict):
            path = entry.get('path', '')
            name = entry.get('channel_name', 'Unknown Channel')
        else:
            path = str(entry)
            name = 'Unknown Channel'

        if os.path.exists(path):
            normalized.append({'path': path, 'channel_name': name})

    if not normalized:
        raise ValueError("No valid image files found")

    logger.info(f"Generating PDF with {len(normalized)} screenshots")

    pdf = LeadGenPDF()

    usable_width = PAGE_WIDTH_MM - (2 * MARGIN_MM)
    usable_image_height = PAGE_HEIGHT_MM - (2 * MARGIN_MM) - HEADER_HEIGHT_MM

    for entry in normalized:
        img_path = entry['path']
        channel_name = entry['channel_name']

        try:
            # Get image dimensions for aspect ratio
            with Image.open(img_path) as img:
                img_width, img_height = img.size

            # Calculate scaling to fit within usable area
            width_ratio = usable_width / img_width
            height_ratio = usable_image_height / img_height
            scale = min(width_ratio, height_ratio)

            display_width = img_width * scale
            display_height = img_height * scale

            # Center the image horizontally
            x_offset = MARGIN_MM + (usable_width - display_width) / 2
            y_offset = MARGIN_MM + HEADER_HEIGHT_MM

            pdf.add_page()

            # Draw channel name header
            pdf.set_font('Helvetica', 'B', 14)
            pdf.set_text_color(50, 50, 50)
            pdf.set_xy(MARGIN_MM, MARGIN_MM)
            pdf.cell(
                w=usable_width,
                h=HEADER_HEIGHT_MM,
                text=channel_name,
                align='L',
                new_x='LMARGIN',
                new_y='NEXT',
            )

            # Draw a thin separator line
            line_y = MARGIN_MM + HEADER_HEIGHT_MM - 1
            pdf.set_draw_color(200, 200, 200)
            pdf.set_line_width(0.3)
            pdf.line(MARGIN_MM, line_y, PAGE_WIDTH_MM - MARGIN_MM, line_y)

            # Place the screenshot image
            pdf.image(
                img_path,
                x=x_offset,
                y=y_offset,
                w=display_width,
                h=display_height,
            )

            logger.info(f"Added page: {channel_name}")

        except Exception as e:
            logger.error(f"Failed to add image {img_path}: {str(e)}")
            continue

    if pdf.page == 0:
        raise ValueError("Failed to add any images to the PDF")

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    pdf.output(output_path)
    logger.info(f"PDF generated: {output_path} ({pdf.page} pages)")

    return output_path
