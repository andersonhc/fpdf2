"""
Handles the creation of patterns and gradients

Usage documentation at: <https://py-pdf.github.io/fpdf2/Patterns.html>
"""

import math
import struct

from abc import ABC
from typing import TYPE_CHECKING, List, Optional, Tuple, Union

from .drawing_primitives import (
    DeviceCMYK,
    DeviceGray,
    DeviceRGB,
    Transform,
    convert_to_device_color,
)
from .enums import GradientSpreadMethod
from .syntax import Name, PDFArray, PDFObject, PDFContentStream
from .util import format_number

Color = Union[DeviceRGB, DeviceGray, DeviceCMYK]

if TYPE_CHECKING:
    from .drawing import BoundingBox

TOLERANCE = 1e-9


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_tuple(
    a: Tuple[float, ...], b: Tuple[float, ...], t: float
) -> Tuple[float, ...]:
    if len(a) != len(b):
        raise ValueError("Mismatched color component counts")
    return tuple(lerp(a[i], b[i], t) for i in range(len(a)))


def pick_colorspace_and_promote(colors: List[Color]) -> Tuple[str, List[Color]]:
    kinds = {type(c).__name__ for c in colors}
    if "DeviceCMYK" in kinds and len(kinds) > 1:
        raise ValueError("Can't mix CMYK with other color spaces.")
    if kinds == {"DeviceGray", "DeviceRGB"}:
        # promote Gray -> RGB
        promoted = [
            DeviceRGB(c.g, c.g, c.g) if isinstance(c, DeviceGray) else c for c in colors
        ]
        return "DeviceRGB", promoted
    if kinds == {"DeviceGray"}:
        return "DeviceGray", colors
    if kinds == {"DeviceRGB"}:
        return "DeviceRGB", colors
    return "DeviceRGB", colors


def normalize_stops(
    stops: List[Tuple[float, Union[Color, str]]],
    coerce_to_device: bool = True,
) -> Tuple[str, List[Tuple[float, Color]]]:
    """
    Clamp/sort/merge, ensure endpoints at 0 and 1, coerce to single Device* colorspace.
    Returns (color_space_name, [(u, Device*)...]).
    """
    if not stops:
        raise ValueError("At least one stop is required")

    tmp: List[Tuple[float, Color]] = []
    for off, col in stops:
        u = 0.0 if off < 0.0 else 1.0 if off > 1.0 else float(off)
        c = (
            convert_to_device_color(col)
            if (coerce_to_device and not hasattr(col, "colors"))
            else col
        )
        tmp.append((u, c))  # type: ignore[arg-type]
    tmp.sort(key=lambda t: t[0])

    merged: List[Tuple[float, Color]] = []
    for u, c in tmp:
        if merged and abs(merged[-1][0] - u) <= TOLERANCE:
            merged[-1] = (u, c)  # last wins
        else:
            merged.append((u, c))

    if len(merged) == 1:
        u, c = merged[0]
        merged = [(0.0, c), (1.0, c)]
    if abs(merged[0][0] - 0.0) > TOLERANCE:
        merged.insert(0, (0.0, merged[0][1]))
    if abs(merged[-1][0] - 1.0) > TOLERANCE:
        merged.append((1.0, merged[-1][1]))

    # colorspace normalization
    space_name, palette = pick_colorspace_and_promote([c for _, c in merged])
    normalized = [(u, p) for (u, _), p in zip(merged, palette)]
    return space_name, normalized


def merge_near_duplicates(
    pairs: List[Tuple[float, Union[Color, str]]]
) -> List[Tuple[float, Union[Color, str]]]:
    out: List[Tuple[float, Union[Color, str]]] = []
    for u, col in pairs:
        if out and abs(out[-1][0] - u) <= TOLERANCE:
            out[-1] = (u, col)
        else:
            out.append((u, col))
    return out


def spread_map(u: float, method: GradientSpreadMethod) -> float:
    """Map u∈R -> [0,1] via PAD/REPEAT/REFLECT."""
    if method == GradientSpreadMethod.PAD:
        return 0.0 if u < 0.0 else 1.0 if u > 1.0 else u
    if method == GradientSpreadMethod.REPEAT:
        return u - math.floor(u)
    # REFLECT: triangle wave
    v = u % 2.0
    return v if v <= 1.0 else 2.0 - v


def sample_stops(stops01: List[Tuple[float, Color]], u: float) -> Tuple[float, ...]:
    """Piecewise-linear sampling in [0,1]. Assumes normalized/sorted stops incl. endpoints."""
    for i in range(1, len(stops01)):
        u1, c1 = stops01[i]
        if u <= u1 + TOLERANCE:
            u0, c0 = stops01[i - 1]
            span = max(u1 - u0, TOLERANCE)
            t = (u - u0) / span
            return lerp_tuple(c0.colors, c1.colors, t)
    return stops01[-1][1].colors


def extract_alpha_stops(
    stops01: List[Tuple[float, Color]]
) -> List[Tuple[float, float]]:
    """Return [(u, a)] with a∈[0,1]; missing alpha => 1.0."""
    out: List[Tuple[float, float]] = []
    for u, c in stops01:
        a = getattr(c, "a", None)
        out.append((u, 1.0 if a is None else float(a)))
    return out


class Pattern(PDFObject):
    """
    Represents a PDF Pattern object.

    Currently, this class supports only "shading patterns" (pattern_type 2),
    using either a linear or radial gradient. Tiling patterns (pattern_type 1)
    are not yet implemented.
    """

    def __init__(self, shading: "Gradient"):
        super().__init__()
        self.type = Name("Pattern")
        # 1 for a tiling pattern or type 2 for a shading pattern:
        self.pattern_type = 2
        self._shading = shading
        self._matrix = Transform.identity()
        # If True (default), OutputProducer will bake the page CTM into this pattern.
        # For patterns used inside Form XObjects (e.g., soft masks), set to False.
        self._apply_page_ctm = True

    @property
    def shading(self) -> str:
        return f"{self._shading.get_shading_object().id} 0 R"

    @property
    def matrix(self) -> str:
        return (
            f"[{format_number(self._matrix.a)} {format_number(self._matrix.b)} "
            f"{format_number(self._matrix.c)} {format_number(self._matrix.d)} "
            f"{format_number(self._matrix.e)} {format_number(self._matrix.f)}]"
        )

    def set_matrix(self, matrix) -> "Pattern":
        self._matrix = matrix
        return self

    def get_matrix(self) -> Transform:
        return self._matrix

    def set_apply_page_ctm(self, apply: bool) -> None:
        self._apply_page_ctm = apply

    def get_apply_page_ctm(self) -> bool:
        return self._apply_page_ctm


class Type2Function(PDFObject):
    """Transition between 2 colors"""

    def __init__(self, color_1, color_2):
        super().__init__()
        # 0: Sampled function; 2: Exponential interpolation function; 3: Stitching function; 4: PostScript calculator function
        self.function_type = 2
        self.domain = "[0 1]"
        c1 = self._get_color_components(color_1)
        c2 = self._get_color_components(color_2)
        if len(c1) != len(c2):
            raise ValueError("Type2Function endpoints must have same component count")
        self.c0 = f'[{" ".join(format_number(c) for c in c1)}]'
        self.c1 = f'[{" ".join(format_number(c) for c in c2)}]'
        self.n = 1

    @classmethod
    def _get_color_components(cls, color):
        if isinstance(color, DeviceGray):
            return [color.g]
        return color.colors


class Type2FunctionGray(PDFObject):
    """1‑channel exponential interpolation for alpha/luminance ramps."""

    def __init__(self, g0: float, g1: float):
        super().__init__()
        self.function_type = 2
        self.domain = "[0 1]"
        self.c0 = f"[{format_number(g0)}]"
        self.c1 = f"[{format_number(g1)}]"
        self.n = 1


class Type3Function(PDFObject):
    """When multiple colors are used, a type 3 function is necessary to stitch type 2 functions together
    and define the bounds between each color transition"""

    def __init__(self, functions, bounds):
        super().__init__()
        # 0: Sampled function; 2: Exponential interpolation function; 3: Stitching function; 4: PostScript calculator function
        self.function_type = 3
        self.domain = "[0 1]"
        self._functions = functions
        self.bounds = f"[{' '.join(format_number(bound) for bound in bounds)}]"
        self.encode = f"[{' '.join('0 1' for _ in functions)}]"

    @property
    def functions(self):
        return f"[{' '.join(f'{f.id} 0 R' for f in self._functions)}]"


class Shading(PDFObject):
    def __init__(
        self,
        shading_type: int,  # 2 for axial shading, 3 for radial shading
        background: Optional[Color],
        color_space: str,
        coords: List[float],
        functions: List[Union[Type2Function, Type3Function]],
        extend_before: bool,
        extend_after: bool,
    ):
        super().__init__()
        self.shading_type = shading_type
        self.background = (
            f'[{" ".join(format_number(c) for c in background.colors)}]'
            if background
            else None
        )
        self.color_space = Name(color_space)
        self.coords = coords
        self._functions = functions
        self.extend = f'[{"true" if extend_before else "false"} {"true" if extend_after else "false"}]'
        self.anti_alias = True

    @property
    def function(self) -> str:
        """Reference to the *top-level* function object for the shading dictionary."""
        return f"{self._functions[-1].id} 0 R"

    def get_functions(self):
        """All function objects used by this shading (Type2 segments + final Type3)."""
        return self._functions

    def get_shading_object(self) -> "Shading":
        """Return self, as this is already a shading object."""
        return self


class Gradient(ABC):
    def __init__(self, colors, background, extend_before, extend_after, bounds):
        self.color_space, self.colors, self._alphas = self._convert_colors(colors)
        self.background = None
        if background:
            bg = (
                convert_to_device_color(background)
                if isinstance(background, (str, DeviceGray, DeviceRGB, DeviceCMYK))
                else convert_to_device_color(*background)
            )
            # Re-map background to the chosen palette colorspace
            if self.color_space == "DeviceGray":
                if isinstance(bg, DeviceRGB):
                    bg = bg.to_gray()
                elif isinstance(bg, DeviceCMYK):
                    raise ValueError("Can't mix CMYK background with non-CMYK gradient")
            elif self.color_space == "DeviceRGB":
                if isinstance(bg, DeviceGray):
                    bg = DeviceRGB(bg.g, bg.g, bg.g)
                elif isinstance(bg, DeviceCMYK):
                    raise ValueError("Can't mix CMYK background with non-CMYK gradient")
            self.background = bg
        self.extend_before = extend_before
        self.extend_after = extend_after
        self.bounds = (
            bounds
            if bounds
            else [(i + 1) / (len(self.colors) - 1) for i in range(len(self.colors) - 2)]
        )
        if len(self.bounds) != len(self.colors) - 2:
            raise ValueError(
                "Bounds array length must be two less than the number of colors"
            )
        self.functions = self._generate_functions()
        self.pattern = Pattern(self)
        self._shading_object = None
        self._alpha_shading_object = None
        self.coords = None
        self.shading_type = 0

    @classmethod
    def _convert_colors(cls, colors) -> Tuple[str, List, List[float]]:
        """Normalize colors to a single device colorspace and capture per-stop alpha (default 1.0)."""
        if len(colors) < 2:
            raise ValueError("A gradient must have at least two colors")

        # 1) Convert everything to Device* instances
        palette = []
        spaces = set()
        alphas = []
        for color in colors:
            dc = (
                convert_to_device_color(color)
                if isinstance(color, (str, DeviceGray, DeviceRGB, DeviceCMYK))
                else convert_to_device_color(*color)
            )
            palette.append(dc)
            spaces.add(type(dc).__name__)
            a = getattr(dc, "a", None)
            alphas.append(float(a) if a is not None else 1.0)

        # 2) Disallow any CMYK mixture with others
        if "DeviceCMYK" in spaces and len(spaces) > 1:
            raise ValueError("Can't mix CMYK with other color spaces.")

        # 3) If we ended up with plain CMYK, we're done
        if spaces == {"DeviceCMYK"}:
            return "DeviceCMYK", palette, alphas

        # 4) Promote mix of Gray+RGB to RGB
        if spaces == {"DeviceGray", "DeviceRGB"}:
            promoted = []
            for c in palette:
                if isinstance(c, DeviceGray):
                    promoted.append(DeviceRGB(c.g, c.g, c.g))
                else:
                    promoted.append(c)
            return "DeviceRGB", promoted, alphas

        # 5) All Gray: stay Gray
        if spaces == {"DeviceGray"}:
            return "DeviceGray", palette, alphas

        # 6) All RGB: optionally downcast to Gray if all are achromatic
        if spaces == {"DeviceRGB"}:
            if all(c.is_achromatic() for c in palette):
                return "DeviceGray", [c.to_gray() for c in palette], alphas
            return "DeviceRGB", palette, alphas

        # Fallback: default to RGB
        return "DeviceRGB", palette, alphas

    def _generate_functions(self):
        if len(self.colors) < 2:
            raise ValueError("A gradient must have at least two colors")
        if len(self.colors) == 2:
            return [Type2Function(self.colors[0], self.colors[1])]
        number_of_colors = len(self.colors)
        functions = []
        for i in range(number_of_colors - 1):
            functions.append(Type2Function(self.colors[i], self.colors[i + 1]))
        functions.append(Type3Function(functions[:], self.bounds))
        return functions

    def get_functions(self):
        return self.functions

    def get_shading_object(self):
        if not self._shading_object:
            coords = [
                format_number(value) if isinstance(value, (int, float)) else value
                for value in self.coords
            ]
            self._shading_object = Shading(
                shading_type=self.shading_type,
                background=self.background,
                color_space=self.color_space,
                coords=PDFArray(coords),
                functions=self.functions,
                extend_before=self.extend_before,
                extend_after=self.extend_after,
            )
        return self._shading_object

    def get_pattern(self):
        return self.pattern

    def has_alpha(self) -> bool:
        """True if any stop carries alpha != 1.0."""
        return any(abs(a - 1.0) > TOLERANCE for a in self._alphas)

    def _generate_alpha_functions(self):
        """Stitched Type2 gray functions mirroring the color ramp bounds."""
        if len(self._alphas) < 2:
            raise ValueError("Alpha ramp requires at least two stops")
        if len(self._alphas) == 2:
            return [Type2FunctionGray(self._alphas[0], self._alphas[1])]
        functions = []
        for i in range(len(self._alphas) - 1):
            functions.append(Type2FunctionGray(self._alphas[i], self._alphas[i + 1]))
        functions.append(Type3Function(functions[:], self.bounds))
        return functions

    def get_alpha_shading_object(self, _=None) -> Optional["Shading"]:
        """Grayscale Shading object representing the alpha ramp (for a soft mask)."""
        if not self.has_alpha():
            return None
        if not self._alpha_shading_object:
            self._alpha_shading_object = Shading(
                shading_type=self.shading_type,
                background=None,  # mask content should be pure coverage, no bg
                color_space="DeviceGray",
                coords=PDFArray(self.coords),
                functions=self._generate_alpha_functions(),
                extend_before=False,
                extend_after=False,
            )
        return self._alpha_shading_object


class LinearGradient(Gradient):
    def __init__(
        self,
        from_x: float,
        from_y: float,
        to_x: float,
        to_y: float,
        colors: List,
        background=None,
        extend_before: bool = False,
        extend_after: bool = False,
        bounds: Optional[List[float]] = None,
    ):
        """
        A shading pattern that creates a linear (axial) gradient in a PDF.

        The gradient is defined by two points: (from_x, from_y) and (to_x, to_y),
        along which the specified colors are interpolated. Optionally, you can set
        a background color, extend the gradient beyond its start or end, and
        specify custom color stop positions via `bounds`.

        Args:
            from_x (int or float): The x-coordinate of the starting point of the gradient,
                in user space units.
            from_y (int or float): The y-coordinate of the starting point of the gradient,
                in user space units.
            to_x (int or float): The x-coordinate of the ending point of the gradient,
                in user space units.
            to_y (int or float): The y-coordinate of the ending point of the gradient,
                in user space units.
            colors (List[str or Tuple[int, int, int]]): A list of colors along which the gradient
                will be interpolated. Colors may be given as hex strings (e.g., "#FF0000") or
                (R, G, B) tuples.
            background (str or Tuple[int, int, int], optional): A background color to use
                if the gradient does not fully cover the region it is applied to.
                Defaults to None (no background).
            extend_before (bool, optional): Whether to extend the first color beyond the
                starting point (from_x, from_y). Defaults to False.
            extend_after (bool, optional): Whether to extend the last color beyond the
                ending point (to_x, to_y). Defaults to False.
            bounds (List[float], optional): An optional list of floats in the range (0, 1)
                that represent gradient stops for color transitions. The number of bounds
                should be two less than the number of colors (for multi-color gradients).
                Defaults to None, which evenly distributes color stops.
        """
        super().__init__(colors, background, extend_before, extend_after, bounds)
        self.coords = [from_x, from_y, to_x, to_y]
        self.shading_type = 2


class RadialGradient(Gradient):
    def __init__(
        self,
        start_circle_x: float,
        start_circle_y: float,
        start_circle_radius: float,
        end_circle_x: float,
        end_circle_y: float,
        end_circle_radius: float,
        colors: List,
        background=None,
        extend_before: bool = False,
        extend_after: bool = False,
        bounds: Optional[List[float]] = None,
    ):
        """
        A shading pattern that creates a radial (or circular/elliptical) gradient in a PDF.

        The gradient is defined by two circles (start and end). Colors are blended from the
        start circle to the end circle, forming a radial gradient. You can optionally set a
        background color, extend the gradient beyond its circles, and provide custom color
        stop positions via `bounds`.

        Args:
            start_circle_x (int or float): The x-coordinate of the inner circle's center,
                in user space units.
            start_circle_y (int or float): The y-coordinate of the inner circle's center,
                in user space units.
            start_circle_radius (int or float): The radius of the inner circle, in user space units.
            end_circle_x (int or float): The x-coordinate of the outer circle's center,
                in user space units.
            end_circle_y (int or float): The y-coordinate of the outer circle's center,
                in user space units.
            end_circle_radius (int or float): The radius of the outer circle, in user space units.
            colors (List[str or Tuple[int, int, int]]): A list of colors along which the gradient
                will be interpolated. Colors may be given as hex strings (e.g., "#FF0000") or
                (R, G, B) tuples.
            background (str or Tuple[int, int, int], optional): A background color to display
                if the gradient does not fully cover the region it's applied to. Defaults to None
                (no background).
            extend_before (bool, optional): Whether to extend the gradient beyond the start circle.
                Defaults to False.
            extend_after (bool, optional): Whether to extend the gradient beyond the end circle.
                Defaults to False.
            bounds (List[float], optional): An optional list of floats in the range (0, 1) that
                represent gradient stops for color transitions. The number of bounds should be one
                less than the number of colors (for multi-color gradients). Defaults to None,
                which evenly distributes color stops.
        """
        super().__init__(colors, background, extend_before, extend_after, bounds)
        self.coords = [
            start_circle_x,
            start_circle_y,
            start_circle_radius,
            end_circle_x,
            end_circle_y,
            end_circle_radius,
        ]
        self.shading_type = 3


class MeshShading(PDFContentStream):
    """
    PDF Shading type 4 (free-form Gouraud triangle mesh) with per-vertex colors.
    """

    def __init__(
        self,
        *,
        color_space: str,
        bbox: "BoundingBox",
        comp_count: int,
        triangles: List[
            Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float]]
        ],
        colors: List[Tuple[Tuple[float, ...], Tuple[float, ...], Tuple[float, ...]]],
        background: Optional["Color"] = None,
        anti_alias: bool = True,
    ):
        self.type = Name("Shading")
        self.shading_type = 4
        self.color_space = Name(color_space)
        self.background = (
            f'[{" ".join(format_number(c) for c in background.colors)}]'
            if background
            else None
        )
        self._bbox = bbox
        self._triangles = triangles
        self._triangle_colors = colors
        self.anti_alias = anti_alias
        self._comp_count = comp_count

        # Fixed bit depths (simple encoder):
        self.bits_per_coordinate = 16
        self.bits_per_component = 8
        self.bits_per_flag = 8

        # Decode = [xmin xmax ymin ymax  0 1 (per component)]
        self.decode = PDFArray(
            [
                format_number(bbox.x0),
                format_number(bbox.x1),
                format_number(bbox.y0),
                format_number(bbox.y1),
                *([0.0, 1.0] * comp_count),
            ]
        )

        super().__init__(contents=self._encode_stream_raw(), compress=True)

    # Let Pattern() accept MeshShading like other shadings
    def get_shading_object(self) -> "MeshShading":
        return self

    def _encode_stream_raw(self) -> bytes:
        xmin, xmax = self._bbox.x0, self._bbox.x1
        ymin, ymax = self._bbox.y0, self._bbox.y1
        maxc = (1 << self.bits_per_coordinate) - 1
        sx = maxc / max(xmax - xmin, TOLERANCE)
        sy = maxc / max(ymax - ymin, TOLERANCE)

        def q16(u, umin, scale):
            ui = int(round((u - umin) * scale))
            return 0 if ui < 0 else maxc if ui > maxc else ui

        def q8(v):
            iv = int(round(float(v) * 255.0))
            return 0 if iv < 0 else 255 if iv > 255 else iv

        vertex_fmt = ">BHH" + ("B" * self._comp_count)
        out = bytearray()
        for (v0, v1, v2), (c0, c1, c2) in zip(self._triangles, self._triangle_colors):
            for (x, y), comps in ((v0, c0), (v1, c1), (v2, c2)):
                component_bytes = [
                    q8(comps[i]) if i < len(comps) else 0
                    for i in range(self._comp_count)
                ]
                out += struct.pack(
                    vertex_fmt,
                    0,  # flag = 0 (no reuse)
                    q16(x, xmin, sx),  # x
                    q16(y, ymin, sy),  # y
                    *component_bytes,
                )
        return bytes(out)

    @classmethod
    def get_functions(cls):
        """Type-4 mesh shadings don't use Function objects; return empty list for output."""
        return []


class SweepGradient(PDFObject):
    """
    Conic/sweep gradient that materializes as a type-4 (mesh) Shading.
    Build is bbox-dependent, so we create the shading lazily at emit time.
    """

    __slots__ = (
        "cx",
        "cy",
        "start_angle",
        "end_angle",
        "stops",
        "spread_method",
        "segments",
        "inner_radius_factor",
        "_cached_key",
        "_shading",
        "_alpha_shading",
    )

    def __init__(
        self,
        cx: float,
        cy: float,
        start_angle: float,
        end_angle: float,
        stops: List[Tuple[float, Union[Color, str]]],
        spread_method: Union["GradientSpreadMethod", str] = GradientSpreadMethod.PAD,
        segments: Optional[int] = None,
        inner_radius_factor: float = 0.002,
    ):
        super().__init__()
        self.cx, self.cy = float(cx), float(cy)
        self.start_angle, self.end_angle = float(start_angle), float(end_angle)
        self.stops = stops
        self.spread_method = (
            GradientSpreadMethod.coerce(spread_method)
            if hasattr(GradientSpreadMethod, "coerce")
            else GradientSpreadMethod(spread_method)
        )
        self.segments = segments
        self.inner_radius_factor = inner_radius_factor
        self._cached_key = None
        self._shading = None
        self._alpha_shading = None

    def has_alpha(self) -> bool:
        # any stop carries alpha != 1
        for _, c in self.stops:
            dc = convert_to_device_color(c) if not hasattr(c, "colors") else c
            a = getattr(dc, "a", None)
            if a is not None and abs(float(a) - 1.0) > TOLERANCE:
                return True
        return False

    def get_shading_object(self, bbox: "BoundingBox") -> "MeshShading":
        key = (
            bbox.x0,
            bbox.y0,
            bbox.x1,
            bbox.y1,
            self.cx,
            self.cy,
            self.start_angle,
            self.end_angle,
            self.segments,
            self.inner_radius_factor,
            self.spread_method.value,
        )
        if self._shading is not None and self._cached_key == key:
            return self._shading
        self._cached_key = key
        self._shading = shape_sweep_gradient_as_mesh(
            self.cx,
            self.cy,
            self.start_angle,
            self.end_angle,
            self.stops,
            spread_method=self.spread_method,
            bbox=bbox,
            segments=self.segments,
            inner_radius_factor=self.inner_radius_factor,
        )
        return self._shading

    def get_alpha_shading_object(self, bbox):
        if not self.has_alpha():
            return None

        # Normalize color stops once, then extract alpha
        _, stops01 = normalize_stops(self.stops)
        alpha01 = extract_alpha_stops(stops01)
        gray_stops = [(u, DeviceGray(a)) for (u, a) in alpha01]

        key = (
            "alpha",
            bbox.x0,
            bbox.y0,
            bbox.x1,
            bbox.y1,
            self.cx,
            self.cy,
            self.start_angle,
            self.end_angle,
            self.segments,
            self.inner_radius_factor,
            self.spread_method.value,
        )

        if getattr(self, "_alpha_cached_key", None) == key:
            return self._alpha_shading

        self._alpha_shading = shape_sweep_gradient_as_mesh(
            self.cx,
            self.cy,
            self.start_angle,
            self.end_angle,
            gray_stops,
            spread_method=self.spread_method,
            bbox=bbox,
            segments=self.segments,
            inner_radius_factor=self.inner_radius_factor,
        )
        self._alpha_cached_key = key
        return self._alpha_shading


def shape_sweep_gradient_as_mesh(
    cx: float,
    cy: float,
    start_angle: float,
    end_angle: float,
    stops: List[Tuple[float, Union[Color, str]]],
    *,
    spread_method: GradientSpreadMethod,
    bbox: "BoundingBox",
    segments: Optional[int] = None,
    inner_radius_factor: float = 0.002,
) -> MeshShading:
    """
    Approximate a sweep (conic) gradient as a Type 4 mesh (triangles).
    We build a full 0..2π fan so PAD/REPEAT/REFLECT outside [0,1] are respected.
    Angles are expected in radians.
    """
    _, norm_stops = normalize_stops(stops)
    first_c = norm_stops[0][1]
    if isinstance(first_c, DeviceGray):
        color_space = "DeviceGray"
        comp_count = 1
    elif isinstance(first_c, DeviceRGB):
        color_space = "DeviceRGB"
        comp_count = 3
    else:
        color_space = "DeviceCMYK"
        comp_count = 4

    tau = 2.0 * math.pi
    delta = end_angle - start_angle
    if abs(delta) <= TOLERANCE:
        delta = tau

    if delta < 0.0:
        start_angle, end_angle = end_angle, start_angle
        norm_stops = [(1.0 - u, c) for (u, c) in norm_stops]
        norm_stops.sort(key=lambda t: t[0])
        delta = -delta

    span = delta if delta > TOLERANCE else tau
    cover_span = max(span, tau)

    if segments is None:
        base_segments = max(1024, len(norm_stops) * 96)
    else:
        base_segments = max(16, segments)
    max_angle = cover_span / float(base_segments)
    max_angle = max(min(max_angle, math.pi / 2.0), math.pi / 360.0)

    r_outer = bbox.max_distance_to_point(cx, cy)
    r_inner = max(min(bbox.width, bbox.height) * float(inner_radius_factor), TOLERANCE)

    start_mod = math.fmod(start_angle, tau)
    if start_mod < 0.0:
        start_mod += tau
    end_mod = math.fmod(start_mod + span, tau)
    if end_mod < 0.0:
        end_mod += tau
    wraps = span < tau - TOLERANCE and end_mod < start_mod
    span_covers_full_circle = span >= tau - TOLERANCE
    seam_progress = (tau - start_mod) % tau
    if seam_progress <= TOLERANCE:
        seam_progress = cover_span

    progress_candidates: List[float] = [0.0]
    tile_count = int(math.floor(cover_span / span))
    remainder = cover_span - tile_count * span
    if remainder < TOLERANCE:
        remainder = 0.0

    for tile in range(tile_count):
        base_progress = tile * span
        for u, _ in norm_stops:
            progress_candidates.append(base_progress + u * span)

    if remainder > 0.0:
        portion = remainder / span
        base_progress = tile_count * span
        for u, _ in norm_stops:
            if u > portion + TOLERANCE:
                break
            progress_candidates.append(base_progress + u * span)
        progress_candidates.append(cover_span)
    else:
        progress_candidates.append(cover_span)

    if spread_method == GradientSpreadMethod.PAD and not span_covers_full_circle:
        tail_length = max(cover_span - span, 0.0)
        if TOLERANCE < seam_progress < cover_span + TOLERANCE:
            progress_candidates.append(seam_progress)
        if (
            tail_length > TOLERANCE
            and cover_span - TOLERANCE > seam_progress > span + TOLERANCE
        ):
            seam_eps = min(
                max(span * 0.01, TOLERANCE),
                seam_progress - span - TOLERANCE,
                cover_span - seam_progress - TOLERANCE,
            )
            if seam_eps > TOLERANCE:
                progress_candidates.append(seam_progress - seam_eps)

    progress_candidates.sort()
    progress_nodes: List[float] = []
    for progress in progress_candidates:
        if progress_nodes and abs(progress - progress_nodes[-1]) <= TOLERANCE:
            progress_nodes[-1] = progress
        else:
            progress_nodes.append(progress)

    if not progress_nodes:
        progress_nodes = [0.0, cover_span]
    elif len(progress_nodes) == 1:
        progress_nodes.append(progress_nodes[0] + cover_span)

    span_plus = start_mod + span
    crosses_360 = span_plus > tau + TOLERANCE

    # pylint: disable=too-many-return-statements
    def raw_from_progress(progress: float) -> float:
        if span <= TOLERANCE:
            return 0.0

        theta = start_angle + progress

        if spread_method == GradientSpreadMethod.PAD:
            if span_covers_full_circle:
                return progress / span if span > TOLERANCE else 0.0

            if not crosses_360:
                angle_mod = math.fmod(theta, tau)
                if angle_mod < 0.0:
                    angle_mod += tau
                end_limit = start_mod + span
                if angle_mod < start_mod - TOLERANCE:
                    return 0.0
                if angle_mod <= end_limit + TOLERANCE:
                    return (angle_mod - start_mod) / span
                return 1.0

            # crosses 360°: only sample up to the seam (start -> 360°)
            visible = max(seam_progress, TOLERANCE)
            if progress <= visible + TOLERANCE:
                return progress / visible
            return 0.0

        return progress / span

    fan_line_raw: List[Tuple[float, float, Tuple[float, ...]]] = []
    for progress in progress_nodes:
        theta = start_angle + progress
        raw = raw_from_progress(progress)
        if spread_method == GradientSpreadMethod.PAD:
            mapped = 0.0 if raw <= 0.0 else 1.0 if raw >= 1.0 else raw
        else:
            mapped = spread_map(raw, spread_method)
        color = sample_stops(norm_stops, mapped)
        fan_line_raw.append((theta, raw, color))

    if not fan_line_raw:
        fan_line: List[Tuple[float, Tuple[float, ...]]] = []
    elif (
        spread_method == GradientSpreadMethod.PAD
        and not span_covers_full_circle
        and wraps
    ):
        limit_theta = start_angle + seam_progress
        pad_color = fan_line_raw[0][2]
        fan_line = []
        inserted = False
        for theta, raw, color in fan_line_raw:
            fan_line.append((theta, color))
            if not inserted and abs(theta - limit_theta) <= TOLERANCE:
                fan_line.append((theta + TOLERANCE, pad_color))
                inserted = True
        if not inserted:
            fan_line.append((limit_theta + TOLERANCE, pad_color))
    else:
        fan_line = [(theta, color) for (theta, _, color) in fan_line_raw]

    samples: List[Tuple[float, Tuple[float, ...]]] = []
    start_color_components = norm_stops[0][1].colors
    if fan_line:
        samples.append(fan_line[0])
        for idx in range(len(fan_line) - 1):
            theta0, color0 = fan_line[idx]
            theta1, color1 = fan_line[idx + 1]
            delta_theta = theta1 - theta0
            if delta_theta <= TOLERANCE:
                if samples:
                    samples[-1] = (theta1, color1)
                else:
                    samples.append((theta1, color1))
                continue
            if wraps and theta0 > limit_theta + TOLERANCE:
                color0 = start_color_components
                color1 = start_color_components
            splits = max(1, int(math.ceil(delta_theta / max_angle)))
            for s in range(1, splits + 1):
                t = s / splits
                theta = theta0 + t * delta_theta
                color = tuple(
                    color0[j] + (color1[j] - color0[j]) * t for j in range(comp_count)
                )
                samples.append((theta, color))

    if len(samples) <= 1:
        theta = fan_line[0][0] if fan_line else start_angle
        base_color = fan_line[0][1] if fan_line else norm_stops[0][1].colors
        samples = [
            (theta, base_color),
            (theta + cover_span, base_color),
        ]

    triangles: List[
        Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float]]
    ] = []
    tri_colors: List[Tuple[Tuple[float, ...], Tuple[float, ...], Tuple[float, ...]]] = (
        []
    )

    theta_prev, color_prev = samples[0]
    x_prev_inner = cx + r_inner * math.cos(theta_prev)
    y_prev_inner = cy - r_inner * math.sin(theta_prev)
    x_prev_outer = cx + r_outer * math.cos(theta_prev)
    y_prev_outer = cy - r_outer * math.sin(theta_prev)

    for theta_next, color_next in samples[1:]:
        x_next_inner = cx + r_inner * math.cos(theta_next)
        y_next_inner = cy - r_inner * math.sin(theta_next)
        x_next_outer = cx + r_outer * math.cos(theta_next)
        y_next_outer = cy - r_outer * math.sin(theta_next)

        triangles.append(
            (
                (x_prev_inner, y_prev_inner),
                (x_prev_outer, y_prev_outer),
                (x_next_outer, y_next_outer),
            )
        )
        tri_colors.append((color_prev, color_prev, color_next))

        triangles.append(
            (
                (x_prev_inner, y_prev_inner),
                (x_next_outer, y_next_outer),
                (x_next_inner, y_next_inner),
            )
        )
        tri_colors.append((color_prev, color_next, color_next))

        theta_prev, color_prev = theta_next, color_next
        x_prev_inner, y_prev_inner = x_next_inner, y_next_inner
        x_prev_outer, y_prev_outer = x_next_outer, y_next_outer

    return MeshShading(
        color_space=color_space,
        bbox=bbox,
        comp_count=comp_count,
        triangles=triangles,
        colors=tri_colors,
        background=None,
        anti_alias=True,
    )


def shape_linear_gradient(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    stops: List[Tuple[float, Union[Color, str]]],
    spread_method: Union[GradientSpreadMethod, str] = GradientSpreadMethod.PAD,
    bbox: Optional["BoundingBox"] = None,
) -> LinearGradient:
    """
    Create a linear gradient for a shape with SVG-like stops (offset in [0,1]).
    REPEAT/REFLECT are implemented by expanding stops to cover the bbox projection.
    """
    if not stops:
        raise ValueError("At least one stop is required")

    spread_method = GradientSpreadMethod.coerce(spread_method)

    _, normalized_stops = normalize_stops(stops)

    if spread_method == GradientSpreadMethod.PAD or bbox is None:
        # if the spread_method is PAD this is the final gradient
        # if the spread_method is REPEAT/REFLECT but no bbox is given, we can't expand yet
        # gradient paint will call this method again with the bbox to replace the gradient
        # at render time
        colors = [color for _, color in normalized_stops]
        bounds = [offset for offset, _ in normalized_stops[1:-1]]

        return LinearGradient(
            from_x=x1,
            from_y=y1,
            to_x=x2,
            to_y=y2,
            colors=colors,
            bounds=bounds,
            extend_before=True,
            extend_after=True,
        )

    # 5) Expand for REPEAT / REFLECT
    tmin, tmax, L = bbox.project_interval_on_axis(x1, y1, x2, y2)
    if L <= TOLERANCE:
        # Degenerate axis: synthesize flat
        c0, c1 = normalized_stops[0][1], normalized_stops[-1][1]
        return LinearGradient(
            from_x=x1,
            from_y=y1,
            to_x=x2,
            to_y=y2,
            colors=[c0, c1],
            bounds=[],
            extend_before=False,
            extend_after=False,
        )

    start_tile = math.floor(tmin / L) - 1
    end_tile = math.ceil(tmax / L) + 1

    expanded: List[Tuple[float, Union[Color, str]]] = []
    for k in range(start_tile, end_tile + 1):
        if spread_method == GradientSpreadMethod.REPEAT or (k & 1) == 0:
            # even tiles for REFLECT behave like REPEAT
            for u, col in normalized_stops:
                expanded.append((k + u, col))
        else:
            # REFLECT on odd tiles: reverse order + mirrored u
            for u, col in reversed(normalized_stops):
                expanded.append((k + (1.0 - u), col))

    # Clip a bit beyond bbox for compactness
    a = (tmin / L) - 1.0
    b = (tmax / L) + 1.0
    clipped = [
        (s, c) for (s, c) in expanded if a - TOLERANCE <= s <= b + TOLERANCE
    ] or expanded

    # Renormalize to [0..1] over synthetic span
    s0 = clipped[0][0]
    sN = clipped[-1][0]
    span = max(sN - s0, TOLERANCE)
    renorm = [((s - s0) / span, c) for (s, c) in clipped]

    # Shift/scale the coords so u=0..1 aligns to absolute positions s0..sN
    lam0 = s0  # in units of periods
    lam1 = s0 + span
    nx1 = x1 + lam0 * (x2 - x1)
    ny1 = y1 + lam0 * (y2 - y1)
    nx2 = x1 + lam1 * (x2 - x1)
    ny2 = y1 + lam1 * (y2 - y1)

    # Merge identical offsets after math
    merged = merge_near_duplicates(renorm)

    colors = [c for _, c in merged]
    bounds = [o for o, _ in merged[1:-1]]

    return LinearGradient(
        from_x=nx1,
        from_y=ny1,
        to_x=nx2,
        to_y=ny2,
        colors=colors,
        bounds=bounds,
        extend_before=False,
        extend_after=False,
    )


def shape_radial_gradient(
    cx: float,
    cy: float,
    r: float,
    stops: List[Tuple[float, Union[Color, str]]],
    fx: Optional[float] = None,
    fy: Optional[float] = None,
    fr: float = 0.0,
    spread_method: Union[GradientSpreadMethod, str] = GradientSpreadMethod.PAD,
    bbox: Optional["BoundingBox"] = None,
) -> RadialGradient:
    """
    Create a radial gradient for a shape with SVG-like stops (offset in [0,1]).
    - (cx, cy, r): outer circle
    - (fx, fy, fr): focal/inner circle (defaults to center with radius 0)
    REPEAT/REFLECT are implemented by expanding stops to cover the bbox projection.
    """
    if not stops:
        raise ValueError("At least one stop is required")

    spread_method = GradientSpreadMethod.coerce(spread_method)

    _, normalized_stops = normalize_stops(stops)

    if r < 0:
        raise ValueError("Outer radius r must be >= 0")
    if fr < 0:
        fr = 0.0
    if fx is None:
        fx = cx
    if fy is None:
        fy = cy
    # If inner radius exceeds outer, clamp
    if fr > r:
        fr = r

    if spread_method == GradientSpreadMethod.PAD or bbox is None:
        # if the spread_method is PAD this is the final gradient
        # if the spread_method is REPEAT/REFLECT but no bbox is given, we can't expand yet
        # gradient paint will call this method again with the bbox to replace the gradient
        # at render time
        colors = [color for _, color in normalized_stops]
        bounds = [offset for offset, _ in normalized_stops[1:-1]]

        return RadialGradient(
            start_circle_x=fx,
            start_circle_y=fy,
            start_circle_radius=fr,
            end_circle_x=cx,
            end_circle_y=cy,
            end_circle_radius=r,
            colors=colors,
            bounds=bounds,
            extend_before=True,
            extend_after=True,
        )

    # 5) Expand for REPEAT / REFLECT across rings
    period = max(r - fr, TOLERANCE)
    maxR = bbox.max_distance_to_point(cx, cy)
    tiles_needed = max(0, math.ceil((maxR - fr) / period)) + 1

    expanded: List[Tuple[float, Union[Color, str]]] = []
    for k in range(tiles_needed + 1):
        if spread_method == GradientSpreadMethod.REPEAT or (k & 1) == 0:
            for u, col in normalized_stops:
                expanded.append((k + u, col))
        else:
            for u, col in reversed(normalized_stops):
                expanded.append((k + (1.0 - u), col))

    s0 = expanded[0][0]
    sN = expanded[-1][0]
    span = max(sN - s0, TOLERANCE)
    renorm = [((s - s0) / span, c) for (s, c) in expanded]

    new_fr = fr
    new_r = fr + span * period

    # Merge identical offsets after math
    merged = merge_near_duplicates(renorm)

    colors = [c for _, c in merged]
    bounds = [o for o, _ in merged[1:-1]]

    return RadialGradient(
        start_circle_x=fx,
        start_circle_y=fy,
        start_circle_radius=new_fr,
        end_circle_x=cx,
        end_circle_y=cy,
        end_circle_radius=new_r,
        colors=colors,
        bounds=bounds,
        extend_before=False,
        extend_after=False,
    )
