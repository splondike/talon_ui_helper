"""
Useful actions related to moving the mouse
"""

import os
import math
import subprocess
from typing import Union

from talon import actions, ui, clip, screen, Module
from talon.types import Rect as TalonRect
from talon.experimental import locate


mod = Module()
setting_template_directory = mod.setting(
    "mouse_helper_template_directory",
    type=str,
    desc=(
        "The folder that templated images are saved to."
        " Defaults to image_templates in your user folder"
    ),
    default=None
)


def get_image_template_directory():
    """
    Gets the full path to the directory where template images are stored.
    """

    maybe_value = setting_template_directory.get()
    if maybe_value:
        return maybe_value
    else:
        return os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            "../image_templates"
        )


def find_active_window_rect() -> TalonRect:
    return ui.active_window().rect


def calculate_relative(modifier: str, start: int, end: int) -> int:
    """
    Helper method for settings. Lets you specify numbers relative to a
    range. For example:

        calculate_relative("-10", 0, 100) == 90
        calculate_relative("10", 0, 100) == 10
        calculate_relative("-0", 0, 100) == 100
    """
    if modifier.startswith("-"):
        modifier_ = int(modifier[1:])
        rel_end = True
    elif modifier == ".":
        # In the middle
        return (end + start) // 2
    else:
        modifier_ = int(modifier)
        rel_end = False

    if rel_end:
        return end - modifier_
    else:
        return start + modifier_


saved_mouse_pos = None


@mod.action_class
class MouseActions:
    def mouse_helper_position_save():
        """
        Saves the mouse position to a global variable
        """

        global saved_mouse_pos

        saved_mouse_pos = (actions.mouse_x(), actions.mouse_y())

    def mouse_helper_position_restore():
        """
        Restores a saved mouse position
        """

        if saved_mouse_pos is None:
            return

        actions.mouse_move(
            saved_mouse_pos[0],
            saved_mouse_pos[1]
        )

    def mouse_helper_move_active_window_relative(xpos: str, ypos: str):
        """
        Positions the mouse relative to the active window
        """

        rect = find_active_window_rect()

        actions.mouse_move(
            calculate_relative(xpos, 0, rect.width) + rect.x,
            calculate_relative(ypos, 0, rect.height) + rect.y,
        )

    def mouse_helper_move_relative(xdelta: int, ydelta: int):
        """
        Moves the mouse relative to its current position
        """

        new_xpos = actions.mouse_x() + xdelta
        new_ypos = actions.mouse_y() + ydelta
        actions.mouse_move(new_xpos, new_ypos)

    def mouse_helper_move_image_relative(
        template_path: str,
        disambiguator: Union[int, str]=0,
        xoffset: int=0,
        yoffset: int=0,
        region: Union[str, TalonRect]="screen"
    ):
        """
        Moves the mouse relative to the template image given in template_path.

        :param template_path: Filename of the image to find. Can be an absolute path or
            if no '/' or '\\' character is specified, it is relative to the image
            templates directory.
        :param disambiguator: If there are multiple matches, use this to indicate
            which one you want to match. Matches are ordered left to right top to
            bottom. If disambiguator is an integer then it's just an index into that list.
            If it's the string "mouse" then it's the next match in the region to the right
            and down from the mouse after shifting back the offset amount and up and left
            half the size and width of the template. If it is "mouse_cycle" then if there
            are no further matches it will attempt to start from the top of the screen again.
            This is useful for iterating through rows in a table for example.
        :param xoffset: Amount to shift in the x direction relative to the
            center of the template.
        :param yoffset: Amount to shift in the y direction relative to the
            center of the template.
        :param region: The region to search for the template in. One of "screen", "window",
            Rect() for the whole currently active monitor, the currently active window,
            and a Talon Rect() instance respectively.
        """

        if region == "screen":
            active_window = ui.active_window()
            if active_window.id == -1:
                rect = ui.main_screen().rect
            else:
                rect = active_window.screen.rect
        elif region == "window":
            rect = find_active_window_rect()
        else:
            rect = region

        if os.pathsep in template_path:
            # Absolute path specified
            template_file = template_path
        else:
            # Filename in image templates directory specified
            template_file = os.path.join(get_image_template_directory(), template_path)

        matches = locate.locate(
            template_file,
            rect=rect
        )

        sorted_matches = sorted(
            matches,
            key=lambda m: (m.x, m.y)
        )

        if len(sorted_matches) == 0:
            return

        if disambiguator in ("mouse", "mouse_cycle"):
            # TODO: Say why ceil is needed
            xnorm = math.ceil(actions.mouse_x() - xoffset - sorted_matches[0].width / 2)
            ynorm = math.ceil(actions.mouse_y() - yoffset - sorted_matches[0].height / 2)
            filtered_matches = [
                match
                for match in sorted_matches
                if (match.y == ynorm and match.x > xnorm) or match.y > ynorm
            ]
            print(len(sorted_matches), len(filtered_matches), xnorm, ynorm, sorted_matches, filtered_matches)

            if len(filtered_matches) > 0:
                match_rect = filtered_matches[0]
            elif disambiguator == "mouse_cycle":
                match_rect = sorted_matches[0]
            else:
                return
        else:
            if len(matches) <= disambiguator:
                return

            match_rect = sorted_matches[disambiguator]

        actions.mouse_move(
            math.ceil(rect.x + match_rect.x + (match_rect.width / 2) + xoffset),
            math.ceil(rect.y + match_rect.y + (match_rect.height / 2) + yoffset),
        )
