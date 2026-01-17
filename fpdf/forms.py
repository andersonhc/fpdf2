"""
Interactive PDF form fields (AcroForms).

The contents of this module are internal to fpdf2, and not part of the public API.
They may change at any time without prior warning or any deprecation period,
in non-backward-compatible ways.
"""

from .annotations import PDFAnnotation
from .enums import FieldFlag
from .syntax import Name, PDFArray, PDFContentStream, PDFString


class PDFFormXObject(PDFContentStream):
    """A Form XObject used for appearance streams of form fields."""

    def __init__(
        self, commands: str, width: float, height: float, resources: str = None
    ):
        if isinstance(commands, str):
            commands = commands.encode("latin-1")
        super().__init__(contents=commands, compress=False)
        self.type = Name("XObject")
        self.subtype = Name("Form")
        self.b_box = PDFArray([0, 0, round(width, 2), round(height, 2)])
        self.form_type = 1
        self._resources_str = resources
        self.resource_font_ids = None

    @property
    def resources(self):
        return self._resources_str

    def set_resource_font_ids(self, font_ids):
        self.resource_font_ids = set(font_ids) if font_ids else None


class Appearance:
    """Base class for appearance templates that render to Form XObjects."""

    def _build_commands(self, resource_catalog, width: float, height: float):
        raise NotImplementedError("Subclasses must implement _build_commands")

    def build_commands(self, resource_catalog, width: float, height: float):
        return self._build_commands(resource_catalog, width, height)

    def render(self, resource_catalog, width: float, height: float):
        commands, font_ids = self.build_commands(resource_catalog, width, height)
        content = "\n".join(commands)
        xobj = PDFFormXObject(content, width, height)
        if font_ids:
            xobj.set_resource_font_ids(font_ids)
        if resource_catalog:
            resource_catalog.register_form_xobject_resources(xobj)
        return xobj

    def default_text_appearance(self):  # pylint: disable=no-self-use
        return None


class BoxAppearance(Appearance):
    """Draws a background and border box."""

    def __init__(self, background_color, border_color, border_width: float = 1):
        self._background_color = background_color
        self._border_color = border_color
        self._border_width = border_width

    def _build_commands(self, resource_catalog, width: float, height: float):
        commands = ["q"]
        if self._background_color:
            r, g, b = self._background_color
            commands.append(f"{r:.3f} {g:.3f} {b:.3f} rg")
            commands.append(f"0 0 {width:.2f} {height:.2f} re")
            commands.append("f")

        if self._border_color:
            r, g, b = self._border_color
            commands.append(f"{r:.3f} {g:.3f} {b:.3f} RG")
            commands.append(f"{self._border_width:.2f} w")
            inset = self._border_width / 2
            commands.append(
                f"{inset:.2f} {inset:.2f} {width - self._border_width:.2f} {height - self._border_width:.2f} re"
            )
            commands.append("S")

        commands.append("Q")
        return commands, set()


class TextAppearance(Appearance):
    """Draws a single text glyph or string centered in the box."""

    def __init__(
        self,
        text: str,
        font_name: str,
        font_size: float,
        color_gray: float = 0,
        x_offset: float = 0,
        y_offset: float = 0,
        x: float = None,
        y: float = None,
    ):
        self.text = text
        self.font_name = font_name
        self.font_size = font_size
        self.color_gray = color_gray
        self._x_offset = x_offset
        self._y_offset = y_offset
        self._x = x
        self._y = y

    def _build_commands(self, resource_catalog, width: float, height: float):
        font = None
        font_name = self.font_name
        if resource_catalog:
            font = resource_catalog.get_font_from_family(font_name)
            resource_catalog.register_form_font(font.i)
            font_name = f"F{font.i}"
            font.get_text_width(self.text, self.font_size, None)

        x = self._x if self._x is not None else (width - self.font_size) / 2
        y = self._y if self._y is not None else (height - self.font_size) / 2
        x += self._x_offset
        y += self._y_offset

        if font:
            text_cmd = font.encode_text(self.text)
        else:
            escaped = (
                self.text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            )
            text_cmd = f"({escaped}) Tj"

        commands = [
            "q",
            "BT",
            f"/{font_name} {self.font_size:.2f} Tf",
            f"{self.color_gray:.2f} g",
            f"{x:.2f} {y:.2f} Td",
            text_cmd,
            "ET",
            "Q",
        ]
        font_ids = {font.i} if font else set()
        return commands, font_ids

    def default_text_appearance(self):
        return self


class CompositeAppearance(Appearance):
    """Combines multiple appearance parts into a single Form XObject."""

    def __init__(self, *parts: Appearance):
        self._parts = parts

    def _build_commands(self, resource_catalog, width: float, height: float):
        commands = []
        font_ids = set()
        for part in self._parts:
            part_commands, part_fonts = part.build_commands(
                resource_catalog, width, height
            )
            commands.extend(part_commands)
            font_ids.update(part_fonts)
        return commands, font_ids

    def default_text_appearance(self):
        for part in self._parts:
            text_appearance = part.default_text_appearance()
            if text_appearance:
                return text_appearance
        return None


class CheckboxAppearance:
    """Holds per-state appearances for a checkbox widget."""

    def __init__(
        self,
        off: Appearance,
        on: Appearance,
        rollover_off: Appearance = None,
        rollover_on: Appearance = None,
    ):
        self.off = off
        self.on = on
        self.rollover_off = rollover_off
        self.rollover_on = rollover_on

    def render(self, resource_catalog, size: float):
        off_xobj = self.off.render(resource_catalog, size, size)
        on_xobj = self.on.render(resource_catalog, size, size)
        rollover_off = (
            self.rollover_off.render(resource_catalog, size, size)
            if self.rollover_off
            else off_xobj
        )
        rollover_on = (
            self.rollover_on.render(resource_catalog, size, size)
            if self.rollover_on
            else on_xobj
        )
        return off_xobj, on_xobj, rollover_off, rollover_on

    def default_text_appearance(self):
        return self.on.default_text_appearance() or self.off.default_text_appearance()


class FormField(PDFAnnotation):
    """Base class for interactive form fields."""

    def __init__(
        self,
        field_type: str,
        field_name: str,
        x: float,
        y: float,
        width: float,
        height: float,
        value=None,
        default_value=None,
        field_flags: int = 0,
        resource_catalog=None,
        **kwargs,
    ):
        super().__init__(
            subtype="Widget",
            x=x,
            y=y,
            width=width,
            height=height,
            field_type=field_type,
            value=value,
            **kwargs,
        )
        self.t = PDFString(field_name, encrypt=True)
        self.d_v = default_value
        self.f_f = field_flags if field_flags else None
        self._width = width
        self._height = height
        self._resource_catalog = resource_catalog
        self._appearance_normal = None
        self._appearance_dict = None

    def _generate_appearance(self, font_name: str = "Helvetica", font_size: float = 12):
        """Generate the appearance stream for this field. Must be overridden by subclasses."""
        raise NotImplementedError("Subclasses must implement _generate_appearance")

    def generate_appearance(self, font_name: str = "Helvetica", font_size: float = 12):
        return self._generate_appearance(font_name, font_size)

    @property
    def a_p(self):
        """Return the appearance dictionary (/AP) for serialization."""
        if self._appearance_dict:
            return self._appearance_dict
        if self._appearance_normal:
            return f"<</N {self._appearance_normal.ref}>>"
        return None


class TextField(FormField):
    """An interactive text input field."""

    def __init__(
        self,
        field_name: str,
        x: float,
        y: float,
        width: float,
        height: float,
        value: str = "",
        font_size: float = 12,
        font_color_gray: float = 0,
        background_color: tuple = None,
        border_color: tuple = None,
        border_width: float = 1,
        max_length: int = None,
        multiline: bool = False,
        password: bool = False,
        read_only: bool = False,
        required: bool = False,
        resource_catalog=None,
        **kwargs,
    ):
        field_flags = 0
        if multiline:
            field_flags |= FieldFlag.MULTILINE
        if password:
            field_flags |= FieldFlag.PASSWORD
        if read_only:
            field_flags |= FieldFlag.READ_ONLY
        if required:
            field_flags |= FieldFlag.REQUIRED

        super().__init__(
            field_type="Tx",
            field_name=field_name,
            x=x,
            y=y,
            width=width,
            height=height,
            value=PDFString(value, encrypt=True) if value else None,
            default_value=PDFString(value, encrypt=True) if value else None,
            field_flags=field_flags,
            border_width=border_width,
            resource_catalog=resource_catalog,
            **kwargs,
        )

        self._font_size = font_size
        self._font_color_gray = font_color_gray
        self._background_color = background_color
        self._border_color = border_color
        self._multiline = multiline
        self._value_str = value or ""
        self.max_len = max_length
        # Default Appearance (/DA): PDF content stream fragment specifying font and color.
        # Format: "/FontName FontSize Tf GrayLevel g" (e.g., "/Helvetica 12 Tf 0 g")
        if self._resource_catalog:
            font = self._resource_catalog.get_font_from_family("Helvetica")
            self._resource_catalog.register_form_font(font.i)
            self.d_a = f"(/F{font.i} {font_size:.2f} Tf {font_color_gray:.2f} g)"
        else:
            self.d_a = f"(/Helvetica {font_size:.2f} Tf {font_color_gray:.2f} g)"

    def _generate_appearance(
        self, font_name: str = "Helvetica", font_size: float = None
    ):
        """Generate the appearance stream XObject for this text field."""
        if font_size is None:
            font_size = self._font_size
        font_id = None
        if self._resource_catalog:
            font = self._resource_catalog.get_font_from_family(font_name)
            font_name = f"F{font.i}"
            font_id = font.i

        self._appearance_normal = self._render_text_appearance(
            font_name,
            font_size,
            font_id,
            self._background_color,
        )
        return self._appearance_normal

    def _render_text_appearance(
        self,
        font_name: str,
        font_size: float,
        font_id: int,
        background_color: tuple,
    ) -> PDFFormXObject:
        width = self._width
        height = self._height
        value = self._value_str

        commands = []
        commands.append("/Tx BMC")
        commands.append("q")

        if background_color:
            r, g, b = background_color
            commands.append(f"{r:.3f} {g:.3f} {b:.3f} rg")
            commands.append(f"0 0 {width:.2f} {height:.2f} re")
            commands.append("f")

        if self._border_color:
            r, g, b = self._border_color
            commands.append(f"{r:.3f} {g:.3f} {b:.3f} RG")
            commands.append("1 w")
            commands.append(f"0.5 0.5 {width - 1:.2f} {height - 1:.2f} re")
            commands.append("S")

        if value:
            commands.append(f"2 2 {width - 4:.2f} {height - 4:.2f} re W n")
            commands.append("BT")
            commands.append(f"/{font_name} {font_size:.2f} Tf")
            commands.append(f"{self._font_color_gray:.2f} g")

            text_y = (height - font_size) / 2 + 2
            if self._multiline:
                text_y = height - font_size - 2
            commands.append(f"2 {text_y:.2f} Td")

            escaped_value = (
                value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            )
            commands.append(f"({escaped_value}) Tj")
            commands.append("ET")

        commands.append("Q")
        commands.append("EMC")

        content = "\n".join(commands)
        xobj = PDFFormXObject(content, width, height)
        if font_id is not None:
            xobj.set_resource_font_ids({font_id})
            self._resource_catalog.register_form_xobject_resources(xobj)
        elif self._resource_catalog:
            self._resource_catalog.register_form_xobject_resources(xobj)
        return xobj


class Checkbox(FormField):
    """An interactive checkbox field."""

    CHECK_CHAR = "4"

    def __init__(
        self,
        field_name: str,
        x: float,
        y: float,
        size: float = 12,
        checked: bool = False,
        background_color: tuple = (1, 1, 1),
        border_color: tuple = (0, 0, 0),
        check_color_gray: float = 0,
        border_width: float = 1,
        read_only: bool = False,
        required: bool = False,
        appearance: CheckboxAppearance = None,
        resource_catalog=None,
        **kwargs,
    ):
        field_flags = 0
        if read_only:
            field_flags |= FieldFlag.READ_ONLY
        if required:
            field_flags |= FieldFlag.REQUIRED

        value = Name("Yes") if checked else Name("Off")

        super().__init__(
            field_type="Btn",
            field_name=field_name,
            x=x,
            y=y,
            width=size,
            height=size,
            value=value,
            default_value=value,
            field_flags=field_flags,
            border_width=border_width,
            resource_catalog=resource_catalog,
            **kwargs,
        )

        self._size = size
        self._checked = checked
        self._background_color = background_color
        self._border_color = border_color
        self._border_width = border_width
        self._check_color_gray = check_color_gray
        self._appearance_spec = appearance or self._default_appearance()
        self._appearance_rollover_off = None
        self._appearance_rollover_yes = None
        self._set_default_appearance()
        self.a_s = Name("Yes") if checked else Name("Off")

    def _default_appearance(self):
        box = BoxAppearance(
            background_color=self._background_color,
            border_color=self._border_color,
            border_width=self._border_width,
        )
        check = TextAppearance(
            text=self.CHECK_CHAR,
            font_name="ZapfDingbats",
            font_size=self._size * 0.8,
            color_gray=self._check_color_gray,
            y_offset=1,
        )
        return CheckboxAppearance(
            off=box,
            on=CompositeAppearance(box, check),
        )

    def _set_default_appearance(self):
        text_appearance = self._appearance_spec.default_text_appearance()
        if not text_appearance:
            text_appearance = TextAppearance(
                text=self.CHECK_CHAR,
                font_name="ZapfDingbats",
                font_size=self._size * 0.8,
                color_gray=self._check_color_gray,
            )
        font_name = text_appearance.font_name
        font_size = text_appearance.font_size
        color_gray = text_appearance.color_gray
        if self._resource_catalog:
            font = self._resource_catalog.get_font_from_family(font_name)
            self._resource_catalog.register_form_font(font.i)
            self.d_a = f"(/F{font.i} {font_size:.2f} Tf {color_gray:.2f} g)"
        else:
            self.d_a = f"(/%s {font_size:.2f} Tf {color_gray:.2f} g)" % font_name

    def _generate_appearance(
        self, font_name: str = "ZapfDingbats", font_size: float = None
    ):
        """Generate appearance streams for checked and unchecked states."""
        size = self._size
        off_xobj, yes_xobj, rollover_off, rollover_yes = self._appearance_spec.render(
            self._resource_catalog, size
        )
        self._appearance_off = off_xobj
        self._appearance_yes = yes_xobj
        self._appearance_rollover_off = rollover_off
        self._appearance_rollover_yes = rollover_yes
        return off_xobj, yes_xobj

    @property
    def a_p(self):
        """Return the appearance dictionary for checkbox."""
        if self._appearance_off and self._appearance_yes:
            parts = [
                f"/N <</Off {self._appearance_off.ref} /Yes {self._appearance_yes.ref}>>"
            ]
            if self._appearance_rollover_off and self._appearance_rollover_yes:
                parts.append(
                    f"/R <</Off {self._appearance_rollover_off.ref} /Yes {self._appearance_rollover_yes.ref}>>"
                )
            return f"<<{' '.join(parts)}>>"
        return None
