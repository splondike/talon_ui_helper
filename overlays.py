import abc
import numpy as np
import threading
import datetime

from talon import Module, actions, ui, imgui, canvas, screen
from talon.skia import image, rrect
from talon.types import Rect as TalonRect
from talon.experimental import locate

from .ui_widgets import layout_text, render_text


mod = Module()


def find_active_window_rect() -> TalonRect:
    return ui.active_window().rect


def screencap_to_image(rect: TalonRect) -> 'talon.skia.image.Image':
    """
    Captures the given rectangle off the screen
    """

    return screen.capture(rect.x, rect.y, rect.width, rect.height)


class ScreenshotOverlay(abc.ABC):
    """
    Abstract base class for overlay windows operating on a static screenshot.
    """

    def __init__(self, result_handler, text=None, screen_idx=None):
        self.result_handler = result_handler

        if screen_idx is not None:
            rect = ui.screens()[screen_idx].rect
        else:
            active_window = ui.active_window()
            if active_window.id == -1:
                rect = ui.main_screen().rect
            else:
                rect = active_window.screen.rect
        self.can = canvas.Canvas.from_rect(rect)
        # Redundantly include these offset so threads can access them (self.can gets locked
        # during draw handler).
        self.offsetx = int(self.can.rect.x)
        self.offsety = int(self.can.rect.y)
        self.image = screencap_to_image(rect)
        self.text = text
        self.text_position = "bottom"
        self.text_rect = None

        self.can.register("draw", self._draw)
        self.can.set_blocks_mouse(True)
        self.can.register("mouse", self._mouse_event)
        self.can.register("key", self._key_event)
        self.can.register("focus", self._focus_event)
        self.can.set_focused(True)
        self.can.freeze()

    def destroy(self):
        self.can.close()

    def _calculate_result(self):
        raise NotImplementedError

    def _draw(self, canvas):
        canvas.draw_image(self.image, canvas.rect.x, canvas.rect.y)
        canvas.paint.color = "000000aa"
        canvas.draw_rect(canvas.rect)

        self._draw_widgets(canvas)

        self._draw_text(canvas)

    def _draw_widgets(self, canvas):
        pass

    def _draw_text(self, canvas):
        if not self.text:
            return

        paint = canvas.paint
        paint.color = "ffffffff"
        ((width, height), formatted_text) = layout_text(self.text, paint, 300)

        xpos = canvas.rect.x + (canvas.width - width - 20) / 2
        ypos = 10 + canvas.rect.y
        if self.text_position == "bottom":
            ypos = canvas.rect.y + canvas.height - height - 20 - 10
        self.text_rect = TalonRect(xpos, ypos, width + 20, height + 20)

        paint.color = "000000ff"
        paint.style = paint.Style.FILL
        thing = rrect.RoundRect.from_rect(
            self.text_rect,
            x=10,
            y=10,
            radii=(10, 10)
        )
        canvas.draw_rrect(thing)

        render_text(canvas, formatted_text, xpos + 10, ypos + 20)

    def _focus_event(self, focussed):
        if not focussed:
            self.destroy()
            self.result_handler(None)

    def _key_event(self, evt):
        if evt.event != "keyup":
            return

        if evt.key == "esc":
            self.destroy()
            self.result_handler(None)

        if evt.key == "return":
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

    def _calculate_result(self):
        return self.hl_region

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
            x,
            y,
            width,
            height
        )

    def _draw_widgets(self, canvas):
        super()._draw_widgets(canvas)

        if not self.hl_region:
            return
        canvas.save()
        canvas.clip_rect(self.hl_region, canvas.ClipOp.INTERSECT)
        canvas.draw_image(self.image, self.offsetx, self.offsety)
        canvas.restore()
        paint = canvas.paint
        paint.style = paint.Style.STROKE
        paint.color = 'ffffffff'
        canvas.draw_rect(self.hl_region)

    def _mouse_event(self, evt):
        super()._mouse_event(evt)

        if evt.event == "mousedown" and evt.button == 0:
            self.hl_region = TalonRect(evt.gpos.x, evt.gpos.y, 0, 0)
            self.is_selecting = True
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
            self.can.freeze()


class ImageSelectorOverlay(BoxSelectorOverlay):
    """
    Allows the user to select a region on the screen to use as an image for the locator API.
    """
    def __init__(self, *args, locate_threshold=0.9, **kwargs):
        super().__init__(*args, **kwargs)
        self.locate_threshold = locate_threshold
        self.offset_coord = None
        self.region_changed = True
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

    def _draw_widgets(self, canvas):
        super()._draw_widgets(canvas)
        if not self.hl_region:
            return

        # Draw other matching regions
        if not self.is_selecting:
            th = threading.Thread(target=self._find_matches, daemon=True)
            th.start()
            th.join(timeout=3)
            timed_out = th.is_alive()

            if timed_out or len(self.result_rects) > 20:
                # TODO: Show some text saying what happened
                self.offset_coord = None
                self.region_changed = True
                self.result_rects = []
                self.hl_region = None
                self.can.freeze()
                return
            else:
                self._draw_matches(canvas)

        # Draw the offset marker
        paint = canvas.paint
        paint.style = paint.Style.FILL
        paint.color = "ff00ffff"
        paint.set_stroke_width(1)
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
            canvas.draw_line(
                *self._get_region_centre(),
                *args
            )

        canvas.draw_circle(
            *args,
            2
        )

    def _get_region_centre(self):
        if self.hl_region:
            return (
                self.hl_region.x + self.hl_region.width / 2,
                self.hl_region.y + self.hl_region.height / 2
            )
        else:
            return None

    def _get_cropped_image(self):
        if self.hl_region is None:
            return None

        # I think make_subset does this more cleanly, but I don't know what the Talon API is
        region = self._get_region()
        xpos = region.x - self.offsetx
        ypos = region.y - self.offsety
        arr = np.array(self.image)[
            ypos:(ypos + region.height),
            xpos:(xpos + region.width),
        ]
        return image.Image.from_array(arr)

    def _find_matches(self):
        if self.region_changed:
            cropped_img = self._get_cropped_image()
            self.result_rects = locate.locate_in_image(
                self.image,
                cropped_img,
                threshold=self.locate_threshold
            )
            self.result_rects = [
                TalonRect(
                    rect.x + self.offsetx,
                    rect.y + self.offsety,
                    rect.width,
                    rect.height
                )
                for rect in self.result_rects
            ]
            self.region_changed = False

    def _draw_matches(self, canvas):
        paint = canvas.paint
        paint.color = "ff0000aa"
        paint.style = paint.Style.STROKE
        paint.set_stroke_width(1)
        for rect in self.result_rects:
            if rect == self._get_region():
                continue
            canvas.save()
            canvas.clip_rect(rect, canvas.ClipOp.INTERSECT)
            canvas.draw_image(self.image, self.offsetx, self.offsety)
            canvas.draw_rect(rect)
            canvas.restore()

    def _mouse_event(self, evt):
        super()._mouse_event(evt)

        if evt.event == "mousedown" and evt.button == 0:
            # Reset the coord when a new box is started
            self.offset_coord = None
            self.region_changed = True

        if evt.event == "mouseup" and evt.button == 1:
            self.offset_coord = evt.gpos
            self.can.freeze()
