from pathlib import Path
from typing import List, Optional, Union, Any
from io import BytesIO
from PIL import Image
import pdf2image
import base64
import json

from .log import log_fail, log_info, log_success, log_warning


def read_prompt(
        prompt_path: Union[str, Path]
) -> str:
    """
    Read a prompt file and return its content

    :param prompt_path: The path to the prompt file
    :return: The prompt content
    """

    path = Path(prompt_path)
    log_info(f"Reading prompt: {path}")

    try:
        if not path.is_file():
            raise FileNotFoundError(f"Prompt file '{path}' not found.")

        prompt = path.read_text(encoding="utf-8").strip()
        if not prompt:
            raise ValueError(f"Prompt file '{path}' is empty.")
    except (OSError, UnicodeError, ValueError) as exc:
        log_fail(f"Failed to read prompt '{path}': {exc}")
        raise

    log_success(f"Prompt loaded successfully: {len(prompt)} characters")
    return prompt



def pdf_to_image(
    pdf_path: Union[str, Path],
    dpi: int = 200,
    max_pages: Optional[int] = None,
    out_dir: Optional[Union[str, Path]] = None,
    fmt: str = "png",
) -> List[Image.Image]:
    """
    Convert a PDF file to a PIL image

    :param pdf_path: The path to the PDF file
    :param dpi: The DPI of the output image
    :param max_pages: The maximum number of pages to generate
    :param out_dir: The directory to save the images to (optional)
    :param fmt: The format of the output image (optional)
    :return:
    """

    in_path = Path(pdf_path)
    log_info(f"Converting PDF to images: {in_path}")
    log_info(f"DPI: {dpi}")

    try:
        if not in_path.is_file():
            raise FileNotFoundError(f"PDF file '{in_path}' not found.")
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be at least 1.")

        if max_pages is not None:
            log_warning(
                f"Processing at most {max_pages} pages; later pages will be excluded."
            )

        images = pdf2image.convert_from_path(
            in_path,
            dpi=dpi,
            last_page=max_pages,
        )
        log_info(f"Rendered {len(images)} page images")

        if out_dir:
            out_path = Path(out_dir)
            out_path.mkdir(parents=True, exist_ok=True)
            log_info(f"Saving page images to: {out_path}")

            for i, image in enumerate(images, start=1):
                image_path = out_path / f"{in_path.stem}_page_{i}.{fmt}"
                image.save(image_path, format=fmt.upper())
                log_info(f"Saved page {i}: {image_path}")
    except Exception as exc:
        # Log conversion or saving failures, then preserve the original error.
        log_fail(f"Failed to process PDF '{in_path}': {exc}")
        raise

    if not images:
        log_warning(f"No page images were produced for '{in_path}'.")
    else:
        log_success(f"PDF processing complete: {len(images)} page images")
    return images



def image_to_messages(
    images: List[Image.Image],
    prompt: str,
) -> List[dict]:
    """
    Constructs a message with image

    :param images: The images to include in the message
    :param prompt: The prompt text message
    :return:
    """

    log_info(f"Building LLM messages from {len(images)} page images")

    if not images:
        log_fail("No page images supplied.")
        raise ValueError("At least one page image is required.")

    if not prompt.strip():
        log_warning("The system prompt is empty or contains only whitespace.")

    content = []

    for page_number, img in enumerate(images, start=1):
        try:
            with BytesIO() as buffer:
                img.convert("RGB").save(buffer, format="PNG")
                encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

            content.extend([
                {"type": "text", "text": f"Page {page_number}"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{encoded}",
                    },
                },
            ])
        except Exception as exc:
            log_fail(f"Failed to encode page {page_number}: {exc}")
            raise

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": content},
    ]

    log_success(
        f"Built {len(messages)} messages containing {len(images)} page images"
    )
    return messages



def write_json(
    data: Any,
    json_path: str | Path
) -> Path:
    """
    Writes data to a JSON file

    :param data: the data to write
    :param json_path: the path to the JSON file
    :return: the path to the JSON file
    """

    try:
        if not isinstance(json_path, (str, Path)):
            raise TypeError("json_path must be a string or Path.")

        if isinstance(json_path, str) and not json_path.strip():
            raise ValueError("json_path must not be empty.")

        path = Path(json_path)

        if path.is_dir():
            raise IsADirectoryError(f"Output path is a directory: {path}")

        log_info(f"Writing JSON: {path}")

        content = json.dumps(
            data,
            indent=4,
            ensure_ascii=False,
            allow_nan=False,
        )

        encoded = (content + "\n").encode("utf-8")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)

    except (TypeError, ValueError, OSError, RecursionError) as exc:
        log_fail(f"Failed to write JSON to {json_path!r}: {exc}")
        raise

    log_success(f"JSON saved successfully: {path}")
    return path



def read_json(json_path: str | Path) -> dict:
    """
    Read a JSON file with double encoded JSON format

    :param json_path: the path to the JSON file
    :return: the given packet
    """
    path = Path(json_path)
    log_info(f"Reading JSON: {path}")

    try:
        with path.open("r", encoding="utf-8") as file:
            rubric = json.load(file)

        if isinstance(rubric, str):
            log_warning("Double-encoded JSON detected; decoding once more.")
            rubric = json.loads(rubric)

        if not isinstance(rubric, dict):
            raise ValueError("The JSON root must be an object.")

    except (OSError, UnicodeError, ValueError) as exc:
        log_fail(f"Failed to read JSON '{path}': {exc}")
        raise

    log_success("JSON loaded successfully.")
    return rubric
