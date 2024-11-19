import abc
import numpy as np
import threading
import datetime
from typing import Optional

from talon import Module, app, actions, ui, imgui, canvas, screen, cron

from talon.skia import image, rrect, paint
from talon.types import Rect as TalonRect
from talon.experimental import locate

from .ui_widgets import layout_text, render_text
from .marker_ui import MarkerUi
from .blob_detector import calculate_blob_rects


mod = Module()


def find_active_window_rect() -> TalonRect:
    return ui.active_window().rect


def screencap_to_image(rect: TalonRect) -> 'talon.skia.image.Image':
    """
    Captures the given rectangle off the screen
    """

    return screen.capture(rect.x, rect.y, rect.width, rect.height, retina=False)


class ScreenshotOverlay(abc.ABC):
    """
    Abstract base class for overlay windows operating on a static screenshot.
    """

    # See _calculate_rect_handler
    CALCULATE_RECT_CANVAS_COLOR = "010203ff"
    CALCULATE_RECT_CANVAS_COLOR_NUMERIC = [1, 2, 3, 255]

    def __init__(self, result_handler, text=None, screen_idx=None):
        self.result_handler = result_handler

        if screen_idx is not None:
            self.screen_rect = ui.screens()[screen_idx].rect
        else:
            active_window = ui.active_window()
            if active_window.id == -1:
                self.screen_rect = ui.main_screen().rect
            else:
                self.screen_rect = active_window.screen.rect

        self.can = canvas.Canvas.from_rect(self.screen_rect)
        # Need panel = True for keyboard events to be captured on Linux
        self.can.panel = True
        # See _calculate_rect_handler for where this is used to refine
        # canvas size.
        self.calculate_rect_state = "initial"

        # We want an unfocus event to destroy the overlay normally, but
        # we get some initial illegitimate unfocus events, so ignore those.
        self.unfocus_destroy_enabled = False
        def _set_unfocus_destroy_enabled():
            if not self.can.focused:
                self.destroy()
            else:
                self.unfocus_destroy_enabled = True
        cron.after("1000ms", _set_unfocus_destroy_enabled)

        self.image = screencap_to_image(self.screen_rect)
        self.text = text
        self.text_position = "bottom"
        self.text_rect = None
        self.flash_text = None

        self.can.register("draw", self._draw_wrapper)
        self.can.blocks_mouse = True
        self.can.register("mouse", self._mouse_event)
        self.can.register("key", self._key_event)
        self.can.register("focus", self._focus_event)
        self.can.focused = True
        self.can.freeze()

    def destroy(self):
        self.can.close()

    def _calculate_rect_handler(self):
        """
        Working out how big to make the canvas isn't straightforward.
        Window manager's may move us (OSX, Linux), and may also have
        floating panels that are positioned above our window (due to
        panel = True).

        So what we do is take a screenshot after filling our attempt
        at a full screen canvas with a particular color. We then
        search the image to find that color, and this tells us what
        parts aren't covered by window manager decorations. We can
        then resize and move the canvas to fit within that area.

        An alternative would be to change the whole UI to implement
        a scrollable window that shows the whole screenshot.
        """

        if app.platform == "windows":
            # Windows screen capture doesn't seem to include the overlay,
            # and doesn't need this trickery anyway, so just go to the regular
            # draw handler without changing anything.
            self.calculate_rect_state = "normal"
            self.can.freeze()
            return

        talon_img = screencap_to_image(self.screen_rect)
        img = np.array(
            talon_img
        )
        # Array of True/False indicating whether the pixel is our
        # special color
        masked_array = np.all(
            img == self.CALCULATE_RECT_CANVAS_COLOR_NUMERIC,
            axis=2
        )

        def _calculate_bounds(mask, axis):
            background_items = np.any(
                mask,
                axis=axis
            )
            bg_start = None
            bg_end = None
            for idx, is_background in enumerate(background_items):
                if is_background:
                    bg_start = idx if bg_start is None else min(idx, bg_start)
                    bg_end = idx if bg_end is None else max(idx, bg_end)
            return bg_start, bg_end + 1

        row_start_idx, row_end_idx = _calculate_bounds(masked_array, 1)
        col_start_idx, col_end_idx = _calculate_bounds(
            masked_array[row_start_idx:row_end_idx],
            0
        )

        self.can.rect = TalonRect(
            col_start_idx,
            row_start_idx,
            col_end_idx - col_start_idx,
            row_end_idx - row_start_idx,
        )

        # Clean up, our work is done.
        self.calculate_rect_state = "normal"
        self.can.freeze()

    def _get_keyboard_commands(self):
        return [
            ("escape", "Close overlay"),
            ("enter", "Confirm selection and close overlay"),
        ]

    def _calculate_result(self):
        raise NotImplementedError

    def _draw_wrapper(self, canvas):
        # This will delegate to _draw for normal drawing, so override that.
        # See _calculate_rect_handler for what's happening here
        if self.calculate_rect_state in ("initial", "drawn"):
            canvas.paint = paint.Paint()
            canvas.paint.color = self.CALCULATE_RECT_CANVAS_COLOR
            canvas.draw_rect(canvas.rect)
            if self.calculate_rect_state == "initial":
                # Give the canvas a bit of time to redraw
                cron.after("200ms", self._calculate_rect_handler)
            self.calculate_rect_state = "drawn"
        elif self.calculate_rect_state == "normal":
            self._draw(canvas)
        else:
            assert False, "Unhandled state: " + self.calculate_rect_state

    def _draw(self, canvas):
        # This is the normal draw routine
        canvas.draw_image(self.image, 0, 0)
        canvas.paint = paint.Paint()
        canvas.paint.color = "000000aa"
        canvas.draw_rect(canvas.rect)

        self._draw_widgets(canvas)

        self._draw_text(canvas)

        self._draw_flash(canvas)

    def _draw_widgets(self, canvas):
        pass

    def _draw_text(self, canvas):
        all_text = self.text or ""
        all_text += "\n\nKeyboard shortcuts (or use equivalent voice command):\n"
        all_text += "\n".join([
            f" - {key}: {description}"
            for key, description in self._get_keyboard_commands()
        ])

        canvas.paint = paint.Paint()
        canvas.paint.antialias = True
        canvas.paint.color = "ffffffff"
        ((width, height), formatted_text) = layout_text(all_text, canvas.paint, 600)

        xpos = canvas.rect.x + (canvas.width - width - 20) / 2
        ypos = 10 + canvas.rect.y
        if self.text_position == "bottom":
            ypos = canvas.rect.y + canvas.height - height - 20 - 10
        self.text_rect = TalonRect(xpos, ypos, width + 20, height + 20)

        canvas.paint.color = "000000ff"
        canvas.paint.style = canvas.paint.Style.FILL
        thing = rrect.RoundRect.from_rect(
            self.text_rect,
            x=10,
            y=10,
            radii=(10, 10)
        )
        canvas.draw_rrect(thing)

        render_text(canvas, formatted_text, xpos + 10, ypos + 20)

    def _draw_flash(self, canvas):
        if self.flash_text is None:
            return

        canvas.paint = paint.Paint()
        canvas.paint.antialias = True
        canvas.paint.color = "ffffffff"
        ((width, height), formatted_text) = layout_text(self.flash_text, canvas.paint, 300)

        xpos = canvas.rect.x + (canvas.width - width - 20) / 2
        ypos = canvas.rect.y + (canvas.height - height - 20) / 2
        text_rect = TalonRect(xpos, ypos, width + 20, height + 20)

        canvas.paint.color = "660000ff"
        canvas.paint.style = canvas.paint.Style.FILL
        thing = rrect.RoundRect.from_rect(
            text_rect,
            x=10,
            y=10,
            radii=(10, 10)
        )
        canvas.draw_rrect(thing)

        render_text(canvas, formatted_text, xpos + 10, ypos + 20)

    def _show_flash(self, text):
        self.flash_text = text
        def clear_flash():
            self.flash_text = None
            self.can.freeze()
        cron.after("2s", clear_flash)

    def _focus_event(self, focussed):
        if not focussed and self.unfocus_destroy_enabled:
            self.destroy()
            self.result_handler(None)

    def _key_event(self, evt):
        if evt.down:
            return

        # Lowercase events are for Talon 0.3, upper for 0.4+ (Rust)
        if evt.key in ("Escape", "esc"):
            self.destroy()
            self.result_handler(None)

        if evt.key in ("Return", "return", "Enter"):
            self.destroy()
            self.result_handler(self._calculate_result())

    def _mouse_event(self, evt):
        if self.text_rect:
            if self.text_rect.contains(evt.gpos.x, evt.gpos.y):
                self.text_position = "top" if self.text_position == "bottom" else "bottom"
                self.can.freeze()


class BoxSelectorOverlay(ScreenshotOverlay):
    """
    Show an overlay allowing the user to select a region of the screen.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.hl_region = None
        self.is_selecting = False
        self.settled_countdown_timer = None

    def _calculate_result(self):
        return self.hl_region

    def _get_keyboard_commands(self):
        commands = super()._get_keyboard_commands()
        commands += [
            ("up/down/left/right", "Nudge selection in indicated direction"),
            ("shift + up/down/left/right", "Nudge selection a larger amount"),
            ("ctrl + up/down/left/right", "Shrink/grow selection"),
            ("shift + ctrl + up/down/left/right", "Shrink/grow selection a larger amount"),
        ]
        return commands

    def _selection_settled(self, finished_selection):
        """
        Called when we can assume that the user has finished selecting a region, or when
        they've just started drawing a new one. If you want to draw any other markers
        after the user has finished selecting this is the place to set and unset
        a flag for _draw_widgets.
        """

    def _get_region(self):
        """
        Gets the selected region, normalising any negative widths
        """

        if self.hl_region is None:
            return None

        if self.hl_region.width < 0:
            x = self.hl_region.x + self.hl_region.width
            width = self.hl_region.width * -1
        else:
            x = self.hl_region.x
            width = self.hl_region.width

        if self.hl_region.height < 0:
            y = self.hl_region.y + self.hl_region.height
            height = self.hl_region.height * -1
        else:
            y = self.hl_region.y
            height = self.hl_region.height

        return TalonRect(
            int(x),
            int(y),
            int(width),
            int(height)
        )

    def _draw_widgets(self, canvas):
        super()._draw_widgets(canvas)

        if not self.hl_region:
            return
        canvas.save()
        canvas.clip_rect(self.hl_region, canvas.ClipOp.INTERSECT)
        canvas.draw_image(self.image, 0, 0)
        canvas.restore()
        canvas.paint = paint.Paint()
        canvas.paint.style = canvas.paint.Style.STROKE
        canvas.paint.color = 'ffffffff'
        if self.hl_region.width == 0 or self.hl_region.height == 0:
            # Deal with the zero thickness cases that happen when using voice commands
            canvas.draw_line(
                self.hl_region.x,
                self.hl_region.y,
                self.hl_region.x + self.hl_region.width,
                self.hl_region.y + self.hl_region.height
            )
        else:
            canvas.draw_rect(self.hl_region)

    def _get_region_centre(self):
        if self.hl_region:
            return (
                self.hl_region.x + self.hl_region.width / 2,
                self.hl_region.y + self.hl_region.height / 2
            )
        else:
            return None

    def _get_cropped_image(self) -> Optional['talon.Image']:
        if self.hl_region is None:
            return None

        # I think make_subset does this more cleanly, but I don't know what the Talon API is
        region = self._get_region()
        xpos = region.x
        ypos = region.y
        arr = np.array(self.image)[
            ypos:(ypos + region.height),
            xpos:(xpos + region.width),
        ]
        if len(arr) == 0:
            return None

        return image.Image.from_array(arr)

    def _mouse_event(self, evt):
        super()._mouse_event(evt)

        if evt.event == "mousedown" and evt.button == 0:
            self.hl_region = TalonRect(evt.gpos.x, evt.gpos.y, 0, 0)
            self.is_selecting = True
            self._selection_settled(False)
            self.can.freeze()
        elif evt.event == "mousemove" and self.is_selecting and self.hl_region:
            self.hl_region = TalonRect(
                self.hl_region.x,
                self.hl_region.y,
                evt.gpos.x - self.hl_region.x,
                evt.gpos.y - self.hl_region.y
            )
            self.can.freeze()
        elif evt.event == "mouseup" and evt.button == 0:
            self.is_selecting = False
            self._selection_settled(True)
            self.can.freeze()

    def _key_event(self, evt):
        super()._key_event(evt)

        if evt.down or self.hl_region is None:
            return

        keymap = [
            # Needed between Talon 0.4.0-185 and 0.4.0-335. Can be removed after 2024-12-01 (once -335 changes have reached everybody).
            ("ArrowLeft", ["x", "width", "-"]),
            ("ArrowRight", ["x", "width", "+"]),
            ("ArrowUp", ["y", "height", "-"]),
            ("ArrowDown", ["y", "height", "+"]),

            # Talon 0.4 public
            ("Left", ["x", "width", "-"]),
            ("Right", ["x", "width", "+"]),
            ("Up", ["y", "height", "-"]),
            ("Down", ["y", "height", "+"]),

            # Talon 0.3 public
            ("left", ["x", "width", "-"]),
            ("right", ["x", "width", "+"]),
            ("up", ["y", "height", "-"]),
            ("down", ["y", "height", "+"]),
        ]

        for key, args in keymap:
            if key != evt.key:
                continue

            position, scale, direction = args
            magnitude = 25 if 'shift' in evt.mods else 1
            magnitude = -1 * magnitude if direction == "-" else magnitude

            if 'ctrl' in evt.mods:
                curr = getattr(self.hl_region, scale)
                new_val = curr + magnitude
                new_val = new_val if new_val >= 0 else 1
                setattr(self.hl_region, scale, new_val)
            else:
                curr = getattr(self.hl_region, position)
                new_val = curr + magnitude
                new_val = new_val if new_val >= 0 else 0
                setattr(self.hl_region, position, new_val)

            # Ensure the region is still within the bounds of the canvas
            for (position, scale) in (("x", "width"), ("y", "height")):
                min_pos = getattr(self.can.rect, position)
                max_pos = min_pos + getattr(self.can.rect, scale)
                curr_extent = getattr(self.hl_region, position) + getattr(self.hl_region, scale)

                if getattr(self.hl_region, position) < min_pos:
                    setattr(self.hl_region, position, min_pos)
                if getattr(self.hl_region, position) > max_pos:
                    setattr(self.hl_region, position, max_pos - 1)

                if curr_extent > max_pos:
                    setattr(
                        self.hl_region,
                        scale,
                        max_pos - getattr(self.hl_region, position)
                    )

            # Start the selection settled countdown timer
            self._selection_settled(False)
            self._reset_settled_countdown("2s")

            self.can.freeze()

    def _reset_settled_countdown(self, countdown):
        def _inner():
            self._selection_settled(True)
            self.settled_countdown_timer = None

        if self.settled_countdown_timer:
            cron.cancel(self.settled_countdown_timer)
        self.settled_countdown_timer = cron.after(countdown, _inner)


class ImageSelectorOverlay(BoxSelectorOverlay):
    """
    Allows the user to select a region on the screen to use as an image for the locator API.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.offset_coord = None
        self.result_rects = []

    def _calculate_result(self):
        if self.hl_region:
            if self.offset_coord is not None:
                cx, cy = self._get_region_centre()
                offset = (
                    self.offset_coord.x - cx,
                    self.offset_coord.y - cy
                )
            else:
                offset = None

            index = 0
            for i, rect in enumerate(self.result_rects):
                if rect == self._get_region():
                    index = i

            return {
                "image": self._get_cropped_image(),
                "offset": offset,
                "index": index
            }
        else:
            return None

    def _selection_settled(self, finished_selection):
        if finished_selection == False:
            self.result_rects = []
            return

        th = threading.Thread(target=self._find_matches, daemon=True)
        th.start()
        th.join(timeout=1)
        timed_out = th.is_alive()

        if timed_out or len(self.result_rects) > 20:
            self._show_flash(
                "Too many matches, not showing any of them"
            )
            self.result_rects = []

        self.can.freeze()

    def _draw_widgets(self, canvas):
        super()._draw_widgets(canvas)
        if not self.hl_region:
            return

        # Draw other matching regions
        if len(self.result_rects) > 0:
            self._draw_matches(canvas)

        # Draw the offset marker
        canvas.paint = paint.Paint()
        canvas.paint.style = canvas.paint.Style.FILL
        canvas.paint.color = "ff00ffff"
        canvas.paint.stroke_width = 1
        if self.offset_coord is None:
            args = [
                self.hl_region.x + self.hl_region.width / 2,
                self.hl_region.y + self.hl_region.height / 2
            ]
        else:
            args = [
                self.offset_coord.x,
                self.offset_coord.y
            ]
            canvas.paint.antialias = True
            canvas.draw_line(
                *self._get_region_centre(),
                *args
            )

        canvas.draw_circle(
            *args,
            2
        )

    def _find_matches(self):
        cropped_img = self._get_cropped_image()
        if cropped_img is None:
            self.result_rects = []
            return

        self.result_rects = locate.locate_in_image(
            self.image,
            cropped_img,
            threshold=0.9
        )
        self.result_rects = [
            TalonRect(
                rect.x,
                rect.y,
                rect.width,
                rect.height
            )
            for rect in self.result_rects
        ]

    def _draw_matches(self, canvas):
        canvas.paint = paint.Paint()
        canvas.paint.color = "ff0000aa"
        canvas.paint.style = canvas.paint.Style.STROKE
        canvas.paint.stroke_width = 1
        for rect in self.result_rects:
            if rect == self._get_region():
                continue
            canvas.save()
            canvas.clip_rect(rect, canvas.ClipOp.INTERSECT)
            canvas.draw_image(self.image, 0, 0)
            canvas.restore()
            canvas.draw_rect(rect)

    def _mouse_event(self, evt):
        super()._mouse_event(evt)

        if evt.event == "mousedown" and evt.button == 0:
            # Reset the coord when a new box is started
            self.offset_coord = None

        if evt.event == "mouseup" and evt.button == 1:
            self.offset_coord = evt.gpos
            self.can.freeze()


class BlobBoxOverlay(BoxSelectorOverlay):
    """
    And overlay that helps the user build a blob box by displaying the matched blobs
    live as they define boxes.
    """

    def _selection_settled(self, finished_selection):
        if finished_selection == False:
            self.markers = []
            return

        maybe_image = self._get_cropped_image()
        if maybe_image is None:
            return

        img = np.array(maybe_image)
        region = self._get_region()
        rects = calculate_blob_rects(img, region)

        self.markers = [
            MarkerUi.Marker(
                rect,
                label
            )
            for rect, label in zip(rects, "abcdefghijklmnopqrstuvwxyz0123456789"*3)
        ]
        self.can.freeze()

    def _draw_widgets(self, canvas):
        super()._draw_widgets(canvas)

        if not self.hl_region:
            return

        if self.markers:
            MarkerUi.draw_markers(canvas, self.markers)
