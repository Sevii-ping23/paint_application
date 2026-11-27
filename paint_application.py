"""
Paint'Ered - a desktop paint application built with Tkinter and Pillow.

Required features (from the weekly task):
    1. Bigger brush range ........ slider goes from 1 to 100
    2. Undo button ............... removes the latest stroke or shape
    3. Filled shapes ............. "Fill shapes" switch for rectangle/oval/etc.
    4. Extra shape tools ......... Triangle, Diamond, Hexagon and Star
    5. Confirm before clearing ... Yes / No dialog
    6. Quick colors .............. six one-click colors

Extra features:
    Redo, Fill bucket, Eyedropper, Spray can, Shift-to-constrain shapes,
    brush-size ring that follows the mouse, recent colors, status bar
    with live coordinates, and keyboard shortcuts.

Design idea: the drawing is stored in a Pillow image (the "source of truth").
The Tkinter canvas only shows that image, plus temporary previews while the
mouse is being dragged. Because the preview and the saved image use the
SAME geometry, what you see is exactly what gets saved.
"""

import math
import random
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageTk

# ----------------------------------------------------------------------------
# 1. PALETTE AND FONT  (change these to restyle the whole app)
# ----------------------------------------------------------------------------
BG = "#17142B"          # window background (deep indigo)
PANEL = "#221E3D"       # side panel and header
CARD = "#2E2952"        # buttons
HOVER = "#41397A"       # button while the mouse is over it
ACCENT = "#FF6B9D"      # active tool / highlights (pink)
SKY_BLUE = "#4FC3F7"    # the apostrophe in the app name
ACCENT_2 = "#2DD4BF"    # small secondary highlights (teal)
TEXT = "#F1EEFF"        # main text
MUTED = "#9A94C7"       # small labels

FONT_FAMILIES = ("Segoe UI", "SF Pro Text", "Helvetica Neue", "Helvetica",
                 "DejaVu Sans", "Arial")

QUICK_COLORS = [          # requirement 6: six one-click colors
    ("Black", "#000000"),
    ("Red", "#E53935"),
    ("Blue", "#1E5BFF"),
    ("Green", "#2E9E4F"),
    ("Yellow", "#FFD600"),
    ("Purple", "#8E24AA"),
]

# ----------------------------------------------------------------------------
# 2. CANVAS SETTINGS
# ----------------------------------------------------------------------------
CANVAS_WIDTH = 900
CANVAS_HEIGHT = 550
MAX_UNDO = 40           # how many steps of history to keep
MAX_RECENT = 8          # how many recent colors to remember

SHAPE_TOOLS = ("line", "rectangle", "oval", "triangle", "diamond", "hexagon",
               "star")
FILLABLE = SHAPE_TOOLS[1:]          # every shape except the line
DEFAULT_HINT = ("Shift = perfect squares/circles   [ ] = brush size   "
                "Ctrl+Z / Ctrl+Y = undo / redo")

# ----------------------------------------------------------------------------
# 3. PROGRAM STATE (global variables, like in the lesson)
# ----------------------------------------------------------------------------
root = None
canvas = None
image = None            # Pillow image that holds the real drawing
draw = None             # Pillow drawing helper for `image`
canvas_image = None     # Tk copy of `image` (must be kept so it is not deleted)
image_item = None       # id of the picture item on the canvas

current_color = "#000000"
brush_size = 5
tool = "brush"
fill_shapes = None      # tk.BooleanVar, created in main()

start_x = start_y = None
last_x = last_y = None
preview_item = None
ring_item = None
before_snapshot = None  # copy of the image taken when a stroke starts
is_drawing = False

undo_stack = []
redo_stack = []
recent_colors = []

tool_buttons = {}
quick_buttons = []
recent_frame = None
color_swatch = None
color_label = None
size_label = None
size_slider = None
status_tool = status_pos = status_hint = None
undo_btn = redo_btn = None
fonts = {}


# ----------------------------------------------------------------------------
# 4. SMALL HELPERS
# ----------------------------------------------------------------------------
def new_blank_image():
    """Return a fresh white image the size of the canvas."""
    return Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), "white")


def set_image(new_image):
    """Make `new_image` the current drawing."""
    global image, draw
    image = new_image
    draw = ImageDraw.Draw(image)


def pick_font(size, weight="normal"):
    """Choose the first font family that exists on this computer."""
    available = set(tkfont.families())
    for family in FONT_FAMILIES:
        if family in available:
            return (family, size, weight)
    return ("TkDefaultFont", size, weight)


def tool_label(name):
    return {"brush": "Brush", "eraser": "Eraser", "spray": "Spray",
            "line": "Line", "rectangle": "Rectangle", "oval": "Oval",
            "triangle": "Triangle", "star": "Star", "hexagon": "Hexagon",
            "diamond": "Diamond",
            "fill": "Fill bucket", "picker": "Eyedropper"}[name]


# ----------------------------------------------------------------------------
# 5. SHAPE GEOMETRY  (one function used by BOTH the preview and the image)
# ----------------------------------------------------------------------------
def constrain(x0, y0, x1, y1):
    """Hold Shift: make the box a square (or snap lines to 45 degrees)."""
    dx, dy = x1 - x0, y1 - y0
    if tool == "line":
        angle = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
        length = math.hypot(dx, dy)
        return x0, y0, x0 + length * math.cos(angle), y0 + length * math.sin(angle)
    side = max(abs(dx), abs(dy))
    return (x0, y0, x0 + math.copysign(side, dx or 1),
            y0 + math.copysign(side, dy or 1))


def shape_points(name, x0, y0, x1, y1):
    """Return the corner points of a shape that fits in the box (x0,y0)-(x1,y1)."""
    left, right = min(x0, x1), max(x0, x1)
    top, bottom = min(y0, y1), max(y0, y1)
    cx, cy = (left + right) / 2, (top + bottom) / 2
    rx, ry = (right - left) / 2, (bottom - top) / 2

    if name == "line":
        return [(x0, y0), (x1, y1)]
    if name == "rectangle":
        return [(left, top), (right, top), (right, bottom), (left, bottom)]
    if name == "triangle":
        return [(cx, top), (right, bottom), (left, bottom)]
    if name == "diamond":
        return [(cx, top), (right, cy), (cx, bottom), (left, cy)]
    if name == "oval":                       # an oval is many tiny corners
        steps = max(24, int(max(rx, ry) * 0.8))
        return [(cx + rx * math.cos(2 * math.pi * i / steps),
                 cy + ry * math.sin(2 * math.pi * i / steps))
                for i in range(steps)]
    if name == "hexagon":
        return [(cx + rx * math.cos(math.radians(60 * i)),
                 cy + ry * math.sin(math.radians(60 * i))) for i in range(6)]
    if name == "star":                       # 5 points: alternate outer/inner
        points = []
        for i in range(10):
            radius = 1.0 if i % 2 == 0 else 0.42
            angle = math.radians(-90 + 36 * i)
            points.append((cx + rx * radius * math.cos(angle),
                           cy + ry * radius * math.sin(angle)))
        return points
    return []


def flat(points):
    """[(x, y), (x, y)] -> [x, y, x, y] (the format Tkinter wants)."""
    return [value for point in points for value in point]


# ----------------------------------------------------------------------------
# 6. DRAWING ON THE PILLOW IMAGE
# ----------------------------------------------------------------------------
def dot(x, y, size, color):
    """A round dot - this gives brush strokes round ends."""
    r = size / 2
    draw.ellipse((x - r, y - r, x + r, y + r), fill=color)


def stroke(points, size, color, closed=False):
    """Draw a thick line through `points` with round corners and ends."""
    pts = list(points)
    if closed:
        pts = pts + [pts[0]]
    if len(pts) >= 2:
        draw.line(pts, fill=color, width=max(1, int(size)), joint="curve")
    for x, y in (pts if len(pts) <= 12 else (pts[0], pts[-1])):
        dot(x, y, size, color)


def paint_shape(name, x0, y0, x1, y1, color, size, filled):
    """Paint one finished shape into the Pillow image."""
    points = shape_points(name, x0, y0, x1, y1)
    if name == "line":
        stroke(points, size, color)
        return
    if filled and name in FILLABLE:
        draw.polygon(points, fill=color)
    stroke(points, size, color, closed=True)


# ----------------------------------------------------------------------------
# 7. UNDO / REDO  (requirement 2)
# ----------------------------------------------------------------------------
def push_undo(snapshot):
    """Remember how the picture looked BEFORE an action."""
    undo_stack.append(snapshot)
    if len(undo_stack) > MAX_UNDO:
        undo_stack.pop(0)
    redo_stack.clear()
    update_history_buttons()


def undo(event=None):
    """Go back one step: removes the most recent stroke, shape, fill or clear."""
    if not undo_stack:
        set_hint("Nothing to undo")
        return
    redo_stack.append(image.copy())
    set_image(undo_stack.pop())
    refresh_canvas()
    update_history_buttons()
    set_hint("Undo")


def redo(event=None):
    """Bring back the step that was just undone."""
    if not redo_stack:
        set_hint("Nothing to redo")
        return
    undo_stack.append(image.copy())
    set_image(redo_stack.pop())
    refresh_canvas()
    update_history_buttons()
    set_hint("Redo")


def update_history_buttons():
    """Dim Undo/Redo when there is nothing to undo/redo."""
    for button, stack in ((undo_btn, undo_stack), (redo_btn, redo_stack)):
        if button is not None:
            button.config(fg=TEXT if stack else MUTED)
            button.enabled = bool(stack)


# ----------------------------------------------------------------------------
# 8. COLORS  (requirement 6 + color picker)
# ----------------------------------------------------------------------------
def set_color(color, remember=True):
    """Change the drawing color everywhere it is shown."""
    global current_color
    current_color = color
    color_swatch.config(bg=color)
    color_label.config(text=color.upper())
    if remember:
        add_recent(color)
    if tool in ("eraser", "picker"):     # picking a color means "paint with it"
        set_tool("brush")


def add_recent(color):
    """Keep a short list of recently used colors."""
    if color in [c for _, c in QUICK_COLORS]:
        return
    if color in recent_colors:
        recent_colors.remove(color)
    recent_colors.insert(0, color)
    del recent_colors[MAX_RECENT:]
    rebuild_recent()


def rebuild_recent():
    for child in recent_frame.winfo_children():
        child.destroy()
    for color in recent_colors:
        swatch = tk.Frame(recent_frame, bg=color, width=20, height=20,
                          cursor="hand2", highlightthickness=1,
                          highlightbackground=CARD)
        swatch.pack(side="left", padx=2)
        swatch.bind("<Button-1>", lambda e, c=color: set_color(c, remember=False))


def choose_color():
    """Open the system color chooser."""
    selected = colorchooser.askcolor(color=current_color, title="Choose a color")
    if selected[1] is not None:
        set_color(selected[1])


# ----------------------------------------------------------------------------
# 9. TOOLS AND BRUSH SIZE  (requirement 1)
# ----------------------------------------------------------------------------
def set_tool(selected_tool):
    """Change the active tool and highlight its button."""
    global tool
    tool = selected_tool
    for name, button in tool_buttons.items():
        button.set_active(name == tool)
    if tool in ("brush", "eraser", "spray"):
        canvas.config(cursor="none")     # the size ring replaces the cursor
    else:
        canvas.config(cursor={"fill": "spraycan", "picker": "target"}.get(tool, "cross"))
    status_tool.config(text=tool_label(tool))
    update_ring_visibility()


def change_brush_size(value):
    """Slider callback. The slider range is 1 to 100."""
    global brush_size
    brush_size = int(float(value))
    size_label.config(text=f"{brush_size} px")


def nudge_size(amount):
    """Keyboard shortcut: [ and ] change the brush size."""
    size_slider.set(max(1, min(100, brush_size + amount)))


# ----------------------------------------------------------------------------
# 10. MOUSE EVENTS
# ----------------------------------------------------------------------------
def start_drawing(event):
    """Mouse pressed: remember where, and take an undo snapshot."""
    global start_x, start_y, last_x, last_y, before_snapshot, is_drawing
    x, y = event.x, event.y
    start_x, start_y = last_x, last_y = x, y

    if tool == "picker":
        pick_color(x, y)
        return
    if tool == "fill":
        flood_fill(x, y)
        return

    is_drawing = True
    before_snapshot = image.copy()
    if tool in ("brush", "eraser"):
        color = "white" if tool == "eraser" else current_color
        dot(x, y, brush_size, color)         # a single click leaves a dot
        draw_canvas_dot(x, y, color)
    elif tool == "spray":
        spray(x, y)


def draw_motion(event):
    """Mouse dragged with the left button held."""
    global last_x, last_y
    move_ring(event)
    update_position(event)
    if not is_drawing:
        return
    x, y = clamp(event.x, event.y)

    if tool in ("brush", "eraser"):
        color = "white" if tool == "eraser" else current_color
        # Draw on the visible canvas AND on the Pillow image.
        canvas.create_line(last_x, last_y, x, y, fill=color, width=brush_size,
                           capstyle=tk.ROUND, joinstyle=tk.ROUND, tags="live")
        draw_canvas_dot(x, y, color)
        stroke([(last_x, last_y), (x, y)], brush_size, color)
        last_x, last_y = x, y
    elif tool == "spray":
        spray(x, y)
    elif tool in SHAPE_TOOLS:
        preview_shape(event)


def finish_drawing(event):
    """Mouse released: save the shape into the image and store undo data."""
    global preview_item, is_drawing, before_snapshot
    if not is_drawing:
        return
    is_drawing = False
    changed = True
    if tool in SHAPE_TOOLS:
        x0, y0, x1, y1 = shape_box(event)
        changed = abs(x1 - x0) > 1 or abs(y1 - y0) > 1
        if changed:                      # ignore a click without a drag
            paint_shape(tool, x0, y0, x1, y1, current_color, brush_size,
                        fill_shapes.get())
        preview_item = None
    if changed:
        push_undo(before_snapshot)       # one drawing action = one undo step
    before_snapshot = None
    refresh_canvas()                    # show exactly what is stored


def clamp(x, y):
    """Keep a point inside the canvas."""
    return (max(0, min(CANVAS_WIDTH - 1, x)), max(0, min(CANVAS_HEIGHT - 1, y)))


def shift_held(event):
    return bool(event.state & 0x0001)


def shape_box(event):
    """Start and end points of the shape being dragged (Shift = constrained)."""
    x1, y1 = clamp(event.x, event.y)
    x0, y0 = start_x, start_y
    if shift_held(event):
        x0, y0, x1, y1 = constrain(x0, y0, x1, y1)
    return x0, y0, x1, y1


def draw_canvas_dot(x, y, color):
    r = brush_size / 2
    canvas.create_oval(x - r, y - r, x + r, y + r, fill=color, outline=color,
                       tags="live")


def spray(x, y):
    """Spray can: scatter random dots around the mouse."""
    radius = max(4, brush_size)
    for _ in range(max(6, radius // 2)):
        angle = random.uniform(0, 2 * math.pi)
        distance = radius * math.sqrt(random.random())
        px, py = x + distance * math.cos(angle), y + distance * math.sin(angle)
        draw.point((px, py), fill=current_color)
        draw.point((px + 1, py), fill=current_color)
        canvas.create_rectangle(px, py, px + 1, py + 1, fill=current_color,
                                outline=current_color, tags="live")


# ----------------------------------------------------------------------------
# 11. SHAPE PREVIEW  (requirement 4: must show while dragging)
# ----------------------------------------------------------------------------
def preview_shape(event):
    """Show a temporary shape while the mouse is being dragged."""
    global preview_item
    if preview_item is not None:
        canvas.delete(preview_item)
    x0, y0, x1, y1 = shape_box(event)
    points = flat(shape_points(tool, x0, y0, x1, y1))
    if tool == "line":
        preview_item = canvas.create_line(
            *points, fill=current_color, width=brush_size,
            capstyle=tk.ROUND, tags="preview")
    else:
        filled = fill_shapes.get()
        preview_item = canvas.create_polygon(
            *points, fill=current_color if filled else "",
            outline=current_color, width=brush_size, joinstyle=tk.ROUND,
            tags="preview")


# ----------------------------------------------------------------------------
# 12. FILL BUCKET AND EYEDROPPER
# ----------------------------------------------------------------------------
def flood_fill(x, y):
    """Fill the connected area under the mouse with the current color."""
    x, y = clamp(x, y)
    snapshot = image.copy()
    canvas.config(cursor="watch")
    canvas.update_idletasks()
    ImageDraw.floodfill(image, (x, y), _rgb(current_color), thresh=12)
    canvas.config(cursor="spraycan")
    push_undo(snapshot)
    refresh_canvas()


def pick_color(x, y):
    """Eyedropper: copy the color of the pixel under the mouse."""
    x, y = clamp(x, y)
    r, g, b = image.getpixel((x, y))
    set_color(f"#{r:02x}{g:02x}{b:02x}")
    set_tool("brush")


def _rgb(color):
    """'#RRGGBB' -> (r, g, b)"""
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


# ----------------------------------------------------------------------------
# 13. CANVAS MANAGEMENT
# ----------------------------------------------------------------------------
def refresh_canvas():
    """Display the current Pillow image on the Tkinter canvas."""
    global canvas_image, image_item
    canvas.delete("live")
    canvas.delete("preview")
    canvas_image = ImageTk.PhotoImage(image)
    if image_item is None:
        image_item = canvas.create_image(0, 0, anchor="nw", image=canvas_image)
    else:
        canvas.itemconfig(image_item, image=canvas_image)
    if ring_item is not None:
        canvas.tag_raise(ring_item)


def clear_canvas():
    """Requirement 5: ask first. Yes clears the canvas, No keeps the drawing."""
    answer = messagebox.askyesno(
        "Clear canvas", "Are you sure you want to clear the whole canvas?",
        icon="warning", parent=root)
    if not answer:                       # user pressed "No"
        set_hint("Clear cancelled")
        return
    push_undo(image.copy())              # so Undo can bring the drawing back
    set_image(new_blank_image())
    refresh_canvas()
    set_hint("Canvas cleared (Ctrl+Z to undo)")


def fit_image(source):
    """Fit any picture inside the canvas WITHOUT stretching it."""
    source = source.convert("RGB")
    source.thumbnail((CANVAS_WIDTH, CANVAS_HEIGHT), Image.LANCZOS)
    page = new_blank_image()
    page.paste(source, ((CANVAS_WIDTH - source.width) // 2,
                        (CANVAS_HEIGHT - source.height) // 2))
    return page


def open_image(event=None):
    """Open an image file and show it on the canvas."""
    file_path = filedialog.askopenfilename(
        filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.gif"),
                   ("All files", "*.*")])
    if file_path:
        try:
            opened = fit_image(Image.open(file_path))
        except Exception as error:
            messagebox.showerror("Error", f"Could not open image:\n{error}")
            return
        push_undo(image.copy())
        set_image(opened)
        refresh_canvas()
        set_hint("Image opened")


def save_image(event=None):
    """Save the drawing. The file is exactly CANVAS_WIDTH x CANVAS_HEIGHT."""
    file_path = filedialog.asksaveasfilename(
        defaultextension=".png",
        filetypes=[("PNG Image", "*.png"),
                   ("JPEG Image", "*.jpg"),
                   ("Bitmap Image", "*.bmp")])
    if file_path:
        try:
            image.save(file_path)
            messagebox.showinfo("Saved", "Your drawing has been saved!")
        except Exception as error:
            messagebox.showerror("Error", f"Could not save image:\n{error}")


# ----------------------------------------------------------------------------
# 14. CURSOR RING AND STATUS BAR
# ----------------------------------------------------------------------------
def move_ring(event):
    """A circle that shows how big the brush is."""
    global ring_item
    if tool not in ("brush", "eraser", "spray"):
        return
    r = max(4, brush_size) if tool == "spray" else brush_size / 2
    x, y = event.x, event.y
    if ring_item is None:
        ring_item = canvas.create_oval(0, 0, 0, 0, outline="#888888", width=1)
    canvas.coords(ring_item, x - r, y - r, x + r, y + r)
    canvas.itemconfig(ring_item, state="normal",
                      outline="#FF6B9D" if tool == "eraser" else "#7A7A7A")
    canvas.tag_raise(ring_item)


def update_ring_visibility(*_):
    if ring_item is not None and tool not in ("brush", "eraser", "spray"):
        canvas.itemconfig(ring_item, state="hidden")


def hide_ring(event=None):
    if ring_item is not None:
        canvas.itemconfig(ring_item, state="hidden")


def update_position(event):
    status_pos.config(text=f"{event.x}, {event.y} px")


def set_hint(text):
    status_hint.config(text=text)


# ----------------------------------------------------------------------------
# 15. CUSTOM FLAT BUTTONS  (Labels look the same on Windows, Mac and Linux)
# ----------------------------------------------------------------------------
class FlatButton(tk.Label):
    """A flat button with hover and 'active' colors."""

    def __init__(self, parent, text, command, width=None, bg=CARD,
                 hover=HOVER, active_bg=ACCENT, font=None, pady=7, **kwargs):
        super().__init__(parent, text=text, bg=bg, fg=TEXT, cursor="hand2",
                         font=font or fonts["button"], padx=10, pady=pady,
                         width=width, **kwargs)
        self.command = command
        self.base_bg, self.hover_bg, self.active_bg = bg, hover, active_bg
        self.active = False
        self.enabled = True
        self.bind("<Enter>", lambda e: self.config(
            bg=self.active_bg if self.active else self.hover_bg))
        self.bind("<Leave>", lambda e: self.config(
            bg=self.active_bg if self.active else self.base_bg))
        self.bind("<Button-1>", lambda e: self.command() if self.enabled else None)

    def set_active(self, active):
        self.active = active
        self.config(bg=self.active_bg if active else self.base_bg,
                    fg="#1B1030" if active else TEXT)


def section_title(parent, text):
    tk.Label(parent, text=text.upper(), bg=PANEL, fg=MUTED,
             font=fonts["small"]).pack(anchor="w", padx=16, pady=(14, 6))


# ----------------------------------------------------------------------------
# 16. BUILD THE INTERFACE
# ----------------------------------------------------------------------------
def build_header():
    global undo_btn, redo_btn
    header = tk.Frame(root, bg=PANEL)
    header.pack(fill="x")

    # App name "Paint'Ered": Paint and Ered share one color, the ' is sky blue.
    tk.Label(header, text="Paint", bg=PANEL, fg=TEXT, padx=0,
             font=fonts["title"]).pack(side="left", padx=(18, 0), pady=12)
    tk.Label(header, text="'", bg=PANEL, fg=SKY_BLUE, padx=0,
             font=fonts["title"]).pack(side="left")
    tk.Label(header, text="Ered", bg=PANEL, fg=TEXT, padx=0,
             font=fonts["title"]).pack(side="left")

    # Right side of the header: file buttons
    FlatButton(header, "Save", save_image, bg=ACCENT, hover="#FF86AF",
               active_bg=ACCENT).pack(side="right", padx=(6, 18), pady=10)
    FlatButton(header, "Open", open_image).pack(side="right", padx=6)
    tk.Frame(header, bg=CARD, width=2, height=24).pack(side="right", padx=8)
    FlatButton(header, "Clear", clear_canvas).pack(side="right", padx=6)
    redo_btn = FlatButton(header, "Redo", redo)
    redo_btn.pack(side="right", padx=6)
    undo_btn = FlatButton(header, "Undo", undo)       # requirement 2
    undo_btn.pack(side="right", padx=6)
    update_history_buttons()


def build_sidebar(parent):
    global color_swatch, color_label, size_label, size_slider
    global recent_frame, fill_shapes

    side = tk.Frame(parent, bg=PANEL, width=224)
    side.pack(side="left", fill="y")
    side.pack_propagate(False)

    # ---- Tools ----
    section_title(side, "Tools")
    grid = tk.Frame(side, bg=PANEL)
    grid.pack(fill="x", padx=14)
    tools = [("brush", "Brush"), ("eraser", "Eraser"),
             ("spray", "Spray"), ("fill", "Fill"),
             ("line", "Line"), ("picker", "Pick"),
             ("rectangle", "Rectangle"), ("oval", "Oval"),
             ("triangle", "Triangle"), ("diamond", "Diamond"),
             ("hexagon", "Hexagon"), ("star", "Star")]
    for index, (name, label) in enumerate(tools):
        button = FlatButton(grid, label, lambda n=name: set_tool(n))
        button.grid(row=index // 2, column=index % 2, sticky="ew",
                    padx=3, pady=2)
        tool_buttons[name] = button
    grid.columnconfigure(0, weight=1, uniform="tools")
    grid.columnconfigure(1, weight=1, uniform="tools")

    # ---- Fill switch (requirement 3) ----
    fill_shapes = tk.BooleanVar(value=False)
    tk.Checkbutton(
        side, text="  Fill shapes with color", variable=fill_shapes,
        bg=PANEL, fg=TEXT, selectcolor=CARD, activebackground=PANEL,
        activeforeground=TEXT, font=fonts["body"], cursor="hand2",
        highlightthickness=0, bd=0,
    ).pack(anchor="w", padx=16, pady=(10, 0))

    # ---- Colors ----
    section_title(side, "Color")
    current = tk.Frame(side, bg=PANEL)
    current.pack(fill="x", padx=16)
    color_swatch = tk.Frame(current, bg=current_color, width=38, height=38,
                            highlightthickness=2, highlightbackground=TEXT)
    color_swatch.pack(side="left")
    color_label = tk.Label(current, text=current_color.upper(), bg=PANEL,
                           fg=TEXT, font=fonts["mono"])
    color_label.pack(side="left", padx=10)

    # Six quick colors (requirement 6)
    quick = tk.Frame(side, bg=PANEL)
    quick.pack(fill="x", padx=16, pady=(10, 0))
    for name, color in QUICK_COLORS:
        swatch = tk.Frame(quick, bg=color, width=22, height=22, cursor="hand2",
                          highlightthickness=2, highlightbackground=PANEL)
        swatch.pack(side="left", padx=(0, 4))
        swatch.bind("<Button-1>", lambda e, c=color: set_color(c))
        swatch.bind("<Enter>", lambda e, s=swatch, n=name:
                    (s.config(highlightbackground=TEXT), set_hint(n)))
        swatch.bind("<Leave>", lambda e, s=swatch:
                    (s.config(highlightbackground=PANEL),
                     set_hint(DEFAULT_HINT)))
        quick_buttons.append(swatch)

    FlatButton(side, "More colors...", choose_color, font=fonts["small_btn"]
               ).pack(fill="x", padx=16, pady=(10, 0))

    tk.Label(side, text="Recent", bg=PANEL, fg=MUTED, font=fonts["small"]
             ).pack(anchor="w", padx=16, pady=(12, 4))
    recent_frame = tk.Frame(side, bg=PANEL, height=22)
    recent_frame.pack(fill="x", padx=14)

    # ---- Brush size (requirement 1) ----
    section_title(side, "Brush size")
    size_row = tk.Frame(side, bg=PANEL)
    size_row.pack(fill="x", padx=16)
    size_label = tk.Label(size_row, text="5 px", bg=PANEL, fg=ACCENT_2,
                          font=fonts["mono"])
    size_label.pack(anchor="e")
    size_slider = tk.Scale(
        side, from_=1, to=100, orient="horizontal",          # 1 -> 100
        command=change_brush_size, length=190,
        bg=PANEL, fg=TEXT, troughcolor=ACCENT, highlightthickness=0)
    size_slider.set(5)
    size_slider.pack(fill="x", padx=14)


def build_canvas(parent):
    global canvas
    area = tk.Frame(parent, bg=BG)
    area.pack(side="left", fill="both", expand=True)

    # soft shadow + border around the white paper
    shadow = tk.Frame(area, bg="#0E0C1E", padx=3, pady=3)
    shadow.place(relx=0.5, rely=0.5, anchor="center")
    canvas = tk.Canvas(shadow, width=CANVAS_WIDTH, height=CANVAS_HEIGHT,
                       bg="white", cursor="none", highlightthickness=0)
    canvas.pack()


def build_status_bar():
    global status_tool, status_pos, status_hint
    bar = tk.Frame(root, bg=PANEL)
    bar.pack(side="bottom", fill="x")
    status_tool = tk.Label(bar, text="Brush", bg=PANEL, fg=ACCENT,
                           font=fonts["small_btn"], width=12, anchor="w")
    status_tool.pack(side="left", padx=(16, 0), pady=5)
    status_hint = tk.Label(
        bar, bg=PANEL, fg=MUTED, font=fonts["small"], anchor="w",
        text=DEFAULT_HINT)
    status_hint.pack(side="left", padx=20)
    status_pos = tk.Label(bar, text="", bg=PANEL, fg=MUTED,
                          font=fonts["small"], width=14, anchor="e")
    status_pos.pack(side="right", padx=16)


def bind_events():
    canvas.bind("<Button-1>", start_drawing)
    canvas.bind("<B1-Motion>", draw_motion)
    canvas.bind("<ButtonRelease-1>", finish_drawing)
    canvas.bind("<Motion>", lambda e: (move_ring(e), update_position(e)))
    canvas.bind("<Leave>", hide_ring)

    root.bind("<Control-z>", undo)
    root.bind("<Control-y>", redo)
    root.bind("<Control-Shift-Z>", redo)
    root.bind("<Control-s>", save_image)
    root.bind("<Control-o>", open_image)
    root.bind("<bracketleft>", lambda e: nudge_size(-5))
    root.bind("<bracketright>", lambda e: nudge_size(5))
    for key, name in (("b", "brush"), ("e", "eraser"), ("s", "spray"),
                      ("f", "fill"), ("l", "line"), ("r", "rectangle"),
                      ("o", "oval"), ("t", "triangle"), ("d", "diamond"),
                      ("h", "hexagon"),
                      ("a", "star"), ("i", "picker")):
        root.bind(f"<KeyPress-{key}>", lambda e, n=name: set_tool(n))


# ----------------------------------------------------------------------------
# 17. RUN THE APPLICATION
# ----------------------------------------------------------------------------
def main():
    global root, fonts
    root = tk.Tk()
    root.title("Paint'Ered")
    root.geometry("1180x700")
    root.minsize(1180, 690)
    root.configure(bg=BG)

    fonts = {
        "title": pick_font(17, "bold"),
        "button": pick_font(10, "bold"),
        "body": pick_font(10),
        "small": pick_font(8, "bold"),
        "small_btn": pick_font(9, "bold"),
        "mono": ("Consolas" if "Consolas" in tkfont.families() else "Courier",
                 11, "bold"),
    }

    set_image(new_blank_image())
    build_header()
    build_status_bar()
    body = tk.Frame(root, bg=BG)
    body.pack(fill="both", expand=True)
    build_sidebar(body)
    build_canvas(body)
    bind_events()

    refresh_canvas()
    set_color("#000000", remember=False)
    set_tool("brush")
    root.mainloop()


if __name__ == "__main__":
    main()
