"""
Номер машины с фотографии (docs/order_photo.md).

Распознаём на своём сервере, без облака: снимки машин клиентов никуда
больше не уходят. Сервер слабый — два ядра, около полутора гигабайт
свободной памяти, без видеокарты, — поэтому взяты маленькие модели
ONNX из fast-alpr:

  · поиск номера на снимке — yolo-v9-t-384 (open-image-models), ~8 МБ;
  · чтение — cct-s-v2-global (fast-plate-ocr), ~5 МБ, латиница и цифры.

Обе в памяти процесса занимают около 140 МБ, снимок разбирается за
десятые доли секунды. Загружаются один раз на процесс, при первом
снимке; веса скачиваются при первом запуске в PLATE_MODEL_DIR (папка
должна быть доступна службе на запись — см. app/config.py).

Отдельной модели под российские номера у fast-plate-ocr нет: модель
«global» учена на номерах многих стран, России среди них нет. Буквы
российского номера — только те, что выглядят как латинские
(АВЕКМНОРСТУХ), поэтому читаем латиницей и переводим в кириллицу, а
результат проверяем по формату. Регион модель читает хуже основной
части — поэтому номер читается ещё и по частям: основная часть слева,
регион справа.

Распознавание — подсказка, а не условие: нет библиотеки, нет весов,
снимок не прочитался — возвращаем (None, 0), и номер вписывают руками.
"""
import io
import logging
import re
import threading
import time

from app.config import settings

log = logging.getLogger('tire_server')

DETECTOR_MODEL = 'yolo-v9-t-384-license-plate-end2end'
OCR_MODEL = 'cct-s-v2-global-model'

# Больше этого по длинной стороне не нужно: номер на снимке машины с
# двух-трёх метров остаётся в сотни точек шириной, а 12-мегапиксельный
# кадр с телефона разбирался бы впятеро дольше и съедал бы память
MAX_SIDE = 1280

# Сколько найденных номеров читаем: на снимке бывает и соседняя машина
MAX_PLATES = 3

# Буквы, которые бывают на российском номере, — и латиница, на них похожая
LETTERS = 'АВЕКМНОРСТУХ'
_LATIN = 'ABEKMHOPCTYX'
_TO_CYRILLIC = str.maketrans(_LATIN, LETTERS)
_TO_LATIN = str.maketrans(LETTERS, _LATIN)

_JUNK = re.compile(r'[\s\-_.,/\\|·]+')

L = f'[{LETTERS}]'
# Регион: две цифры (не 00) или три, и трёхзначные начинаются с 1, 7
# или 9 (102, 777, 977). Без этого «АВ123477» читался бы как такси
# с регионом 477, а это прицеп с регионом 77
REGION = r'(?:(?!00)\d{2}|[179]\d{2})$'
FORMATS = (
    # А123ВВ77, А123ВВ777 — обычный
    ('standard', re.compile(rf'^{L}(?!000)\d{{3}}{L}{{2}}{REGION}')),
    # АВ12377 — такси
    ('taxi', re.compile(rf'^{L}{{2}}(?!000)\d{{3}}{REGION}')),
    # АВ123477 — прицеп
    ('trailer', re.compile(rf'^{L}{{2}}(?!0000)\d{{4}}{REGION}')),
)
_MAIN = re.compile(rf'^{L}(?!000)\d{{3}}{L}{{2}}$')

# Что модель путает в позиции буквы и в позиции цифры
_DIGIT_AS_LETTER = {'0': 'O', '8': 'B', '4': 'A', '7': 'T', '1': 'T', '6': 'B'}
_LETTER_AS_DIGIT = {'O': '0', 'D': '0', 'Q': '0', 'U': '0', 'B': '8', 'Z': '2',
                    'S': '5', 'I': '1', 'L': '1', 'J': '1', 'T': '7', 'A': '4',
                    'G': '6', 'E': '3'}


def normalize(text):
    """
    «a123вв 77», «A123BB777» -> «А123ВВ777».

    Латиница, похожая на кириллицу, становится кириллицей: на номере
    других букв не бывает, а с телефона и из модели приходит латиница.
    Прочие буквы не трогаем — их отсеет проверка формата.
    """
    if not text:
        return ''
    return _JUNK.sub('', str(text).strip().upper()).translate(_TO_CYRILLIC)


def plate_format(plate):
    """Какой это номер: standard, taxi, trailer. Не российский — None."""
    plate = normalize(plate)
    for name, pattern in FORMATS:
        if pattern.match(plate):
            return name
    return None


def is_valid(plate):
    return plate_format(plate) is not None


def is_main_part(plate):
    """«А123ВВ» — номер без региона."""
    return bool(_MAIN.match(normalize(plate)))


# ----------------------------------------------------------------------
# Разбор того, что прочитала модель
# ----------------------------------------------------------------------

def _latin(text):
    """Текст модели в латинице, без мусора и хвоста «RUS»."""
    text = _JUNK.sub('', str(text or '').upper()).translate(_TO_LATIN)
    return re.sub(r'R?U?S$', '', text) if len(text) > 8 else text


def _fix_standard(text):
    """
    Поправить буквы и цифры по их местам в обычном номере: 0 на месте
    буквы — это О, В на месте цифры — 8. Только для обычного формата:
    у такси и прицепа места другие, а гадать там опаснее, чем не трогать.
    """
    if len(text) not in (8, 9):
        return text
    out = []
    for index, char in enumerate(text):
        letter_place = index in (0, 4, 5)
        if letter_place and char.isdigit():
            char = _DIGIT_AS_LETTER.get(char, char)
        elif not letter_place and not char.isdigit():
            char = _LETTER_AS_DIGIT.get(char, char)
        out.append(char)
    return ''.join(out)


def _fix_main(text):
    """Основная часть: Б ЦЦЦ ББ — те же поправки по местам."""
    if len(text) != 6:
        return text
    return _fix_standard(text + '00')[:6]


def _region(text):
    """Регион из правой части номера: первые две-три цифры."""
    digits = ''.join(_LETTER_AS_DIGIT.get(char, char) for char in _latin(text))
    match = re.match(r'^(\d{2,3})', digits)
    if not match:
        return ''
    region = match.group(1)
    # Трёхзначные регионы начинаются с 1, 7 или 9 (102, 777, 977).
    # Иначе третья цифра — скорее всего, кусок «RUS» или рамки
    if len(region) == 3 and region[0] not in '179':
        region = region[:2]
    return region


def _mean(values):
    if isinstance(values, (int, float)):
        return float(values)
    values = [float(value) for value in (values or [])]
    return sum(values) / len(values) if values else 0.0


def pick(full_text, full_conf, main_text=None, main_conf=0.0,
         region_text=None, region_conf=0.0):
    """
    Лучший номер из прочитанного целиком и по частям: (номер, уверенность).

    Целиком прочитанный номер верен, если сходится с форматом. Если нет —
    собираем из основной части и региона. Если не читается и регион —
    отдаём основную часть без региона: дописать две цифры быстрее, чем
    весь номер, а в базе по ней часто находится машина целиком.
    """
    full = normalize(_fix_standard(_latin(full_text)))
    main = normalize(_fix_main(_latin(main_text)[:6])) if main_text else ''
    if not is_main_part(main):
        main = normalize(_fix_main(_latin(full_text)[:6]))
        main_conf = full_conf
    region = _region(region_text) if region_text else ''

    if is_valid(full):
        # Регион мелкий, и целиком модель теряет в нём цифру: «977»
        # читает как «77». Отдельно прочитанный трёхзначный регион, в
        # котором есть те же две цифры, — вернее (проверка 26.10.2026)
        short = full[6:]
        if plate_format(full) == 'standard' and len(short) == 2 and len(region) == 3 \
                and short in region:
            longer = (main if is_main_part(main) else full[:6]) + region
            if is_valid(longer):
                return longer, round(min(full_conf, region_conf), 3)
        # Целиком и по частям прочитали по-разному — верим частям: на
        # основной части модель ошибается реже, чем на всём номере
        if is_main_part(main) and plate_format(full) == 'standard' \
                and full[:6] != main and region:
            joined = main + region
            if is_valid(joined):
                return joined, round(min(main_conf, region_conf), 3)
        return full, round(full_conf, 3)

    if is_main_part(main):
        if region and is_valid(main + region):
            return main + region, round(min(main_conf, region_conf), 3)
        return main, round(main_conf * 0.5, 3)

    return None, 0.0


# ----------------------------------------------------------------------
# Модель
# ----------------------------------------------------------------------

_lock = threading.Lock()
_engine = None
_engine_failed_at = None

# Не загрузилось — пробуем снова не чаще раза в десять минут: иначе
# каждый снимок ждал бы неудачной загрузки, а сеть могла и вернуться
RETRY_SECONDS = 600


def model_dir():
    return settings.PLATE_MODEL_DIR


def _load():
    """
    Загрузить модели. Веса — в PLATE_MODEL_DIR, а не в ~/.cache: у
    службы домашней папки нет (ProtectHome), а рабочая папка сервера
    ей доступна на запись.
    """
    import pathlib

    import onnxruntime as ort
    import fast_plate_ocr.inference.hub as ocr_hub
    import open_image_models.detection.core.hub as detector_hub

    root = pathlib.Path(model_dir())
    root.mkdir(parents=True, exist_ok=True)
    ocr_hub.MODEL_CACHE_DIR = root / 'fast-plate-ocr'
    detector_hub.MODEL_CACHE_DIR = root / 'open-image-models'

    from fast_alpr import ALPR

    # Два потока на снимок: ядер на сервере два, и рабочих процессов
    # тоже два — больше потоков только толкались бы друг с другом
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1

    started = time.monotonic()
    engine = ALPR(detector_model=DETECTOR_MODEL, ocr_model=OCR_MODEL,
                  ocr_device='cpu',
                  detector_providers=['CPUExecutionProvider'],
                  ocr_providers=['CPUExecutionProvider'],
                  detector_sess_options=options, ocr_sess_options=options)
    log.info('plates: models loaded in %d ms (%s)',
             (time.monotonic() - started) * 1000, root)
    return engine


def engine():
    """Модели этого процесса. Нет библиотеки или весов — None."""
    global _engine, _engine_failed_at

    if not settings.PLATES_ENABLED:
        return None
    if _engine is not None:
        return _engine
    if _engine_failed_at is not None and \
            time.monotonic() - _engine_failed_at < RETRY_SECONDS:
        return None

    with _lock:
        if _engine is not None:
            return _engine
        try:
            _engine = _load()
            _engine_failed_at = None
        except Exception as e:      # нет библиотеки, нет сети, битые веса
            _engine_failed_at = time.monotonic()
            log.warning('Распознавание номеров недоступно: %s', e)
            return None
    return _engine


def _frame(image_bytes):
    """Снимок в массив BGR, уменьшенный, повёрнутый как на экране телефона."""
    import numpy as np
    from PIL import Image, ImageOps

    image = Image.open(io.BytesIO(image_bytes))
    image.draft('RGB', (MAX_SIDE, MAX_SIDE))      # JPEG уменьшается при чтении
    image = ImageOps.exif_transpose(image).convert('RGB')
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    return np.ascontiguousarray(np.asarray(image)[:, :, ::-1])


def _read(alpr, frame):
    best = (None, 0.0)
    found = sorted(alpr.detector.predict(frame),
                   key=lambda item: item.confidence, reverse=True)[:MAX_PLATES]

    for detection in found:
        box = detection.bounding_box
        x1, y1, x2, y2 = int(box.x1), int(box.y1), int(box.x2), int(box.y2)
        if x2 - x1 < 8 or y2 - y1 < 4:
            continue
        # Чуть шире рамки детектора: без полей модель теряет крайние знаки
        pad_x, pad_y = int((x2 - x1) * 0.04), int((y2 - y1) * 0.08)
        crop = frame[max(0, y1 - pad_y):y2 + pad_y, max(0, x1 - pad_x):x2 + pad_x]
        width, height = crop.shape[1], crop.shape[0]

        full = alpr.ocr.predict(crop)
        main = alpr.ocr.predict(crop[:, :int(width * 0.78)])
        region = alpr.ocr.predict(crop[:int(height * 0.75), int(width * 0.76):])
        if full is None:
            continue

        plate, confidence = pick(
            full.text, _mean(full.confidence),
            main.text if main else None, _mean(main.confidence) if main else 0.0,
            region.text if region else None,
            _mean(region.confidence) if region else 0.0)
        # Что модель увидела каждым способом — по журналу видно, где
        # она ошибается на настоящих снимках
        log.info('plates raw: full=%s main=%s region=%s -> %s',
                 full.text, main.text if main else '-',
                 region.text if region else '-', plate or 'none')

        # Полный номер всегда лучше куска, даже менее уверенный
        better = (plate is not None and (
            best[0] is None
            or (is_valid(plate), confidence) > (is_valid(best[0]), best[1])))
        if better:
            best = (plate, confidence)
    return best


def recognize(image_bytes):
    """
    (номер или None, уверенность от 0 до 1).

    Номер — в кириллице, «А123ВВ777». Если не прочитался регион — только
    основная часть, «А123ВВ», с уверенностью вдвое ниже. Любой сбой —
    (None, 0): поле останется пустым, и номер впишут руками.
    """
    if not image_bytes:
        return None, 0.0

    alpr = engine()
    if alpr is None:
        return None, 0.0

    started = time.monotonic()
    try:
        frame = _frame(image_bytes)
        plate, confidence = _read(alpr, frame)
        # Строка для журнала после раскатки: по ней смотрят, сколько
        # длится распознавание на сервере и что оно читает
        log.info('plates: %s in %d ms (confidence %.2f)', plate or 'none',
                 (time.monotonic() - started) * 1000, confidence)
        return plate, confidence
    except Exception as e:
        log.warning('plates: none in %d ms (error: %s)',
                    (time.monotonic() - started) * 1000, e)
        return None, 0.0


def warm_up():
    """Скачать веса и загрузить модели заранее. True — готово."""
    return engine() is not None


