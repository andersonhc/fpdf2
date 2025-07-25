from pathlib import Path
from test.conftest import assert_pdf_equal

import pytest

from fpdf import FPDF
from fpdf.drawing import (
    BoundingBox,
    HorizontalLine,
    Line,
    PaintedPath,
    Point,
    RelativeHorizontalLine,
    RelativeLine,
    Transform,
    VerticalLine,
    RelativeVerticalLine,
    BezierCurve,
    RelativeBezierCurve,
    QuadraticBezierCurve,
    RelativeQuadraticBezierCurve,
    Arc,
    RelativeArc,
    Rectangle,
    RoundedRectangle,
    Ellipse,
)

HERE = Path(__file__).resolve().parent


def rotate_around_center(bbox: BoundingBox) -> Transform:
    """
    Create a transformation that rotates the bounding box around its center.
    """
    center_x = (bbox.x0 + bbox.x1) / 2
    center_y = (bbox.y0 + bbox.y1) / 2
    return (
        Transform.translation(center_x, center_y)
        .rotate(45)
        .translate(-center_x + 150, -center_y)
    )


TRANSFORMS = {
    "identity": Transform.identity(),
    "scaled": Transform.scaling(2, 3),
    "rotated": rotate_around_center,
    "translated": Transform.translation(50, 100),
}


def render_path_element_with_bounding_box(
    path_element, start, transform, expected_bbox, reference_pdf_file, tmp_path
):
    """
    Render a path element and its bounding box in a PDF.
    """
    pdf = FPDF()
    pdf.add_page()

    with pdf.drawing_context() as gc:
        path = PaintedPath()
        path.move_to(start.x, start.y)
        path.add_path_element(path_element)
        path.style.stroke_color = "#000000"
        path.transform = transform
        gc.add_item(path)

        bbox, _ = path.bounding_box(start=start)

        expected_scaled_bbox = expected_bbox.transformed(transform)
        if not bbox.is_valid():
            assert not expected_scaled_bbox.is_valid()
            return
        assert bbox == expected_scaled_bbox

        bbox_path = PaintedPath()
        bbox_path.rectangle(bbox.x0, bbox.y0, bbox.x1 - bbox.x0, bbox.y1 - bbox.y0)
        bbox_path.style.stroke_color = "#FF0000"
        bbox_path.style.fill_color = None
        gc.add_item(bbox_path)

    assert_pdf_equal(pdf, reference_pdf_file, tmp_path)


@pytest.mark.parametrize(
    "test_id, shape, start, expected_bbox",
    [
        (
            "horizontal",
            Line(pt=Point(50, 20)),
            Point(10, 20),
            BoundingBox(10, 20, 50, 20),
        ),
        (
            "vertical",
            Line(pt=Point(30, 80)),
            Point(30, 10),
            BoundingBox(30, 10, 30, 80),
        ),
        (
            "diagonal",
            Line(pt=Point(100, 100)),
            Point(50, 50),
            BoundingBox(50, 50, 100, 100),
        ),
        (
            "rev-diagonal",
            Line(pt=Point(50, 50)),
            Point(100, 100),
            BoundingBox(50, 50, 100, 100),
        ),
        (
            "negative-coords",
            Line(pt=Point(5, 5)),
            Point(-10, -5),
            BoundingBox(-10, -5, 5, 5),
        ),
        ("dot", Line(pt=Point(42, 42)), Point(42, 42), BoundingBox(42, 42, 42, 42)),
        (
            "horizontal",
            RelativeLine(pt=Point(40, 0)),
            Point(10, 20),
            BoundingBox(10, 20, 50, 20),
        ),
        (
            "vertical",
            RelativeLine(pt=Point(0, 60)),
            Point(30, 10),
            BoundingBox(30, 10, 30, 70),
        ),
        (
            "diagonal",
            RelativeLine(pt=Point(100, 100)),
            Point(0, 0),
            BoundingBox(0, 0, 100, 100),
        ),
        (
            "rev-diagonal",
            RelativeLine(pt=Point(-100, -100)),
            Point(100, 100),
            BoundingBox(0, 0, 100, 100),
        ),
        (
            "negative-coords",
            RelativeLine(pt=Point(15, 10)),
            Point(-10, -5),
            BoundingBox(-10, -5, 5, 5),
        ),
        (
            "dot",
            RelativeLine(pt=Point(0, 0)),
            Point(42, 42),
            BoundingBox(42, 42, 42, 42),
        ),
        ("right", HorizontalLine(x=50), Point(10, 20), BoundingBox(10, 20, 50, 20)),
        ("left", HorizontalLine(x=20), Point(50, 15), BoundingBox(20, 15, 50, 15)),
        (
            "zero-length",
            HorizontalLine(x=42),
            Point(42, 42),
            BoundingBox(42, 42, 42, 42),
        ),
        (
            "right",
            RelativeHorizontalLine(x=40),
            Point(10, 20),
            BoundingBox(10, 20, 50, 20),
        ),
        (
            "left",
            RelativeHorizontalLine(x=-30),
            Point(20, 15),
            BoundingBox(-10, 15, 20, 15),
        ),
        (
            "zero-length",
            RelativeHorizontalLine(x=0),
            Point(42, 42),
            BoundingBox(42, 42, 42, 42),
        ),
        ("up", VerticalLine(y=80), Point(30, 10), BoundingBox(30, 10, 30, 80)),
        ("down", VerticalLine(y=20), Point(20, 50), BoundingBox(20, 20, 20, 50)),
        ("zero-length", VerticalLine(y=42), Point(42, 42), BoundingBox(42, 42, 42, 42)),
        ("up", RelativeVerticalLine(y=50), Point(30, 10), BoundingBox(30, 10, 30, 60)),
        (
            "down",
            RelativeVerticalLine(y=-30),
            Point(20, 50),
            BoundingBox(20, 20, 20, 50),
        ),
        (
            "zero-length",
            RelativeVerticalLine(y=0),
            Point(42, 42),
            BoundingBox(42, 42, 42, 42),
        ),
        (
            "horizontal-line",
            BezierCurve(c1=Point(30, 0), c2=Point(70, 0), end=Point(100, 0)),
            Point(0, 0),
            BoundingBox(0, 0, 100, 0),
        ),
        (
            "vertical-line",
            BezierCurve(c1=Point(0, 30), c2=Point(0, 70), end=Point(0, 100)),
            Point(0, 0),
            BoundingBox(0, 0, 0, 100),
        ),
        (
            "zigzag-diagonal",
            BezierCurve(c1=Point(100, 0), c2=Point(0, 100), end=Point(100, 100)),
            Point(0, 0),
            BoundingBox(0, 0, 100, 100),
        ),
        (
            "reverse-horizontal",
            BezierCurve(c1=Point(70, 100), c2=Point(30, 100), end=Point(0, 100)),
            Point(100, 100),
            BoundingBox(0, 100, 100, 100),
        ),
        (
            "extreme-control-points",
            BezierCurve(c1=Point(150, 0), c2=Point(-150, 100), end=Point(100, 100)),
            Point(0, 0),
            BoundingBox(-3.808522398518157, 0.0, 100.0, 100.0),
        ),
        (
            "diagonal-curve",
            BezierCurve(c1=Point(25, 25), c2=Point(50, 50), end=Point(75, 75)),
            Point(0, 0),
            BoundingBox(0, 0, 75, 75),
        ),
        (
            "zero-length",
            BezierCurve(c1=Point(42, 42), c2=Point(42, 42), end=Point(42, 42)),
            Point(42, 42),
            BoundingBox(42, 42, 42, 42),
        ),
        (
            "simple-diagonal",
            RelativeBezierCurve(
                c1=Point(30, 60), c2=Point(60, 90), end=Point(100, 100)
            ),
            Point(0, 0),
            BoundingBox(0, 0, 100, 100),
        ),
        (
            "reflected-turn",
            RelativeBezierCurve(
                c1=Point(20, -20), c2=Point(-30, 30), end=Point(-50, -50)
            ),
            Point(25, 25),
            BoundingBox(-25.0, -25.0, 29.63395588138013, 25.0),
        ),
        (
            "control-points-zero",
            RelativeBezierCurve(c1=Point(0, 0), c2=Point(0, 0), end=Point(50, 50)),
            Point(0, 0),
            BoundingBox(0, 0, 50, 50),
        ),
        (
            "zero-length",
            RelativeBezierCurve(c1=Point(0, 0), c2=Point(0, 0), end=Point(0, 0)),
            Point(10, 10),
            BoundingBox(10, 10, 10, 10),
        ),
        (
            "flat-horizontal",
            RelativeBezierCurve(c1=Point(50, 1), c2=Point(100, 2), end=Point(150, 1)),
            Point(0, 0),
            BoundingBox(0.0, 0.0, 150.0, 1.4142135623730951),
        ),
        (
            "flat-vertical",
            RelativeBezierCurve(c1=Point(1, 50), c2=Point(2, 100), end=Point(1, 150)),
            Point(0, 0),
            BoundingBox(0.0, 0.0, 1.4142135623730951, 150.0),
        ),
        (
            "upward",
            QuadraticBezierCurve(ctrl=Point(50, 100), end=Point(100, 0)),
            Point(0, 0),
            BoundingBox(0, 0, 100, 50),
        ),
        (
            "parabola-up",
            QuadraticBezierCurve(ctrl=Point(50, 100), end=Point(100, 0)),
            Point(0, 0),
            BoundingBox(0, 0, 100, 50),
        ),
        (
            "flat-horizontal",
            QuadraticBezierCurve(ctrl=Point(50, 0), end=Point(100, 0)),
            Point(0, 0),
            BoundingBox(0, 0, 100, 0),
        ),
        (
            "diagonal",
            QuadraticBezierCurve(ctrl=Point(50, 50), end=Point(100, 100)),
            Point(0, 0),
            BoundingBox(0, 0, 100, 100),
        ),
        (
            "sharp-down",
            QuadraticBezierCurve(ctrl=Point(25, -100), end=Point(50, 0)),
            Point(0, 0),
            BoundingBox(0, -50, 50, 0),
        ),
        (
            "zero-length",
            QuadraticBezierCurve(ctrl=Point(42, 42), end=Point(42, 42)),
            Point(42, 42),
            BoundingBox(42, 42, 42, 42),
        ),
        (
            "symmetric-upward",
            RelativeQuadraticBezierCurve(ctrl=Point(50, 100), end=Point(100, 0)),
            Point(0, 0),
            BoundingBox(0, 0, 100, 50),
        ),
        (
            "flat-horizontal",
            RelativeQuadraticBezierCurve(ctrl=Point(50, 0), end=Point(100, 0)),
            Point(0, 0),
            BoundingBox(0, 0, 100, 0),
        ),
        (
            "diagonal",
            RelativeQuadraticBezierCurve(ctrl=Point(50, 50), end=Point(100, 100)),
            Point(0, 0),
            BoundingBox(0, 0, 100, 100),
        ),
        (
            "sharp-down",
            RelativeQuadraticBezierCurve(ctrl=Point(25, -100), end=Point(50, 0)),
            Point(0, 0),
            BoundingBox(0, -50, 50, 0),
        ),
        (
            "zero-length",
            RelativeQuadraticBezierCurve(ctrl=Point(0, 0), end=Point(0, 0)),
            Point(42, 42),
            BoundingBox(42, 42, 42, 42),
        ),
        (
            "negative-offsets",
            RelativeQuadraticBezierCurve(ctrl=Point(-25, 25), end=Point(-50, -50)),
            Point(100, 100),
            BoundingBox(50, 50, 100, 106.25),
        ),
        (
            "90-degree",
            Arc(
                radii=Point(50, 50),
                rotation=0,
                large=False,
                sweep=True,
                end=Point(50, 50),
            ),
            Point(0, 0),
            BoundingBox(0, 0, 50, 50),
        ),
        (
            "180-degree",
            Arc(
                radii=Point(50, 50),
                rotation=0,
                large=True,
                sweep=False,
                end=Point(-50, 0),
            ),
            Point(50, 0),
            BoundingBox(-50, -50, 50, 0),
        ),
        (
            "rotated-ellipse",
            Arc(
                radii=Point(50, 30),
                rotation=45,
                large=False,
                sweep=True,
                end=Point(100, 0),
            ),
            Point(0, 0),
            BoundingBox(-5.405509724430832, -68.61529643011123, 99.99999989849465, 0),
        ),
        (
            "tiny-arc",
            Arc(
                radii=Point(0.1, 0.1),
                rotation=0,
                large=False,
                sweep=True,
                end=Point(0.1, 0),
            ),
            Point(0, 0),
            BoundingBox(0, -0.013397459621556158, 0.1, 0),
        ),
        (
            "negative-sweep",
            Arc(
                radii=Point(25, 40),
                rotation=0,
                large=False,
                sweep=False,
                end=Point(-40, 25),
            ),
            Point(0, 0),
            BoundingBox(
                -39.99999998902608, -8.416886842006127, 0.0, 24.999999894774596
            ),
        ),
        (
            "quarter-circle",
            RelativeArc(
                radii=Point(50, 50),
                rotation=0,
                large=False,
                sweep=True,
                end=Point(50, 50),
            ),
            Point(0, 0),
            BoundingBox(0, 0, 50, 50),
        ),
        (
            "half-circle",
            RelativeArc(
                radii=Point(50, 50),
                rotation=0,
                large=True,
                sweep=False,
                end=Point(-100, 0),
            ),
            Point(50, 0),
            BoundingBox(-50.0, -50.0, 50.0, 0.0),
        ),
        (
            "diagonal-rotated-ellipse",
            RelativeArc(
                radii=Point(50, 30),
                rotation=45,
                large=False,
                sweep=True,
                end=Point(100, 0),
            ),
            Point(0, 0),
            BoundingBox(-5.405509724430832, -68.61529643011123, 99.99999989849465, 0),
        ),
        (
            "tiny-arc",
            RelativeArc(
                radii=Point(0.1, 0.1),
                rotation=0,
                large=False,
                sweep=True,
                end=Point(0.1, 0),
            ),
            Point(0, 0),
            BoundingBox(0, -0.013397459621556158, 0.1, 0),
        ),
        (
            "negative-sweep",
            RelativeArc(
                radii=Point(25, 40),
                rotation=0,
                large=False,
                sweep=False,
                end=Point(-40, 25),
            ),
            Point(0, 0),
            BoundingBox(-39.99999998902608, -8.416886842006127, 0, 24.999999894774596),
        ),
        (
            "simple-rectangle",
            Rectangle(org=Point(10, 20), size=Point(80, 60)),
            None,
            BoundingBox(10, 20, 90, 80),
        ),
        (
            "square",
            Rectangle(org=Point(0, 0), size=Point(100, 100)),
            None,
            BoundingBox(0, 0, 100, 100),
        ),
        (
            "negative-origin",
            Rectangle(org=Point(-50, -25), size=Point(30, 45)),
            None,
            BoundingBox(-50, -25, -20, 20),
        ),
        (
            "zero-size",
            Rectangle(org=Point(42, 42), size=Point(0, 0)),
            None,
            BoundingBox(42, 42, 42, 42),
        ),
        (
            "thin-horizontal",
            Rectangle(org=Point(5, 10), size=Point(100, 0.1)),
            None,
            BoundingBox(5, 10, 105, 10.1),
        ),
        (
            "thin-vertical",
            Rectangle(org=Point(5, 10), size=Point(0.1, 100)),
            None,
            BoundingBox(5, 10, 5.1, 110),
        ),
        (
            "simple",
            RoundedRectangle(
                org=Point(0, 0), size=Point(100, 50), corner_radii=Point(10, 10)
            ),
            None,
            BoundingBox(0, 0, 100, 50),
        ),
        (
            "no-rounding",
            RoundedRectangle(
                org=Point(10, 20), size=Point(30, 40), corner_radii=Point(0, 0)
            ),
            None,
            BoundingBox(10, 20, 40, 60),
        ),
        (
            "negative-size",
            RoundedRectangle(
                org=Point(50, 50), size=Point(-30, -20), corner_radii=Point(5, 5)
            ),
            None,
            BoundingBox(20, 30, 50, 50),
        ),
        (
            "corner-radius-larger-than-size",
            RoundedRectangle(
                org=Point(0, 0), size=Point(20, 10), corner_radii=Point(30, 30)
            ),
            None,
            BoundingBox(0, 0, 20, 10),
        ),
        (
            "zero-width",
            RoundedRectangle(
                org=Point(0, 0), size=Point(0, 50), corner_radii=Point(10, 10)
            ),
            None,
            BoundingBox(0, 0, 0, 50),
        ),
        (
            "zero-size",
            RoundedRectangle(
                org=Point(0, 0), size=Point(80, 0), corner_radii=Point(10, 10)
            ),
            None,
            BoundingBox(0, 0, 80, 0),
        ),
        (
            "negative-size-zero-radius",
            RoundedRectangle(
                org=Point(30, 30), size=Point(-10, -10), corner_radii=Point(0, 0)
            ),
            None,
            BoundingBox(20, 20, 30, 30),
        ),
        (
            "circle-origin",
            Ellipse(radii=Point(10, 10), center=Point(0, 0)),
            None,
            BoundingBox(-10, -10, 10, 10),
        ),
        (
            "circle-offset",
            Ellipse(radii=Point(10, 10), center=Point(100, 200)),
            None,
            BoundingBox(90, 190, 110, 210),
        ),
        (
            "ellipse-wide",
            Ellipse(radii=Point(25, 10), center=Point(50, 75)),
            None,
            BoundingBox(25, 65, 75, 85),
        ),
        (
            "ellipse-zero-width",
            Ellipse(radii=Point(0, 20), center=Point(50, 50)),
            None,
            BoundingBox.empty(),
        ),
        (
            "ellipse-zero-height",
            Ellipse(radii=Point(15, 0), center=Point(0, 0)),
            None,
            BoundingBox.empty(),
        ),
    ],
)
def test_shape_bounding_box(test_id, shape, start, expected_bbox, tmp_path):
    bbox, _ = shape.bounding_box(start)
    if not bbox.is_valid():
        assert not expected_bbox.is_valid()
    else:
        assert bbox == expected_bbox

    for name, tf in TRANSFORMS.items():
        transform = tf(expected_bbox) if callable(tf) else tf
        render_path_element_with_bounding_box(
            shape,
            start=start or Point(0, 0),  # Use Point(0, 0) if start is None
            transform=transform,
            expected_bbox=expected_bbox,
            reference_pdf_file=HERE
            / f"generated_pdf/bounding_box_{shape.__class__.__name__.lower()}_{test_id}_{name}.pdf",
            tmp_path=tmp_path,
        )
