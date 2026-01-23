"""
Florence-2 Test Script (GPU)

RTX 3060 Ti (8GB) — отлично для Florence-2

Модели:
- microsoft/Florence-2-base (~0.5GB, 232M params) — быстрее
- microsoft/Florence-2-large (~1.5GB, 770M params) — точнее

Задачи:
- <CAPTION> — краткое описание
- <DETAILED_CAPTION> — подробное описание
- <MORE_DETAILED_CAPTION> — очень подробное
- <OCR> — распознавание текста
- <OD> — object detection

Источники:
- https://huggingface.co/microsoft/Florence-2-base
- https://huggingface.co/docs/transformers/en/model_doc/florence2
"""

import os
import sys
import time
import io
from pathlib import Path

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Проверяем зависимости
try:
    import torch
    from PIL import Image
    from transformers import AutoProcessor, Florence2ForConditionalGeneration
except ImportError as e:
    print(f"Установи: pip install torch torchvision transformers pillow")
    print(f"Ошибка: {e}")
    sys.exit(1)


# === КОНФИГ ===
MODEL_ID = "florence-community/Florence-2-base"  # native transformers version

# GPU setup (согласно официальной документации)
DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"
DTYPE = torch.float16 if torch.cuda.is_available() else torch.float32

print(f"Device: {DEVICE}")
print(f"Dtype: {DTYPE}")
print(f"Model: {MODEL_ID}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name(0)}")
    print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
print()


def load_model():
    """Загружает Florence-2 модель на GPU."""
    print("Загрузка модели...")
    start = time.time()

    # Официальный способ загрузки (HuggingFace docs)
    processor = AutoProcessor.from_pretrained(MODEL_ID)

    model = Florence2ForConditionalGeneration.from_pretrained(
        MODEL_ID,
        torch_dtype=DTYPE
    ).to(DEVICE)

    elapsed = time.time() - start
    print(f"Модель загружена за {elapsed:.1f}s")

    # Показываем использование VRAM
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated(0) / 1024**3
        print(f"VRAM used: {allocated:.2f} GB")

    return processor, model


def analyze_image(processor, model, image_path: str, task: str = "<CAPTION>"):
    """
    Анализирует изображение.

    Tasks:
        <CAPTION> — краткое описание
        <DETAILED_CAPTION> — подробное описание
        <MORE_DETAILED_CAPTION> — очень подробное
        <OCR> — текст на изображении
        <OD> — object detection (bboxes)
    """
    # Загружаем изображение
    image = Image.open(image_path).convert("RGB")

    # Подготавливаем inputs
    inputs = processor(text=task, images=image, return_tensors="pt")

    # Переносим на device
    input_ids = inputs["input_ids"].to(DEVICE)
    pixel_values = inputs["pixel_values"].to(DEVICE, DTYPE)

    # Генерация
    start = time.time()

    with torch.no_grad():
        generated_ids = model.generate(
            input_ids=input_ids,
            pixel_values=pixel_values,
            max_new_tokens=512,
            do_sample=False
        )

    elapsed = time.time() - start

    # Декодируем результат
    generated_text = processor.batch_decode(generated_ids, skip_special_tokens=False)[0]

    # Парсим результат (Florence-2 возвращает специальный формат)
    parsed = processor.post_process_generation(
        generated_text,
        task=task,
        image_size=(image.width, image.height)
    )

    return parsed, elapsed


def main():
    # Загружаем модель
    processor, model = load_model()
    print()

    # Находим тестовые изображения
    test_dir = Path(__file__).parent
    images = list(test_dir.glob("*.jpg")) + list(test_dir.glob("*.png"))

    if not images:
        print("Нет изображений для теста!")
        return

    print(f"Найдено {len(images)} изображений")
    print("=" * 60)

    total_time = 0
    total_tasks = 0

    # Тестируем каждое изображение
    for img_path in images:
        print(f"\n[IMG] {img_path.name}")
        print("-" * 40)

        # Разные задачи
        for task in ["<CAPTION>", "<DETAILED_CAPTION>", "<OCR>"]:
            try:
                result, elapsed = analyze_image(processor, model, str(img_path), task)
                total_time += elapsed
                total_tasks += 1

                task_name = task.strip("<>")
                output = result.get(task, result)

                # Форматируем вывод
                if isinstance(output, str):
                    text = output[:200] + "..." if len(output) > 200 else output
                elif isinstance(output, dict):
                    text = str(output)[:200]
                else:
                    text = str(output)[:200]

                print(f"  {task_name}: {text}")
                print(f"  TIME: {elapsed:.2f}s")

            except Exception as e:
                print(f"  {task}: ERROR - {e}")

        print()

    # Итоги
    if total_tasks > 0:
        print("=" * 60)
        print(f"ИТОГО: {total_tasks} задач за {total_time:.1f}s")
        print(f"Среднее время: {total_time/total_tasks:.2f}s на задачу")


if __name__ == "__main__":
    main()
