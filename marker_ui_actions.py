"""
Exposes the Marker UI and associated functionality as actions.
"""

from typing import List

from talon import Module, Context, actions
from talon.types import Rect as TalonRect

from .marker_ui import MarkerUi


mod = Module()
mod.tag("marker_ui_showing", desc="The marker UI labels are showing")
setting_labels = mod.setting(
    "marker_ui_labels",
    type=str,
    desc="Space separated labels to use in the marker UI. See also marker_ui_label capture if overwriting.",
    default=" ".join("abcdefghijklmnopqrstuvwxyz0123456789")
)

ctx = Context()

marker_ui = None


@mod.capture(rule="<user.letter> | <user.number>")
def marker_ui_label(m) -> str:
    """
    Capture for the labels used in the marker UI. See also marker_ui_labels setting if you want
    to override it.
    """

    return str(m)


@mod.action_class
class MarkerUiActions:
    """
    Actions related to showing, hiding, and using the marker UI interface.
    """

    def marker_ui_show(rects: List[TalonRect]):
        """
        Shows the given markers in the Marker UI. They can then be clicked or moved
        to using other actions in this class.
        """

        global marker_ui

        if marker_ui is not None:
            marker_ui.destroy()

        markers = [
            MarkerUi.Marker(
                rect,
                label
            )
            for rect, label in zip(rects, setting_labels.get().split(" "))
        ]

        marker_ui = MarkerUi(markers)

        marker_ui.show()
        ctx.tags = ["user.marker_ui_showing"]

    def marker_ui_hide():
        """
        Hides any visible marker UI
        """

        global marker_ui

        if marker_ui is not None:
            marker_ui.destroy()

        marker_ui = None
        ctx.tags = []

    def marker_ui_mouse_move(label: str):
        """
        Moves the mouse cursor to the label corresponding to the given label
        """

        global marker_ui

        if marker_ui is None:
            return

        rect = marker_ui.find_rect(label)

        if rect is None:
            return

        actions.mouse_move(
            rect.x + rect.width / 2,
            rect.y + rect.height / 2,
        )
