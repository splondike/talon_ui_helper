import os
import datetime

from talon import Module, actions

from .overlays import ImageSelectorOverlay
from .mouse_helper import get_image_template_directory


mod = Module()


def save_image_template(image):
    """
    Saves the given image to the image templates folder and returns the generated name.58
    """

    unique_filename = \
        str(datetime.datetime.now().date()) + '_' + \
        str(datetime.datetime.now().time()).replace(':', '.') + \
        ".png"

    templates_directory = get_image_template_directory()
    full_filename = os.path.join(templates_directory, unique_filename)

    if not os.path.exists(templates_directory):
        os.mkdir(templates_directory)

    image.write_file(full_filename)

    return unique_filename


def handle_image_click_builder(result):
    """
    Result handler for the image click command builder.
    """
    if result is None:
        return

    filename = save_image_template(result["image"])
    index = result["index"]

    offset_bit = ""
    if result["offset"]:
        offset_bit = ", ".join([""] + list(map(lambda x: str(int(x)), result["offset"])))

    command = "\n".join([
        "",
        ":",
        "    user.mouse_helper_position_save()",
        f'    user.mouse_helper_move_image_relative("{filename}", {index}{offset_bit})',
        "    sleep(0.05)",
        "    mouse_click(0)",
        "    sleep(0.05)",
        "    user.mouse_helper_position_restore()",
    ])
    actions.clip.set_text(command)
    actions.app.notify("Copied new command to clipboard")


@mod.action_class
class CommandWizardActions:
    """
    Actions related to the command builder wizard.
    """

    def command_wizard_show():
        """
        Brings up the command wizard UI
        """

        ImageSelectorOverlay(
            handle_image_click_builder,
            text=(
                "Select a region of the screen to use in your voice command "
                "then press enter to confirm your selection. Press escape to cancel.\n\n"
                "After selecting and before enter, optionally right click to define an "
                "offset from the selected region. This will be clicked instead of the "
                "center of the region."
            )
        )
