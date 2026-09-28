import base64
import os
from io import BytesIO

from dotenv import load_dotenv
from openai import OpenAI
from PIL import ImageGrab
from tools.computer_observer import ComputerObserver

load_dotenv()


class ScreenVision:
    """Analyze the current screen using a multimodal vision model."""

    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")

        if not api_key:
            raise ValueError("GROQ_API_KEY is not set.")

        self.client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=api_key,
        )

        self.model = "qwen/qwen3.8-27b"

        self.locate_model = "qwen/qwen3.8-27b"

    def capture_screen(self):
        screenshot = ImageGrab.grab()

        output = BytesIO()
        screenshot.convert("RGB").save(
            output,
            format="JPEG",
            quality=85,
        )

        return output.getvalue()

    def analyze(self, question: str):
        observer = ComputerObserver()
        screen_state = observer.get_screen_state()
        image_bytes = self.capture_screen()

        encoded_image = base64.b64encode(
            image_bytes
        ).decode("utf-8")

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are JARVIS's visual observation system. "
                        "Your job is to report only information that can be "
                        "directly verified from the supplied screenshot. "
                        "Never guess, infer hidden information, or invent "
                        "filenames, paths, applications, UI elements, or text. "
                        "If the requested information cannot be read clearly "
                        "from the screenshot, return UNKNOWN. "
                        "Answer only the user's specific question. "
                        "Be concise and factual."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"{question}\n\n"
                                "Here is deterministic information obtained directly "
                                "from the Windows computer observer:\n"
                                f"{screen_state}\n\n"
                                "Use this computer-state information when it directly "
                                "answers the question. Use the screenshot only for "
                                "information that cannot be obtained from the computer "
                                "observer.\n\n"
                                "Only report information supported by either the "
                                "computer-state data or the screenshot. "
                                "Never guess or invent filenames, paths, applications, "
                                "UI elements, or text. "
                                "If the requested information cannot be verified clearly, "
                                "return UNKNOWN. "
                                "Be concise and factual."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": (
                                    "data:image/jpeg;base64,"
                                    f"{encoded_image}"
                                ),
                            },
                        },
                    ],
                },
            ],
            max_completion_tokens=256,
            reasoning_effort="none",
        )

        return response.choices[0].message.content.strip()

    def locate(self, question: str):
        """
        Locate something visible and return its screen coordinates.

        Deterministic ground-truth is provided so the model answers in
        a verifiable coordinate frame instead of hallucinating.
        """

        observer = ComputerObserver()
        screen_state = observer.get_screen_state()

        image = ImageGrab.grab()
        width, height = image.size

        output = BytesIO()
        image.convert("RGB").save(output, format="JPEG", quality=85)

        encoded_image = base64.b64encode(output.getvalue()).decode("utf-8")

        # ------------------------------------------------
        # PASS 1: coarse grid cell
        # ------------------------------------------------
        grid_prompt = f"""{question}

This image is a screenshot of the user's screen ({width}x{height} pixels).
The screen is divided into a grid: 3 rows and 4 columns.
Row 1 is the top, column 1 is the left.

In which grid cell is the described item? If it spans cells, pick the
cell containing its center. If it is not visible, return exactly
UNKNOWN. Otherwise return ONLY:

{{"row": <1-3>, "col": <1-4>}}
"""

        cell = self._vision_json(
            self.locate_model,
            grid_prompt,
            encoded_image,
        )

        if (
            not isinstance(cell, dict)
            or "row" not in cell
            or "col" not in cell
        ):
            return {
                "success": False,
                "error": "I couldn't find that on the screen.",
            }

        try:
            row = int(cell["row"])
            col = int(cell["col"])
        except (TypeError, ValueError):
            return {
                "success": False,
                "error": "I couldn't find that on the screen.",
            }

        if not (1 <= row <= 3 and 1 <= col <= 4):
            return {
                "success": False,
                "error": "I couldn't find that on the screen.",
            }

        # ------------------------------------------------
        # PASS 2: zoom into the cell and refine
        # ------------------------------------------------
        cell_w = width // 4
        cell_h = height // 3

        margin = 40

        left = max(0, (col - 1) * cell_w - margin)
        top = max(0, (row - 1) * cell_h - margin)
        right = min(width, col * cell_w + margin)
        bottom = min(height, row * cell_h + margin)

        crop = image.crop((left, top, right, bottom))

        scale = 2

        crop = crop.resize(
            (crop.width * scale, crop.height * scale)
        )

        crop_output = BytesIO()
        crop.convert("RGB").save(crop_output, format="JPEG", quality=90)

        crop_encoded = base64.b64encode(
            crop_output.getvalue()
        ).decode("utf-8")

        crop_prompt = f"""{question}

This image is a zoomed-in crop from the user's screen. It is exactly
{crop.width}x{crop.height} pixels, counted from the TOP-LEFT corner.

Report the pixel coordinates of the CENTER of the described item within
THIS image. If it is not visible in this crop, return exactly UNKNOWN.
Otherwise return ONLY:

{{"x": <center_x>, "y": <center_y>}}
"""

        point = self._vision_json(
            self.locate_model,
            crop_prompt,
            crop_encoded,
        )

        if (
            not isinstance(point, dict)
            or not isinstance(point.get("x"), int)
            or not isinstance(point.get("y"), int)
        ):
            return {
                "success": False,
                "error": "I couldn't locate that on the screen.",
            }

        x = left + int(point["x"]) // scale
        y = top + int(point["y"]) // scale

        x = max(0, min(width - 1, x))
        y = max(0, min(height - 1, y))

        return {
            "success": True,
            "x": x,
            "y": y,
            "width": width,
            "height": height,
        }

    def _vision_json(self, model: str, prompt: str, encoded_image: str):
        """Send one vision request and parse a JSON object reply."""

        import json
        import re

        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": (
                                    "data:image/jpeg;base64,"
                                    f"{encoded_image}"
                                )
                            },
                        },
                    ],
                },
            ],
            max_completion_tokens=64,
            temperature=0.0,
        )

        text = response.choices[0].message.content.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[^\}]*\}", text, re.DOTALL)

            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    return None

            return None