"""
Florence-2 Vision Module v1.0

Анализ изображений с каналов для улучшения классификации.
- florence-community/Florence-2-base (native transformers)
- GPU: RTX 3060 Ti, 0.44 GB VRAM, ~0.6s per image
- Tasks: CAPTION (описание) + OCR (текст/тикеры)
"""

import io
import time
from typing import List, Optional
from dataclasses import dataclass

import torch
from PIL import Image
from transformers import AutoProcessor, Florence2ForConditionalGeneration

MODEL_ID = "florence-community/Florence-2-base"
DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"
DTYPE = torch.float16 if torch.cuda.is_available() else torch.float32

_processor = None
_model = None


@dataclass
class ImageAnalysis:
    """Результат анализа изображения."""
    caption: str
    ocr_text: str
    analysis_time: float


def _load_model():
    """Загружает Florence-2 модель на GPU (один раз)."""
    global _processor, _model
    if _model is not None:
        return _processor, _model

    print("Loading Florence-2 model...")
    start = time.time()

    _processor = AutoProcessor.from_pretrained(MODEL_ID)
    _model = Florence2ForConditionalGeneration.from_pretrained(
        MODEL_ID, torch_dtype=DTYPE
    ).to(DEVICE)

    elapsed = time.time() - start
    vram = torch.cuda.memory_allocated(0) / 1024**3 if torch.cuda.is_available() else 0
    print(f"Florence-2 loaded in {elapsed:.1f}s, VRAM: {vram:.2f} GB")
    return _processor, _model


def unload_model():
    """Выгружает модель из GPU памяти."""
    global _processor, _model
    _model = None
    _processor = None
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print("Florence-2 unloaded")


def analyze_image(image_bytes: bytes) -> Optional[ImageAnalysis]:
    """
    Анализирует изображение: CAPTION + OCR.

    Args:
        image_bytes: Изображение в байтах (JPEG/PNG)

    Returns:
        ImageAnalysis с caption и ocr_text, или None при ошибке
    """
    try:
        processor, model = _load_model()
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

        start = time.time()
        results = {}

        for task in ["<CAPTION>", "<OCR>"]:
            inputs = processor(text=task, images=image, return_tensors="pt")
            input_ids = inputs["input_ids"].to(DEVICE)
            pixel_values = inputs["pixel_values"].to(DEVICE, DTYPE)

            with torch.no_grad():
                generated_ids = model.generate(
                    input_ids=input_ids,
                    pixel_values=pixel_values,
                    max_new_tokens=256,
                    do_sample=False
                )

            text = processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
            parsed = processor.post_process_generation(text, task=task, image_size=image.size)
            results[task.strip("<>")] = parsed.get(task, "")

        return ImageAnalysis(
            caption=results.get("CAPTION", ""),
            ocr_text=results.get("OCR", ""),
            analysis_time=time.time() - start
        )
    except Exception as e:
        print(f"Vision error: {e}")
        return None


def analyze_images_batch(images: List[bytes], max_images: int = 10) -> List[ImageAnalysis]:
    """
    Анализирует пакет изображений.

    Args:
        images: Список изображений в байтах
        max_images: Максимум изображений для анализа

    Returns:
        Список ImageAnalysis
    """
    results = []
    for img_bytes in images[:max_images]:
        analysis = analyze_image(img_bytes)
        if analysis:
            results.append(analysis)
    return results


def format_for_prompt(analyses: List[ImageAnalysis]) -> str:
    """
    Форматирует результаты анализа для добавления в промпт классификатора.

    Returns:
        Строка вида:
        Image analysis:
        [1] Scene: A trading chart. Text: BTC -4.20%
        [2] Scene: A man in suit. Text: (none)
    """
    if not analyses:
        return ""
    lines = ["Image analysis:"]
    for i, a in enumerate(analyses, 1):
        caption = a.caption[:100] if a.caption else "(no description)"
        ocr = a.ocr_text[:100] if a.ocr_text else "(none)"
        lines.append(f"[{i}] Scene: {caption}. Text: {ocr}")
    return "\n".join(lines)
