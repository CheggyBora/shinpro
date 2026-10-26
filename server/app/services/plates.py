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
# Своя модель под российские номера (app/plate_ocr/README.md): общая не
# училась на них и путала регион. Лежит в коде — скачивать её неоткуда
import os as _os
RU_OCR_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                           'plate_ocr')
RU_OCR_MODEL = _os.path.join(RU_OCR_DIR, 'cct_s_v2_ru.onnx')
RU_OCR_CONFIG = _os.path.join(RU_OCR_DIR, 'cct_s_v2_ru_plate_config.yaml')

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


# Номера Беларуси и ближних стран СНГ (владелец, 26.10.2026). Их не
# правим под российский формат — возвращаем как прочитано, с пометкой
# страны: номер всё равно подтверждает человек на телефоне
FOREIGN = (
    ('BY', re.compile(r'^\d{4}[A-Z]{2}\d$')),              # 1234 AB-7
    ('KZ', re.compile(r'^\d{3}[A-Z]{2,3}\d{2}$')),         # 123 ABC 01
    ('TJ', re.compile(r'^\d{4}[A-Z]{2}\d{2}$')),           # 1234 AB 01
    ('UZ', re.compile(r'^\d{2}[A-Z]\d{3}[A-Z]{2}$')),      # 01 A 123 BC
    ('KG', re.compile(r'^\d{5}[A-Z]{3}$')),                # 01 123 ABC (и Узбекистан)
    ('AM', re.compile(r'^\d{2}[A-Z]{2}\d{3}$')),           # 12 AB 345 (и Азербайджан)
    ('GE', re.compile(r'^[A-Z]{2}\d{3}[A-Z]{2}$')),         # AB 123 CD
)
# Код страны, который модель иногда читает вместе с номером
_COUNTRY_CODE = re.compile(r'^(BY|KZ|TJ|UZ|KG|AM|AZ|GE)|(BY|KZ|TJ|UZ|KG|AM|AZ|GE)$')
# Ни на что не похож, но прочитан уверенно — тоже отдаём, пусть проверят
OTHER_MIN_CONFIDENCE = 0.85


def foreign_country(plate):
    """Код страны СНГ по виду номера, 'other' — не российский и не из списка, None — российский или пусто."""
    if not plate or is_valid(plate) or is_main_part(plate):
        return None
    text = _JUNK.sub('', str(plate).upper()).translate(_TO_LATIN)
    for country, pattern in FOREIGN:
        if pattern.match(text):
            return country
    return 'other'


def _foreign(full_text, full_conf):
    """Номер другой страны из прочитанного целиком: (номер, уверенность) или None."""
    text = _JUNK.sub('', str(full_text or '').upper()).translate(_TO_LATIN)
    for candidate in (text, _COUNTRY_CODE.sub('', text)):
        for _country, pattern in FOREIGN:
            if pattern.match(candidate):
                return normalize(candidate), round(full_conf, 3)
    if full_conf >= OTHER_MIN_CONFIDENCE and 5 <= len(text) <= 10 \
            and re.fullmatch(r'[A-Z0-9]+', text) \
            and sum(c.isdigit() for c in text) >= 2 and any(c.isalpha() for c in text):
        return normalize(text), round(full_conf, 3)
    return None


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

    # Беларусь и ближние страны: российские поправки тут исказили бы
    # номер, поэтому проверяем до того, как собирать его по частям
    foreign = _foreign(full_text, full_conf)
    if foreign is not None and not is_main_part(normalize(_latin(full_text))[:6]):
        return foreign

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
    # Российская модель, если её файлы на месте; иначе — общая
    own = _os.path.exists(RU_OCR_MODEL) and _os.path.exists(RU_OCR_CONFIG)
    ocr = (dict(ocr_model=None, ocr_model_path=RU_OCR_MODEL, ocr_config_path=RU_OCR_CONFIG)
           if own else dict(ocr_model=OCR_MODEL))
    engine = ALPR(detector_model=DETECTOR_MODEL, **ocr,
                  ocr_device='cpu',
                  detector_providers=['CPUExecutionProvider'],
                  ocr_providers=['CPUExecutionProvider'],
                  detector_sess_options=options, ocr_sess_options=options)
    log.info('plates: models loaded in %d ms (%s, OCR: %s)',
             (time.monotonic() - started) * 1000, root, 'ru' if own else 'global')
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


# Номер вырезаем из снимка покрупнее: на уменьшенном до MAX_SIDE кадре
# номер — сотня точек, а цифры региона — десяток, и модель их путает
CROP_SIDE = 3200


def _frame(image_bytes):
    """
    (кадр для поиска номера, крупный снимок для вырезки, во сколько раз
    крупный больше). Оба повёрнуты как на экране телефона.
    """
    import numpy as np
    from PIL import Image, ImageOps

    # Картинка на сотни мегапикселей влезает в несколько мегабайт PNG и
    # съела бы при разборе гигабайт памяти — такие не открываем
    Image.MAX_IMAGE_PIXELS = 60_000_000
    big = Image.open(io.BytesIO(image_bytes))
    big.draft('RGB', (CROP_SIDE, CROP_SIDE))      # JPEG уменьшается при чтении
    big = ImageOps.exif_transpose(big).convert('RGB')
    big.thumbnail((CROP_SIDE, CROP_SIDE))
    small = big.copy()
    small.thumbnail((MAX_SIDE, MAX_SIDE))
    scale = big.size[0] / small.size[0]
    return np.ascontiguousarray(np.asarray(small)[:, :, ::-1]), big, scale


def _read(alpr, shot):
    import numpy as np

    frame, big, scale = shot
    best = (None, 0.0)
    # Сначала самый крупный номер: снимают ту машину, что ближе, а на
    # заднем плане бывают соседние (проверка 26.10.2026: вместо Porsche
    # прочитался Mercedes за ним)
    def area(item):
        box = item.bounding_box
        return (box.x2 - box.x1) * (box.y2 - box.y1)

    found = sorted(alpr.detector.predict(frame), key=area, reverse=True)[:MAX_PLATES]

    for detection in found:
        if best[0] is not None:
            break       # ближняя машина прочиталась — соседние не нужны
        box = detection.bounding_box
        x1, y1, x2, y2 = int(box.x1), int(box.y1), int(box.x2), int(box.y2)
        if x2 - x1 < 8 or y2 - y1 < 4:
            continue
        # Чуть шире рамки детектора: без полей модель теряет крайние знаки.
        # Вырезаем из крупного снимка — точек в номере втрое больше
        pad_x, pad_y = (x2 - x1) * 0.04, (y2 - y1) * 0.08
        crop = np.asarray(big.crop((
            max(0, int((x1 - pad_x) * scale)), max(0, int((y1 - pad_y) * scale)),
            int((x2 + pad_x) * scale), int((y2 + pad_y) * scale))))[:, :, ::-1].copy()

        # Российская модель читает табличку целиком, с регионом. Чтения по
        # частям и голосование были нужны общей модели — российская на
        # обрезках не училась и только сбивалась бы
        full = alpr.ocr.predict(crop)
        if full is None:
            continue
        plate, confidence = pick(full.text, _mean(full.confidence))

        # Что прочитала модель — по журналу видно, где она ошибается
        log.info('plates raw: full=%s -> %s', full.text, plate or 'none')

        # Полный номер всегда лучше куска, даже менее уверенный
        better = (plate is not None and (
            best[0] is None
            or (is_valid(plate), confidence) > (is_valid(best[0]), best[1])))
        if better:
            best = (plate, confidence)
    return best


# Снимок разбирается одним потоком за раз: процессор у сервера на два
# ядра, и десяток одновременных снимков отнял бы его у всего остального
_one_at_a_time = threading.Semaphore(1)


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
    if not _one_at_a_time.acquire(timeout=20):
        log.warning('plates: busy, skipped')
        return None, 0.0
    try:
        return _recognize(alpr, image_bytes)
    finally:
        _one_at_a_time.release()


def _recognize(alpr, image_bytes):
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


