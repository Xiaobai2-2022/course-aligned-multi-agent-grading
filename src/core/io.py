from pathlib import Path
from typing import List, Union, Optional
from PIL import Image
import pdf2image

def read_prompt(
        prompt_path: Union[str, Path]
) -> str:

    path = Path(prompt_path)

    if not path.is_file():
        raise FileNotFoundError(f"Prompt file '{path}' not found.")

    prompt = path.read_text(encoding="utf-8").strip()

    if not prompt:
        raise ValueError(f"Prompt file '{path}' is empty.")

    return prompt



def pdf_to_image(
        pdf_path: Union[str, Path],
        dpi: int = 200,
        max_pages: Optional[int] = None,
        out_dir: Optional[Union[str, Path]] = None,
        fmt: str = "png"
) -> List[Image.Image]:

    in_path = Path(pdf_path)

    if not in_path.is_file():
        raise FileNotFoundError(f"PDF file '{in_path}' not found.")

    if max_pages is not None and max_pages < 1:
        raise ValueError("max_pages must be at least 1.")

    images = pdf2image.convert_from_path(
        in_path,
        dpi=dpi,
        last_page=max_pages if max_pages else None
    )

    if out_dir:
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        stem = in_path.stem

        for i, image in enumerate(images, start=1):
            image.save(out_path / f"{stem}_page_{i}.{fmt}", format=fmt.upper())

    return images



def image_to_messages(
    images: List[Image.Image],
    prompt: str,
) -> List[dict]:

    content = []

    for page_number, img in enumerate(images, start=1):
        content.extend([
            {"type": "text", "text": f"Page {page_number}"},
            {"type": "image", "image": img},
        ])

    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": content},
    ]
