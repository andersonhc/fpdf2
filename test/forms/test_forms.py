"""
Tests for interactive PDF form fields (AcroForms).
"""

from pathlib import Path

from fpdf import FPDF
from fpdf.forms import (
    BoxAppearance,
    CheckboxAppearance,
    CompositeAppearance,
    TextAppearance,
)

from test.conftest import assert_pdf_equal


HERE = Path(__file__).resolve().parent


def test_text_field_basic(tmp_path):
    """Test basic text field creation."""
    pdf = FPDF()
    pdf.add_page()
    pdf.text_field(
        name="test_field",
        x=10,
        y=10,
        w=60,
        h=8,
        value="initial",
        border_color=(0, 0, 0),
        background_color=(1, 1, 1),
    )
    assert_pdf_equal(pdf, HERE / "text_field_basic.pdf", tmp_path)


def test_text_field_multiline(tmp_path):
    """Test multiline text field creation."""
    pdf = FPDF()
    pdf.add_page()
    pdf.text_field(
        name="multiline_field",
        x=10,
        y=10,
        w=100,
        h=30,
        value="line1",
        multiline=True,
        border_color=(0, 0, 0),
        background_color=(1, 1, 1),
    )
    assert_pdf_equal(pdf, HERE / "text_field_multiline.pdf", tmp_path)


def test_text_field_readonly(tmp_path):
    """Test read-only text field."""
    pdf = FPDF()
    pdf.add_page()
    pdf.text_field(
        name="readonly_field",
        x=10,
        y=10,
        w=60,
        h=8,
        value="Cannot edit",
        read_only=True,
    )
    assert_pdf_equal(pdf, HERE / "text_field_readonly.pdf", tmp_path)


def test_checkbox_unchecked(tmp_path):
    """Test unchecked checkbox creation."""
    pdf = FPDF()
    pdf.add_page()
    pdf.checkbox(
        name="unchecked_box",
        x=10,
        y=10,
        size=10,
        checked=False,
    )
    assert_pdf_equal(pdf, HERE / "checkbox_unchecked.pdf", tmp_path)


def test_checkbox_checked(tmp_path):
    """Test pre-checked checkbox creation."""
    pdf = FPDF()
    pdf.add_page()
    pdf.checkbox(
        name="checked_box",
        x=10,
        y=10,
        size=10,
        checked=True,
    )
    assert_pdf_equal(pdf, HERE / "checkbox_checked.pdf", tmp_path)


def test_checkbox_readonly(tmp_path):
    """Test read-only checkbox."""
    pdf = FPDF()
    pdf.add_page()
    pdf.checkbox(
        name="readonly_box",
        x=10,
        y=10,
        size=10,
        checked=True,
        read_only=True,
    )
    assert_pdf_equal(pdf, HERE / "checkbox_readonly.pdf", tmp_path)


def test_form_with_multiple_fields(tmp_path):
    """Test form with multiple fields of different types."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "", 12)

    # Add text fields
    pdf.text(10, 20, "First Name:")
    pdf.text_field(
        name="first_name",
        x=50,
        y=15,
        w=60,
        h=8,
        value="",
        border_color=(0, 0, 0),
        background_color=(1, 1, 1),
    )

    pdf.text(10, 35, "Last Name:")
    pdf.text_field(
        name="last_name",
        x=50,
        y=30,
        w=60,
        h=8,
        value="",
        border_color=(0, 0, 0),
        background_color=(1, 1, 1),
    )

    # Add checkboxes
    pdf.checkbox(
        name="subscribe",
        x=10,
        y=50,
        size=5,
        checked=False,
    )
    pdf.text(18, 53, "Subscribe to newsletter")

    pdf.checkbox(
        name="agree_terms",
        x=10,
        y=62,
        size=5,
        checked=True,
    )
    pdf.text(18, 65, "I agree to the terms")

    assert_pdf_equal(pdf, HERE / "form_multiple_fields.pdf", tmp_path)


def test_text_field_states(tmp_path):
    """Test text fields with different appearance states."""
    pdf = FPDF()
    pdf.add_page()

    pdf.text_field(
        name="state_field_1",
        x=10,
        y=10,
        w=60,
        h=8,
        value="one",
        background_color=(1, 1, 0.9),
        border_color=(0, 0, 0),
    )
    pdf.text_field(
        name="state_field_2",
        x=10,
        y=25,
        w=60,
        h=8,
        value="two",
        background_color=(0.95, 1, 0.9),
        border_color=(0, 0, 0),
    )
    pdf.text_field(
        name="state_field_3",
        x=10,
        y=40,
        w=60,
        h=8,
        value="three",
        background_color=(0.9, 0.95, 1),
        border_color=(0, 0, 0),
    )

    assert_pdf_equal(pdf, HERE / "text_field_states.pdf", tmp_path)


def test_checkbox_emoji_appearance(tmp_path):
    """Test checkbox with emoji appearance using a color font."""
    pdf = FPDF()
    pdf.add_page()
    emoji_font = HERE.parent / "color_font" / "colrv1-NotoColorEmoji.ttf"
    pdf.add_font("NotoColorEmoji", fname=emoji_font)

    size = 12
    box = BoxAppearance(
        background_color=(1, 1, 1),
        border_color=(0, 0, 0),
        border_width=1,
    )
    checked = CompositeAppearance(
        box,
        TextAppearance(
            text="😀",
            font_name="NotoColorEmoji",
            font_size=size * 0.8,
            color_gray=0,
        ),
    )
    unchecked = CompositeAppearance(
        box,
        TextAppearance(
            text="😢",
            font_name="NotoColorEmoji",
            font_size=size * 0.8,
            color_gray=0,
        ),
    )
    rollover = CompositeAppearance(
        box,
        TextAppearance(
            text="😐",
            font_name="NotoColorEmoji",
            font_size=size * 0.8,
            color_gray=0,
        ),
    )
    appearance = CheckboxAppearance(
        off=unchecked,
        on=checked,
        rollover_off=rollover,
        rollover_on=rollover,
    )
    pdf.checkbox(
        name="emoji_box",
        x=10,
        y=10,
        size=size,
        checked=True,
        appearance=appearance,
    )
    assert_pdf_equal(pdf, HERE / "checkbox_emoji.pdf", tmp_path)
