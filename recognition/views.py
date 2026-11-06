import base64
import json
import math
import re
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.shortcuts import render
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from recipes.models import Ingredient
from recipes.ingredient_utils import normalize_ingredient_name

from .models import DetectedIngredient, RecognitionSession


XKIRO_API_URL = 'https://api.xkiro.com/v1/chat/completions'
XKIRO_MODELS_URL = 'https://api.xkiro.com/v1/models'
DEFAULT_XKIRO_MODEL = 'qwen/qwen3-vl-plus:free'
FALLBACK_XKIRO_VISION_MODELS = (
    'qwen/qwen3-vl-plus:free',
    'qwen/qwen3-vl-plus',
    'qwen/qwen3.6-plus:free',
    'qwen/qwen3.7-plus:free',
)
GROQ_API_URL = XKIRO_API_URL
DEFAULT_GROQ_MODEL = DEFAULT_XKIRO_MODEL
COORDINATE_SCALE = 1000
MIN_DETECTION_CONFIDENCE = 0.55
VIETNAMESE_LABELS = {
    'Akabare Khursani': 'Ớt Akabare',
    'Apple': 'Táo',
    'Artichoke': 'Atiso',
    'Ash Gourd -Kubhindo-': 'Bầu bí',
    'Asparagus -Kurilo-': 'Măng tây',
    'Avocado': 'Bơ',
    'Bacon': 'Thịt xông khói',
    'Bamboo Shoots -Tama-': 'Măng tre',
    'Banana': 'Chuối',
    'Beans': 'Đậu',
    'Beaten Rice -Chiura-': 'Cơm tẻ xay',
    'Beef': 'Thịt bò',
    'Beetroot': 'Củ dền',
    'Bethu ko Saag': 'Rau Bethu',
    'Bitter Gourd': 'Mướp đắng',
    'Black Lentils': 'Đậu lăng đen',
    'Black beans': 'Đậu đen',
    'Bottle Gourd -Lauka-': 'Bầu nước',
    'Bread': 'Bánh mì',
    'Brinjal': 'Cà tím',
    'Broad Beans -Bakullo-': 'Đậu rộng',
    'Broccoli': 'Bông cải xanh',
    'Buff Meat': 'Thịt trâu',
    'Butter': 'Bơ',
    'Cabbage': 'Bắp cải',
    'Capsicum': 'Ớt chuông',
    'Carrot': 'Cà rốt',
    'Cassava -Ghar Tarul-': 'Sắn',
    'Cauliflower': 'Bông cải trắng',
    'Chayote-iskus-': 'Su su',
    'Cheese': 'Phô mai',
    'Chicken': 'Thịt gà',
    'Chicken Gizzards': 'Mật gà',
    'Chickpeas': 'Đậu gà',
    'Chili Pepper -Khursani-': 'Ớt chili',
    'Chili Powder': 'Bột ớt',
    'Chowmein Noodles': 'Mì Chowmein',
    'Cinnamon': 'Quế',
    'Coriander -Dhaniya-': 'Rau mùi',
    'Corn': 'Ngô',
    'Cornflakec': 'Ngũ cốc ngô',
    'Crab Meat': 'Thịt cua',
    'Cucumber': 'Dưa chuột',
    'Egg': 'Trứng',
    'Farsi ko Munta': 'Mướp Farsi',
    'Fiddlehead Ferns -Niguro-': 'Rau dương xỉ',
    'Fish': 'Cá',
    'Garden Peas': 'Đậu Hà Lan',
    'Garden cress-Chamsur ko saag-': 'Rau mùi tự nhiên',
    'Garlic': 'Tỏi',
    'Ginger': 'Gừng',
    'Green Brinjal': 'Cà tím xanh',
    'Green Lentils': 'Đậu lăng xanh',
    'Green Mint -Pudina-': 'Bạc hà xanh',
    'Green Peas': 'Đậu xanh',
    'Green Soyabean -Hariyo Bhatmas-': 'Đậu nành xanh',
    'Gundruk': 'Rau Gundruk',
    'Ham': 'Thịt nguội',
    'Ice': 'Đá',
    'Jack Fruit': 'Mít',
    'Ketchup': 'Sốt cà chua',
    'Lapsi -Nepali Hog Plum-': 'Lapsi',
    'Lemon -Nimbu-': 'Chanh',
    'Lime -Kagati-': 'Chanh ta',
    'Long Beans -Bodi-': 'Đậu đũa',
    'Masyaura': 'Masyaura',
    'Milk': 'Sữa',
    'Minced Meat': 'Thịt băm',
    'Moringa Leaves -Sajyun ko Munta-': 'Lá chùm ngây',
    'Mushroom': 'Nấm',
    'Mutton': 'Thịt cừu',
    'Nutrela -Soya Chunks-': 'Đậu nành khô',
    'Okra -Bhindi-': 'Đậu bắp',
    'Olive Oil': 'Dầu ô liu',
    'Onion': 'Hành tây',
    'Onion Leaves': 'Lá hành',
    'Orange': 'Cam',
    'Palak -Indian Spinach-': 'Bạc hà Ấn Độ',
    'Palungo -Nepali Spinach-': 'Rau chân vịt',
    'Paneer': 'Phô mai tươi',
    'Papaya': 'Đu đủ',
    'Pea': 'Đậu Hà Lan',
    'Pear': 'Lê',
    'Pointed Gourd -Chuche Karela-': 'Mướp khía',
    'Pork': 'Thịt lợn',
    'Potato': 'Khoai tây',
    'Pumpkin -Farsi-': 'Bí đỏ',
    'Radish': 'Củ cải',
    'Rahar ko Daal': 'Đậu lăng đỏ',
    'Rayo ko Saag': 'Rau cải ngựa',
    'Red Beans': 'Đậu đỏ',
    'Red Lentils': 'Đậu lăng đỏ',
    'Rice -Chamal-': 'Gạo',
    'Sajjyun -Moringa Drumsticks-': 'Măng chùm ngây',
    'Salt': 'Muối',
    'Sausage': 'Xúc xích',
    'Snake Gourd -Chichindo-': 'Mướp rắn',
    'Soy Sauce': 'Nước tương',
    'Soyabean -Bhatmas-': 'Đậu nành',
    'Sponge Gourd -Ghiraula-': 'Mướp xương',
    'Stinging Nettle -Sisnu-': 'Cây gai',
    'Strawberry': 'Dâu tây',
    'Sugar': 'Đường',
    'Sweet Potato -Suthuni-': 'Khoai lang',
    'Taro Leaves -Karkalo-': 'Lá khoai môn',
    'Taro Root-Pidalu-': 'Củ khoai môn',
    'Thukpa Noodles': 'Mì Thukpa',
    'Tofu': 'Đậu phụ',
    'Tomato': 'Cà chua',
    'Tori ko Saag': 'Rau Tori',
    'Tree Tomato -Rukh Tamatar-': 'Cà chua cây',
    'Turnip': 'Củ cải trắng',
    'Wallnut': 'Hạt óc chó',
    'Water Melon': 'Dưa hấu',
    'Wheat': 'Lúa mì',
    'Yellow Lentils': 'Đậu lăng vàng',
    'kimchi': 'Kimchi',
    'mayonnaise': 'Mayonnaise',
    'noodle': 'Mì',
    'seaweed': 'Rong biển',
    'onions': 'Hành tây',
    'tomatoes': 'Cà chua',
    'carrots': 'Cà rốt',
    'potatoes': 'Khoai tây',
    'cucumbers': 'Dưa chuột',
    'bell pepper': 'Ớt chuông',
    'bell peppers': 'Ớt chuông',
}


def _label_name(name):
    if name is None:
        return 'Unknown'
    raw_name = str(name).strip()
    if not raw_name:
        return 'Unknown'
    normalized = ' '.join(raw_name.replace('_', ' ').split())
    labels_by_key = {key.casefold(): value for key, value in VIETNAMESE_LABELS.items()}
    return labels_by_key.get(raw_name.casefold(), labels_by_key.get(normalized.casefold(), normalized))


def _label_font(size):
    font_candidates = (
        Path('C:/Windows/Fonts/arial.ttf'),
        Path(ImageFont.__file__).parent / 'fonts' / 'DejaVuSans.ttf',
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        Path('/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf'),
    )
    for font_path in font_candidates:
        if font_path.exists():
            return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.load_default()


DETECTION_COLORS = (
    '#E53935',
    '#1E88E5',
    '#2E7D32',
    '#FB8C00',
    '#8E24AA',
    '#00897B',
    '#D81B60',
    '#3949AB',
    '#6D4C41',
)


def _find_label_bounds(
    left,
    top,
    right,
    bottom,
    label_width,
    label_height,
    image_width,
    image_height,
    occupied_bounds,
):
    clamped_left = max(0, min(image_width - label_width, left))
    clamped_right = max(0, min(image_width - label_width, right - label_width))
    clamped_center = max(
        0,
        min(image_width - label_width, (left + right - label_width) // 2),
    )
    horizontal_positions = []
    for candidate_x in (
        clamped_left,
        clamped_center,
        clamped_right,
        max(0, min(image_width - label_width, left + 6)),
        max(0, min(image_width - label_width, right - label_width - 6)),
    ):
        if candidate_x not in horizontal_positions:
            horizontal_positions.append(candidate_x)

    vertical_positions = []
    for candidate_y in (
        top - label_height - 2,
        top + 2,
        top + label_height + 4,
        (top + bottom - label_height) // 2,
        bottom - label_height - 2,
        bottom + 2,
    ):
        if candidate_y not in vertical_positions:
            vertical_positions.append(candidate_y)

    fallback = None
    fallback_overlap_area = None
    for y in vertical_positions:
        if not 0 <= y <= image_height - label_height:
            continue
        for x in horizontal_positions:
            if not 0 <= x <= image_width - label_width:
                continue
            bounds = (x, y, x + label_width, y + label_height)
            overlap_area = sum(
                max(0, min(bounds[2], other[2]) - max(bounds[0], other[0]))
                * max(0, min(bounds[3], other[3]) - max(bounds[1], other[1]))
                for other in occupied_bounds
            )
            if overlap_area == 0:
                return bounds
            if (
                fallback_overlap_area is None
                or overlap_area < fallback_overlap_area
            ):
                fallback = bounds
                fallback_overlap_area = overlap_area

    return fallback


def _discover_xkiro_vision_models(api_key):
    request = Request(
        XKIRO_MODELS_URL,
        headers={
            'Authorization': f'Bearer {api_key}',
            'User-Agent': 'food-recommendation/1.0',
        },
        method='GET',
    )
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except Exception:
        return []

    items = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []

    model_ids = [
        item.get('id')
        for item in items
        if isinstance(item, dict) and isinstance(item.get('id'), str)
    ]
    preferred_keywords = ('vl', 'vision', 'qwen3.6', 'qwen3.7', 'gemini', 'gpt-4o')
    discovered = []
    for keyword in preferred_keywords:
        for model_id in model_ids:
            if keyword in model_id.lower() and model_id not in discovered:
                discovered.append(model_id)
    return discovered


def _candidate_xkiro_models():
    configured_xkiro = getattr(settings, 'XKIRO_MODEL', '')
    configured_groq = getattr(settings, 'GROQ_MODEL', '')
    groq_defaults = {
        'meta-llama/llama-4-scout-17b-16e-instruct',
        'llama-3.3-70b-versatile',
        'llama-3.1-8b-instant',
        'qwen/qwen3.8-27b',
    }
    candidates = []
    for item in (
        configured_xkiro,
        configured_groq if configured_groq not in groq_defaults else '',
        *FALLBACK_XKIRO_VISION_MODELS,
    ):
        if (
            isinstance(item, str)
            and item.strip()
            and item.strip() != 'qwen/qwen3.8-27b'
            and item.strip() not in candidates
        ):
            candidates.append(item.strip())
    if not candidates:
        candidates.append(DEFAULT_XKIRO_MODEL)
    return candidates


def _xkiro_ingredients(image_bytes, image_format):
    api_key = (
        getattr(settings, 'XKIRO_API_KEY', '')
        or getattr(settings, 'GROQ_API_KEY', '')
    )
    if not api_key:
        raise ValueError(
            'Chưa cấu hình XKIRO_API_KEY (hoặc GROQ_API_KEY) trên máy chủ.'
        )

    mime_type = {
        'JPEG': 'image/jpeg',
        'JPG': 'image/jpeg',
        'MPO': 'image/jpeg',
        'PNG': 'image/png',
        'WEBP': 'image/webp',
    }.get(image_format)
    if mime_type is None:
        raise ValueError('Định dạng ảnh không được hỗ trợ.')

    image_url = (
        f'data:{mime_type};base64,'
        f'{base64.b64encode(image_bytes).decode("ascii")}'
    )
    prompt = (
        'Inspect the image carefully and detect all distinct food ingredients '
        'that are visibly present. Ignore plates, bowls, baskets, utensils, '
        'table surfaces, and watermarks. Use a short, accurate Vietnamese '
        'ingredient name (for example: cà rốt, thịt gà, hành lá, lá chanh, '
        'tỏi, gừng, hành tím, nấm đùi gà, nấm hương, nấm kim châm). '
        'For each distinct ingredient type, return ONE tight 2D bounding box '
        'that encloses the entire visible group/pile/cluster of that '
        'ingredient in the image. Use standard 2D grounding coordinates '
        '"bbox_2d": [xmin, ymin, xmax, ymax] normalized from 0 to 1000 '
        '(where xmin, xmax are horizontal from left=0 to right=1000, and '
        'ymin, ymax are vertical from top=0 to bottom=1000). Double-check '
        'that each ingredient name matches the exact visual region inside its '
        'bbox_2d (for example, white enoki mushrooms = nấm kim châm, brown '
        'shiitake caps = nấm hương, thick white stems with brown caps = '
        'nấm đùi gà). Return only a JSON object with an "ingredients" array: '
        '{"ingredients":[{"name":"...","confidence":0.95,"bbox_2d":[xmin,ymin,xmax,ymax]}]}. '
        'Do not include markdown or any text outside the JSON.'
    )
    api_url = getattr(settings, 'XKIRO_API_URL', XKIRO_API_URL) or XKIRO_API_URL
    models_to_try = _candidate_xkiro_models()
    discovered_checked = False
    api_response = None

    index = 0
    while index < len(models_to_try):
        model = models_to_try[index]
        index += 1
        payload = {
            'model': model,
            'messages': [{
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': prompt},
                    {'type': 'image_url', 'image_url': {'url': image_url}},
                ],
            }],
            'temperature': 0,
            'max_completion_tokens': 2048,
            'response_format': {'type': 'json_object'},
        }
        request = Request(
            api_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
                'User-Agent': 'food-recommendation/1.0',
            },
            method='POST',
        )

        try:
            with urlopen(request, timeout=60) as response:
                api_response = json.loads(response.read().decode('utf-8'))
            break
        except HTTPError as error:
            response_text = error.read().decode('utf-8', errors='replace').strip()
            retryable_codes = (400, 404, 408, 422, 429, 500, 502, 503, 504)
            if error.code in retryable_codes and not discovered_checked and index == len(models_to_try):
                discovered_checked = True
                for discovered_model in _discover_xkiro_vision_models(api_key):
                    if discovered_model not in models_to_try:
                        models_to_try.append(discovered_model)
            if error.code in retryable_codes and index < len(models_to_try):
                continue

            error_message = response_text
            try:
                error_body = json.loads(response_text)
            except json.JSONDecodeError:
                error_body = None

            if isinstance(error_body, dict):
                api_error = error_body.get('error')
                if isinstance(api_error, dict):
                    error_message = (
                        api_error.get('message')
                        or error_body.get('message')
                        or error_body.get('detail')
                        or response_text
                    )
                elif isinstance(api_error, str):
                    error_message = api_error
                else:
                    error_message = (
                        error_body.get('message')
                        or error_body.get('detail')
                        or response_text
                    )

            if not isinstance(error_message, str) or not error_message:
                error_message = str(error.reason or 'Phản hồi không có nội dung.')
            error_message = error_message.replace(api_key, '[đã ẩn]')
            request_id = error.headers.get('x-request-id') if error.headers else None
            cf_ray = error.headers.get('cf-ray') if error.headers else None
            diagnostics = f'HTTP {error.code}: {error_message[:500]}'
            if request_id:
                diagnostics += f' (request ID: {request_id})'
            if cf_ray:
                diagnostics += f' (Cloudflare Ray ID: {cf_ray})'
            raise ValueError(
                f'xKiro API từ chối yêu cầu ({diagnostics})'
            ) from error
        except (URLError, TimeoutError) as error:
            raise ValueError('Không thể kết nối tới xKiro API.') from error
        except json.JSONDecodeError as error:
            raise ValueError('xKiro API trả về phản hồi không hợp lệ.') from error

    try:
        content = api_response['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError('xKiro API không trả về nội dung nhận diện.') from error
    if not isinstance(content, str):
        raise ValueError('xKiro API trả về nội dung nhận diện không hợp lệ.')

    content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
    if content.startswith('```'):
        content = content.split('\n', 1)[-1]
        if content.endswith('```'):
            content = content[:-3].strip()

    try:
        result = json.loads(content)
    except json.JSONDecodeError as error:
        start = content.find('{')
        end = content.rfind('}')
        if start != -1 and end > start:
            try:
                result = json.loads(content[start:end + 1])
            except json.JSONDecodeError:
                raise ValueError(
                    'xKiro API trả về JSON nhận diện không hợp lệ.'
                ) from error
        else:
            raise ValueError(
                'xKiro API trả về JSON nhận diện không hợp lệ.'
            ) from error
    ingredients = result.get('ingredients') if isinstance(result, dict) else None
    if not isinstance(ingredients, list):
        raise ValueError('xKiro API không trả về danh sách nguyên liệu.')
    return ingredients


_groq_ingredients = _xkiro_ingredients


def _detect_ingredients(uploaded_file):
    try:
        image = Image.open(uploaded_file)
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError('Tệp tải lên không phải là ảnh hợp lệ.') from error

    image_format = image.format
    try:
        image = ImageOps.exif_transpose(image)
    except Exception:
        pass
    image = image.convert('RGB')
    if max(image.size) > 1600:
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        buf = BytesIO()
        image.save(buf, format='JPEG', quality=88)
        image_bytes = buf.getvalue()
        image_format = 'JPEG'
    else:
        uploaded_file.seek(0)
        image_bytes = uploaded_file.read()
    width, height = image.size
    ingredients = _xkiro_ingredients(image_bytes, image_format)

    line_width = max(2, round(min(width, height) * 0.005))
    grouped = {}
    for ingredient in ingredients:
        if not isinstance(ingredient, dict):
            raise ValueError('xKiro API trả về một nguyên liệu không hợp lệ.')
        name = ingredient.get('name')
        bbox_2d = ingredient.get('bbox_2d') or ingredient.get('box_2d')
        box = bbox_2d if bbox_2d is not None else ingredient.get('box')
        is_xyxy = bbox_2d is not None
        confidence = ingredient.get('confidence')
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(box, list)
            or len(box) != 4
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise ValueError('xKiro API trả về dữ liệu nguyên liệu không hợp lệ.')

        if any(
            isinstance(coordinate, bool)
            or not isinstance(coordinate, (int, float))
            or not math.isfinite(coordinate)
            or not 0 <= coordinate <= COORDINATE_SCALE
            for coordinate in box
        ):
            raise ValueError('xKiro API trả về tọa độ khung không hợp lệ.')

        if is_xyxy:
            xmin, ymin, xmax, ymax = box
        else:
            ymin, xmin, ymax, xmax = box
        if ymin >= ymax or xmin >= xmax:
            raise ValueError('xKiro API trả về khung nhận diện không hợp lệ.')
        if confidence < MIN_DETECTION_CONFIDENCE:
            continue
        left = round(xmin * (width - 1) / COORDINATE_SCALE)
        top = round(ymin * (height - 1) / COORDINATE_SCALE)
        right = round(xmax * (width - 1) / COORDINATE_SCALE)
        bottom = round(ymax * (height - 1) / COORDINATE_SCALE)
        vietnamese_name = _label_name(name)
        group_key = vietnamese_name.casefold()
        candidate = {
            'name': vietnamese_name,
            'left': left,
            'top': top,
            'right': right,
            'bottom': bottom,
            'confidence': confidence,
        }
        current = grouped.get(group_key)
        candidate_area = (right - left) * (bottom - top)
        current_area = (
            (current['right'] - current['left'])
            * (current['bottom'] - current['top'])
            if current else None
        )
        if (
            current is None
            or confidence > current['confidence']
            or (
                confidence == current['confidence']
                and candidate_area > current_area
            )
        ):
            grouped[group_key] = candidate

    font = _label_font(max(12, round(min(width, height) * 0.032)))
    draw = ImageDraw.Draw(image)
    occupied_label_bounds = []
    grouped_items = list(grouped.values())
    for idx, group in enumerate(grouped_items):
        color = DETECTION_COLORS[idx % len(DETECTION_COLORS)]
        group['color'] = color
        bounds = (group['left'], group['top'], group['right'], group['bottom'])
        draw.rectangle(bounds, outline=color, width=line_width)
    for group in grouped_items:
        color = group['color']
        text_box = draw.textbbox(
            (0, 0),
            group['name'],
            font=font,
            stroke_width=0,
        )
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        padding = 5
        label_bounds = _find_label_bounds(
            group['left'],
            group['top'],
            group['right'],
            group['bottom'],
            text_width + padding * 2,
            text_height + padding * 2,
            width,
            height,
            occupied_label_bounds,
        )
        if label_bounds is None:
            continue
        draw.rectangle(label_bounds, fill=color)
        occupied_label_bounds.append(label_bounds)
        draw.text(
            (
                label_bounds[0] + padding - text_box[0],
                label_bounds[1] + padding - text_box[1],
            ),
            group['name'],
            fill='white',
            font=font,
        )

    detections = [
        {
            'name': group['name'],
            'confidence': round(group['confidence'] * 100),
        }
        for group in grouped.values()
    ]

    output = BytesIO()
    image.save(output, format='JPEG', quality=90)
    output_path = default_storage.save(
        f'uploads/detection_{uploaded_file.name.rsplit(".", 1)[0]}.jpg',
        ContentFile(output.getvalue()),
    )
    return detections, default_storage.url(output_path), output_path


def _save_detection_results(session, detections):
    ingredients = list(
        Ingredient.objects.filter(dang_su_dung=True)
        .only('id', 'ten_thuc_pham', 'ten_chuan_hoa')
    )
    ingredient_by_name = {}
    for ingredient in ingredients:
        ingredient_by_name.setdefault(
            normalize_ingredient_name(ingredient.ten_chuan_hoa),
            ingredient,
        )
    for ingredient in ingredients:
        ingredient_by_name.setdefault(
            normalize_ingredient_name(ingredient.ten_thuc_pham),
            ingredient,
        )

    with transaction.atomic():
        DetectedIngredient.objects.bulk_create([
            DetectedIngredient(
                phien_nhan_dien=session,
                thuc_pham=ingredient_by_name.get(
                    normalize_ingredient_name(detection['name'])
                ),
                ten_da_nhan_dien=detection['name'],
                do_tin_cay=Decimal(str(detection['confidence'])) / Decimal('100'),
            )
            for detection in detections
        ])
        session.trang_thai = 'thanh_cong'
        session.save(update_fields=['trang_thai'])


def get_active_recognition_session(request, require_success=False):
    session_id = request.session.get('last_recognition_session_id')
    session = None
    if session_id is not None:
        filters = {'pk': session_id}
        if require_success:
            filters['trang_thai'] = 'thanh_cong'
        session = RecognitionSession.objects.filter(**filters).first()
        if session is not None and request.user.is_authenticated:
            if session.user_id is None:
                session.user = request.user
                session.save(update_fields=['user'])
            elif session.user_id != request.user.id:
                session = None

    if session is None and request.user.is_authenticated:
        user_filters = {'user': request.user}
        if require_success:
            user_filters['trang_thai'] = 'thanh_cong'
        session = (
            RecognitionSession.objects.filter(**user_filters)
            .order_by('-ngay_tao', '-id')
            .first()
        )
        if session is not None:
            request.session['last_recognition_session_id'] = session.pk
    return session


def detect(request):
    context = {'detections': [], 'image_url': None, 'error': None}
    if request.method == 'POST':
        uploaded_file = request.FILES.get('image')
        if not uploaded_file:
            context['error'] = 'Vui lòng chọn một ảnh để nhận diện.'
        else:
            request.session.pop('last_recognition_session_id', None)
            uploaded_file.seek(0)
            session = RecognitionSession.objects.create(
                user=request.user if request.user.is_authenticated else None,
                anh_dau_vao=uploaded_file,
            )
            uploaded_file.seek(0)
            try:
                (
                    context['detections'],
                    context['image_url'],
                    processed_image_path,
                ) = _detect_ingredients(uploaded_file)
            except ValueError as error:
                session.trang_thai = 'that_bai'
                session.save(update_fields=['trang_thai'])
                context['error'] = str(error)
            else:
                session.anh_da_xu_ly.name = processed_image_path
                session.save(update_fields=['anh_da_xu_ly'])
                _save_detection_results(session, context['detections'])
                request.session['last_recognition_session_id'] = session.pk
                request.session.pop('recommendation_error', None)
                context['recognition_session_id'] = session.pk
                context['can_recommend'] = True
    else:
        session = get_active_recognition_session(request, require_success=True)
        if session is not None:
            image = session.anh_da_xu_ly or session.anh_dau_vao
            context['image_url'] = image.url
            context['detections'] = [
                {'name': detection.ten_da_nhan_dien}
                for detection in DetectedIngredient.objects.filter(
                    phien_nhan_dien=session
                ).order_by('id')
            ]
            context['recognition_session_id'] = session.pk
            context['can_recommend'] = True
    return render(request, 'detect.html', context)
