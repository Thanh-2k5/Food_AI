import json
import math
import re
import time
import zlib
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import quote

from django.conf import settings
from django.db.models import Q
from django.db import transaction

from recognition.models import (
    DetectedIngredient,
    RecognitionSession,
    Recommendation,
)

from .ingredient_utils import (
    canonical_ingredient_name,
    normalize_ingredient_name,
)
from .models import Ingredient, Recipe, RecipeIngredient


GROQ_API_URL = 'https://api.groq.com/openai/v1/chat/completions'
GROQ_MODELS_URL = 'https://api.groq.com/openai/v1/models'
XKIRO_API_URL = 'https://api.xkiro.com/v1/chat/completions'
XKIRO_MODELS_URL = 'https://api.xkiro.com/v1/models'
DEFAULT_GROQ_RECIPE_MODEL = 'llama-3.3-70b-versatile'
FALLBACK_GROQ_RECIPE_MODELS = (
    'llama-3.3-70b-versatile',
    'llama-3.1-8b-instant',
)
FALLBACK_XKIRO_RECIPE_MODELS = (
    'deepseek/deepseek-v4.1-flash:free',
    'qwen/qwen3.6-plus:free',
    'qwen/qwen3.7-plus:free',
    'qwen/qwen-plus-2025-07-28:free',
    'qwen/qwen3-vl-plus:free',
)
DEPRECATED_RECIPE_MODELS = {
    'meta-llama/llama-4-scout-17b-16e-instruct',
    'qwen/qwen3.8-27b',
}
RETRYABLE_HTTP_CODES = {400, 401, 403, 404, 408, 422, 429, 500, 502, 503, 504}
MIN_RECOMMENDATIONS = 3
MAX_AI_RECIPES = 4
MINIMUM_DATABASE_RECIPE_MATCH_PERCENT = 70
MINIMUM_IMAGE_WORD_OVERLAP = 3
GROQ_MAX_503_RETRIES = 3
GROQ_RETRY_BASE_SECONDS = 1
GROQ_RETRY_MAX_SECONDS = 30
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
DEFAULT_AI_IMAGE_MODEL = 'flux'
DEFAULT_AI_IMAGE_URL_TEMPLATE = (
    'https://tse2.mm.bing.net/th?q={prompt}&w=800&h=600&c=7&rs=1&p=0'
)


def _recipe_similarity_score(first_name, second_name):
    first_tokens = set(normalize_ingredient_name(first_name).split())
    second_tokens = set(normalize_ingredient_name(second_name).split())
    if not first_tokens or not second_tokens:
        return 0.0, 0
    overlap = len(first_tokens & second_tokens)
    token_score = 2 * overlap / (len(first_tokens) + len(second_tokens))
    text_score = SequenceMatcher(
        None,
        ' '.join(sorted(first_tokens)),
        ' '.join(sorted(second_tokens)),
    ).ratio()
    return 0.65 * token_score + 0.35 * text_score, overlap


def _find_recipe_image(recipe_name, minimum_score=0.0, minimum_overlap=1):
    media_root = getattr(settings, 'MEDIA_ROOT', None)
    if not media_root:
        return None
    image_dir = Path(media_root) / 'mon_an'
    if not image_dir.is_dir():
        return None

    best_file = None
    best_score = 0.0
    for file_path in sorted(image_dir.iterdir()):
        if not file_path.is_file() or file_path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        score, overlap = _recipe_similarity_score(recipe_name, file_path.stem)
        if overlap < minimum_overlap:
            continue
        if score > best_score and score >= minimum_score:
            best_file = file_path
            best_score = score

    if best_file is not None:
        return f'mon_an/{best_file.name}'
    return None


def _build_ai_image_prompt(recipe_name, ingredient_names=(), image_prompt=''):
    cleaned_prompt = (image_prompt or '').strip()
    if cleaned_prompt:
        return (
            f'{cleaned_prompt}, Vietnamese cuisine, realistic appetizing '
            'food photography, natural lighting, high resolution'
        )

    ingredients_part = ', '.join(
        name.strip()
        for name in ingredient_names
        if isinstance(name, str) and name.strip()
    )
    if ingredients_part:
        return (
            f'Vietnamese dish "{recipe_name}", cooked with {ingredients_part}, '
            'served on a ceramic plate, realistic appetizing food photography, '
            'natural lighting, high resolution'
        )
    return (
        f'Vietnamese dish "{recipe_name}", served on a ceramic plate, '
        'realistic appetizing food photography, natural lighting, high resolution'
    )


def _generate_ai_recipe_image_url(
    recipe_name,
    ingredient_names=(),
    image_prompt='',
):
    """Generate a fast food photo URL from instant CDN or custom template."""
    template = getattr(
        settings,
        'AI_IMAGE_URL_TEMPLATE',
        DEFAULT_AI_IMAGE_URL_TEMPLATE,
    )
    if not template:
        return None
    model = (
        getattr(settings, 'AI_IMAGE_MODEL', DEFAULT_AI_IMAGE_MODEL)
        or DEFAULT_AI_IMAGE_MODEL
    )
    if 'tse2.mm.bing.net' in template or 'bing.net/th' in template:
        prompt = f'{str(recipe_name).strip()} món ăn Việt Nam'
    else:
        prompt = _build_ai_image_prompt(
            recipe_name,
            ingredient_names=ingredient_names,
            image_prompt=image_prompt,
        )
    normalized_name = normalize_ingredient_name(recipe_name) or str(recipe_name)
    seed = zlib.crc32(normalized_name.encode('utf-8')) & 0x7FFFFFFF
    return template.format(
        prompt=quote(prompt),
        model=quote(str(model)),
        seed=seed,
    )


def _save_recipe_image_if_missing(
    recipe,
    ingredient_names=(),
    image_prompt='',
):
    if recipe.anh_mon:
        current_stem = Path(recipe.anh_mon.name).stem
        _, current_overlap = _recipe_similarity_score(recipe.ten_mon, current_stem)
        if current_overlap >= MINIMUM_IMAGE_WORD_OVERLAP:
            return
        recipe.anh_mon = ''
        recipe.save(update_fields=['anh_mon'])

    if recipe.anh_mon_url and 'image.pollinations.ai' not in recipe.anh_mon_url:
        return

    local_image = _find_recipe_image(
        recipe.ten_mon,
        minimum_score=0.78,
        minimum_overlap=MINIMUM_IMAGE_WORD_OVERLAP,
    )
    if local_image:
        recipe.anh_mon.name = local_image
        recipe.save(update_fields=['anh_mon'])
        return

    best_match = None
    best_score = 0.0
    candidates = Recipe.objects.exclude(pk=recipe.pk).filter(
        Q(anh_mon__isnull=False) & ~Q(anh_mon='')
    )
    for candidate in candidates:
        score, overlap = _recipe_similarity_score(recipe.ten_mon, candidate.ten_mon)
        if overlap >= MINIMUM_IMAGE_WORD_OVERLAP and score > best_score:
            best_match, best_score = candidate, score

    if best_match and best_score >= 0.78:
        _, stem_overlap = _recipe_similarity_score(
            recipe.ten_mon,
            Path(best_match.anh_mon.name).stem,
        )
        if stem_overlap >= MINIMUM_IMAGE_WORD_OVERLAP:
            recipe.anh_mon.name = best_match.anh_mon.name
            recipe.save(update_fields=['anh_mon'])
            return

    if not ingredient_names and recipe.pk:
        ingredient_names = [
            item.thuc_pham.ten_thuc_pham
            for item in recipe.thanh_phan.all()
            if getattr(item, 'thuc_pham_id', None)
        ]

    image_url = (
        _generate_ai_recipe_image_url(
            recipe.ten_mon,
            ingredient_names=ingredient_names,
            image_prompt=image_prompt,
        )
        or _search_recipe_image_url(recipe.ten_mon)
    )
    if image_url:
        recipe.anh_mon_url = image_url
        recipe.save(update_fields=['anh_mon_url'])


def _search_recipe_image_url(recipe_name):
    """Find a food photo through Pexels; requires PEXELS_API_KEY."""
    api_key = getattr(settings, 'PEXELS_API_KEY', '')
    if not api_key:
        return None
    query = f'{recipe_name} Vietnamese food'
    request = Request(
        'https://api.pexels.com/v1/search?query='
        + quote(query)
        + '&per_page=1&orientation=landscape',
        headers={'Authorization': api_key, 'User-Agent': 'food-recommendation/1.0'},
    )
    try:
        with urlopen(request, timeout=8) as response:
            result = json.loads(response.read().decode('utf-8'))
        photos = result.get('photos', [])
        src = photos[0].get('src', {}) if photos else {}
        image_url = src.get('large') or src.get('medium')
        if isinstance(image_url, str) and image_url.startswith('https://'):
            return image_url
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, AttributeError, IndexError):
        return None
    return None


def _groq_urlopen(request):
    for attempt in range(GROQ_MAX_503_RETRIES + 1):
        try:
            return urlopen(request, timeout=60)
        except HTTPError as error:
            if error.code != 503 or attempt == GROQ_MAX_503_RETRIES:
                raise

            retry_after = error.headers.get('Retry-After') if error.headers else None
            try:
                delay = float(retry_after)
            except (TypeError, ValueError):
                delay = GROQ_RETRY_BASE_SECONDS * (2 ** attempt)
            if not math.isfinite(delay) or delay < 0:
                delay = GROQ_RETRY_BASE_SECONDS * (2 ** attempt)

            error.close()
            time.sleep(min(delay, GROQ_RETRY_MAX_SECONDS))


def _discover_chat_models(models_url, api_key):
    request = Request(
        models_url,
        headers={
            'Authorization': f'Bearer {api_key}',
            'User-Agent': 'food-recommendation/1.0',
        },
        method='GET',
    )
    try:
        with urlopen(request, timeout=12) as response:
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
    excluded = ('whisper', 'tts', 'guard', 'embed', 'moderation', 'rerank', 'audio')
    preferred = (
        ':free',
        'llama-3.3',
        'llama-3.1',
        'deepseek',
        'qwen',
        'mistral',
        'ministral',
        'gemini',
        'gpt',
    )
    discovered = []
    for keyword in preferred:
        for model_id in model_ids:
            lower_id = model_id.lower()
            if (
                keyword in lower_id
                and not any(skip in lower_id for skip in excluded)
                and model_id not in discovered
            ):
                discovered.append(model_id)
                if len(discovered) >= 8:
                    return discovered
    return discovered


def _build_recipe_targets():
    groq_key = getattr(settings, 'GROQ_API_KEY', '')
    configured_groq_model = getattr(settings, 'GROQ_MODEL', '')
    if not groq_key:
        return []

    groq_models = []
    for model in (configured_groq_model, *FALLBACK_GROQ_RECIPE_MODELS):
        if (
            isinstance(model, str)
            and model.strip()
            and model.strip() not in DEPRECATED_RECIPE_MODELS
            and model.strip() not in groq_models
        ):
            groq_models.append(model.strip())
    return [
        (GROQ_API_URL, GROQ_MODELS_URL, groq_key, model, True)
        for model in groq_models
    ]


def _parse_recipe_json(content):
    if not isinstance(content, str):
        raise ValueError('Phản hồi không phải chuỗi hợp lệ.')
    cleaned = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
    if cleaned.startswith('```'):
        cleaned = cleaned.split('\n', 1)[-1]
        if cleaned.endswith('```'):
            cleaned = cleaned[:-3].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find('{')
        end = cleaned.rfind('}')
        if start != -1 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise


def _groq_recipe_suggestions(ingredient_names):
    targets = _build_recipe_targets()
    if not targets:
        raise ValueError('Chưa cấu hình GROQ_API_KEY (hoặc XKIRO_API_KEY) trên máy chủ.')

    prompt = (
        'Bạn là đầu bếp Việt Nam. Hãy đề xuất ít nhất 3 món (từ 3 đến 4 món) '
        'khác nhau có thể nấu dựa trên danh sách nguyên liệu hiện có dưới đây. '
        'Mỗi món phải dùng ít nhất một nguyên liệu bắt buộc trong danh sách. '
        'Có thể nêu thêm nguyên liệu cần mua. Trả về duy nhất JSON theo cấu trúc '
        '{"recipes":[{"name":"...","description":"...",'
        '"cooking_time_minutes":30,"difficulty":"De","servings":2,'
        '"ingredients":[{"name":"...","quantity":1,"unit":"củ","optional":false}],'
        '"steps":["..."]}]}. '
        'Bắt buộc mảng "recipes" phải có ít nhất 3 món ăn khác nhau. '
        'difficulty chỉ được là De, Trung binh hoặc Kho; quantity là số '
        'hoặc null. Không trả markdown hay văn bản ngoài JSON. Nguyên liệu '
        f'hiện có: {json.dumps(ingredient_names, ensure_ascii=False)}'
    )

    discovered_endpoints = set()
    api_response = None
    index = 0
    while index < len(targets):
        api_url, models_url, api_key, model, use_json_mode = targets[index]
        index += 1
        payload = {
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
            'temperature': 0.3,
            'max_completion_tokens': 3000,
        }
        if use_json_mode:
            payload['response_format'] = {'type': 'json_object'}
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
            with _groq_urlopen(request) as response:
                api_response = json.loads(response.read().decode('utf-8'))
            content = api_response['choices'][0]['message']['content']
            result = _parse_recipe_json(content)
            recipes = result.get('recipes') if isinstance(result, dict) else None
            if isinstance(recipes, list) and recipes:
                return recipes[:MAX_AI_RECIPES]
            if index < len(targets):
                continue
        except HTTPError as error:
            response_text = error.read().decode('utf-8', errors='replace').strip()
            if error.code in RETRYABLE_HTTP_CODES and models_url not in discovered_endpoints:
                discovered_endpoints.add(models_url)
                is_groq = api_url == GROQ_API_URL
                for discovered_model in _discover_chat_models(models_url, api_key):
                    candidate = (api_url, models_url, api_key, discovered_model, is_groq)
                    if candidate not in targets:
                        targets.append(candidate)
            if error.code in RETRYABLE_HTTP_CODES and index < len(targets):
                continue

            try:
                error_body = json.loads(response_text)
            except json.JSONDecodeError:
                error_body = None
            if isinstance(error_body, dict):
                api_error = error_body.get('error')
                if isinstance(api_error, dict):
                    response_text = api_error.get('message') or response_text
                elif isinstance(api_error, str):
                    response_text = api_error
                else:
                    response_text = (
                        error_body.get('message')
                        or error_body.get('detail')
                        or response_text
                    )
            response_text = response_text.replace(api_key, '[đã ẩn]')
            raise ValueError(
                f'Groq không thể gợi ý món ăn (HTTP {error.code}): '
                f'{response_text[:500] or error.reason}'
            ) from error
        except (URLError, TimeoutError) as error:
            if index < len(targets):
                continue
            raise ValueError('Không thể kết nối tới Groq API để gợi ý món ăn.') from error
        except json.JSONDecodeError as error:
            if index < len(targets):
                continue
            raise ValueError('Groq API trả về phản hồi gợi ý không hợp lệ.') from error
        except (KeyError, IndexError, TypeError, ValueError) as error:
            if index < len(targets):
                continue
            raise ValueError('Groq API trả về dữ liệu gợi ý không hợp lệ.') from error

    try:
        content = api_response['choices'][0]['message']['content']
        result = _parse_recipe_json(content)
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError('Groq API trả về dữ liệu gợi ý không hợp lệ.') from error
    recipes = result.get('recipes') if isinstance(result, dict) else None
    if not isinstance(recipes, list):
        raise ValueError('Groq API không trả về danh sách món ăn.')
    if not recipes:
        raise ValueError('Groq API không tìm được món ăn phù hợp.')
    return recipes[:MAX_AI_RECIPES]


def _validate_ai_recipe(recipe):
    if not isinstance(recipe, dict):
        raise ValueError('Groq API trả về một món ăn không hợp lệ.')

    name = recipe.get('name')
    description = recipe.get('description', '')
    image_prompt = recipe.get('image_prompt', '')
    cooking_time = recipe.get('cooking_time_minutes')
    servings = recipe.get('servings', 1)
    difficulty = recipe.get('difficulty', 'De')
    ingredients = recipe.get('ingredients')
    steps = recipe.get('steps')
    difficulty_names = {
        'de': 'De',
        'dễ': 'De',
        'trung binh': 'Trung binh',
        'trung bình': 'Trung binh',
        'kho': 'Kho',
        'khó': 'Kho',
    }

    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name.strip()) > 200
        or not isinstance(description, str)
        or (image_prompt is not None and not isinstance(image_prompt, str))
        or not isinstance(cooking_time, int)
        or isinstance(cooking_time, bool)
        or cooking_time <= 0
        or not isinstance(servings, int)
        or isinstance(servings, bool)
        or servings <= 0
        or not isinstance(difficulty, str)
        or difficulty.casefold() not in difficulty_names
        or not isinstance(ingredients, list)
        or not ingredients
        or not isinstance(steps, list)
        or not steps
    ):
        raise ValueError('Groq API trả về thông tin món ăn không hợp lệ.')

    validated_ingredients = []
    for ingredient in ingredients:
        if not isinstance(ingredient, dict):
            raise ValueError('Groq API trả về nguyên liệu món ăn không hợp lệ.')
        ingredient_name = ingredient.get('name')
        quantity = ingredient.get('quantity')
        unit = ingredient.get('unit', '')
        optional = ingredient.get('optional', False)
        if (
            not isinstance(ingredient_name, str)
            or not ingredient_name.strip()
            or len(ingredient_name.strip()) > 100
            or (quantity is not None and (
                isinstance(quantity, bool)
                or not isinstance(quantity, (int, float))
                or not math.isfinite(quantity)
                or quantity < 0
            ))
            or (unit is not None and not isinstance(unit, str))
            or not isinstance(optional, bool)
        ):
            raise ValueError('Groq API trả về nguyên liệu món ăn không hợp lệ.')
        amount = None
        if quantity is not None:
            try:
                amount = Decimal(str(quantity)).quantize(Decimal('0.01'))
            except InvalidOperation as error:
                raise ValueError(
                    'Groq API trả về định lượng nguyên liệu không hợp lệ.'
                ) from error
            if amount > Decimal('999999.99'):
                raise ValueError(
                    'Groq API trả về định lượng nguyên liệu vượt giới hạn.'
                )
        validated_ingredients.append({
            'name': ingredient_name.strip(),
            'quantity': amount,
            'unit': (unit or '')[:30],
            'optional': optional,
        })

    if any(
        not isinstance(step, str) or not step.strip()
        for step in steps
    ):
        raise ValueError('Groq API trả về cách nấu không hợp lệ.')

    return {
        'name': name.strip(),
        'description': description.strip(),
        'image_prompt': (image_prompt or '').strip(),
        'cooking_time': cooking_time,
        'servings': servings,
        'difficulty': difficulty_names[difficulty.casefold()],
        'ingredients': validated_ingredients,
        'steps': [step.strip() for step in steps],
    }


def _detected_ingredients(session):
    detections = list(
        DetectedIngredient.objects.filter(phien_nhan_dien=session)
        .select_related('thuc_pham')
    )
    available_names = []
    available_ids = set()
    for detection in detections:
        name = (
            detection.thuc_pham.ten_thuc_pham
            if detection.thuc_pham_id
            else detection.ten_da_nhan_dien
        )
        if name not in available_names:
            available_names.append(name)
        if detection.thuc_pham_id:
            available_ids.add(detection.thuc_pham_id)
    return detections, available_names, available_ids


def _create_database_recommendations(
    session,
    available_ids,
    min_match_percent=MINIMUM_DATABASE_RECIPE_MATCH_PERCENT,
    exclude_recipe_ids=(),
    limit=None,
):
    if not available_ids:
        return []

    existing_ids = set(
        Recommendation.objects.filter(
            phien_nhan_dien=session,
            mon_an__isnull=False,
        ).values_list('mon_an_id', flat=True)
    ) | set(exclude_recipe_ids)

    recipes = (
        Recipe.objects.filter(
            dang_su_dung=True,
            thanh_phan__thuc_pham_id__in=available_ids,
        )
        .exclude(pk__in=existing_ids)
        .distinct()
        .prefetch_related('thanh_phan__thuc_pham')
    )
    scored_candidates = []
    for recipe in recipes:
        recipe_ingredients = list(recipe.thanh_phan.all())
        required_ingredients = [
            item for item in recipe_ingredients if not item.la_tuy_chon
        ]
        matched_count = sum(
            1 for item in required_ingredients
            if item.thuc_pham_id in available_ids
        )
        denominator = len(required_ingredients)
        if (
            denominator == 0
            or matched_count == 0
            or matched_count * 100 < denominator * min_match_percent
        ):
            continue
        score = (
            Decimal(matched_count * 100) / Decimal(denominator)
        ).quantize(Decimal('0.01'))
        missing = [
            item.thuc_pham.ten_thuc_pham
            for item in required_ingredients
            if item.thuc_pham_id not in available_ids
        ]
        scored_candidates.append((score, matched_count, recipe, recipe_ingredients, missing))

    scored_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if limit is not None:
        scored_candidates = scored_candidates[:limit]

    created_recommendations = []
    for score, _, recipe, recipe_ingredients, missing in scored_candidates:
        _save_recipe_image_if_missing(
            recipe,
            ingredient_names=[
                item.thuc_pham.ten_thuc_pham for item in recipe_ingredients
            ],
        )
        created_recommendations.append(Recommendation(
            phien_nhan_dien=session,
            mon_an=recipe,
            diem_phu_hop=score,
            thuc_pham_con_thieu=missing,
        ))
    return Recommendation.objects.bulk_create(created_recommendations)


def _get_or_create_ingredient(name):
    canonical_name = canonical_ingredient_name(name)
    if not canonical_name:
        raise ValueError('Tên nguyên liệu do Groq trả về không hợp lệ.')
    ingredient, _ = Ingredient.objects.get_or_create(
        ten_chuan_hoa=canonical_name,
        defaults={
            'ten_thuc_pham': name[:100],
            'loai_thuc_pham': 'Khác',
        },
    )
    return ingredient


def _ingredient_matches_detected(ingredient_key, detected_keys):
    if not ingredient_key:
        return False
    if ingredient_key in detected_keys:
        return True
    for det_key in detected_keys:
        if not det_key:
            continue
        if len(det_key) >= 3 and (det_key in ingredient_key or ingredient_key in det_key):
            return True
    return False


def _create_ai_recommendations(session, recipes, detected_names, existing_names=()):
    validated_recipes = [_validate_ai_recipe(recipe) for recipe in recipes]
    detected_keys = {
        normalize_ingredient_name(name)
        for name in detected_names
    }
    seen_recipe_names = {
        normalize_ingredient_name(name)
        for name in existing_names
        if isinstance(name, str) and name.strip()
    }
    created_recommendations = []

    with transaction.atomic():
        for recipe_data in validated_recipes:
            normalized_recipe_name = normalize_ingredient_name(recipe_data['name'])
            if normalized_recipe_name in seen_recipe_names:
                continue
            unique_recipe_ingredients = []
            matched_names = set()
            seen_ingredients = set()
            for item in recipe_data['ingredients']:
                ingredient_key = normalize_ingredient_name(item['name'])
                if ingredient_key in seen_ingredients:
                    continue
                seen_ingredients.add(ingredient_key)
                unique_recipe_ingredients.append(item)
                if not item['optional'] and _ingredient_matches_detected(
                    ingredient_key,
                    detected_keys,
                ):
                    matched_names.add(ingredient_key)

            if not matched_names:
                continue

            seen_recipe_names.add(normalized_recipe_name)
            ingredient_links = [
                (_get_or_create_ingredient(item['name']), item)
                for item in unique_recipe_ingredients
            ]
            missing_names = [
                item['name']
                for item in unique_recipe_ingredients
                if (
                    not item['optional']
                    and not _ingredient_matches_detected(
                        normalize_ingredient_name(item['name']),
                        detected_keys,
                    )
                )
            ]
            required_count = sum(
                1 for item in unique_recipe_ingredients if not item['optional']
            )
            recipe = Recipe.objects.create(
                ten_mon=recipe_data['name'],
                mo_ta=recipe_data['description'],
                thoi_gian_nau=recipe_data['cooking_time'],
                do_kho=recipe_data['difficulty'],
                cong_thuc='\n'.join(
                    f'{index}. {step}'
                    for index, step in enumerate(recipe_data['steps'], start=1)
                ),
                so_khau_phan=recipe_data['servings'],
                nguon_du_lieu='groq',
            )
            _save_recipe_image_if_missing(
                recipe,
                ingredient_names=[
                    item['name'] for item in unique_recipe_ingredients
                ],
                image_prompt=recipe_data.get('image_prompt', ''),
            )
            RecipeIngredient.objects.bulk_create([
                RecipeIngredient(
                    mon_an=recipe,
                    thuc_pham=ingredient,
                    so_luong=item['quantity'],
                    don_vi=item['unit'],
                    la_tuy_chon=item['optional'],
                )
                for ingredient, item in ingredient_links
            ])
            score = (
                Decimal(len(matched_names) * 100)
                / Decimal(required_count)
            ).quantize(Decimal('0.01'))
            created_recommendations.append(Recommendation(
                phien_nhan_dien=session,
                mon_an=recipe,
                diem_phu_hop=score,
                thuc_pham_con_thieu=missing_names,
            ))

        if not created_recommendations:
            raise ValueError(
                'Groq không gợi ý được món dùng nguyên liệu đã nhận diện.'
            )
        return Recommendation.objects.bulk_create(created_recommendations)


def create_recommendations_for_session(session: RecognitionSession):
    _, detected_names, available_ids = _detected_ingredients(session)
    if not detected_names:
        return []

    existing = list(
        Recommendation.objects.filter(
            phien_nhan_dien=session,
            mon_an__isnull=False,
        ).select_related('mon_an')
    )
    new_db_recs = _create_database_recommendations(session, available_ids)
    recommendations = existing + list(new_db_recs)
    if len(recommendations) >= MIN_RECOMMENDATIONS:
        return recommendations

    existing_names = [
        item.mon_an.ten_mon
        for item in recommendations
        if item.mon_an_id
    ]
    if not recommendations:
        ai_recipes = _groq_recipe_suggestions(detected_names)
        recommendations.extend(
            _create_ai_recommendations(
                session,
                ai_recipes,
                detected_names,
                existing_names=existing_names,
            )
        )
    elif getattr(settings, 'GROQ_API_KEY', ''):
        try:
            ai_recipes = _groq_recipe_suggestions(detected_names)
            recommendations.extend(
                _create_ai_recommendations(
                    session,
                    ai_recipes,
                    detected_names,
                    existing_names=existing_names,
                )
            )
        except ValueError:
            pass

    if len(recommendations) < MIN_RECOMMENDATIONS and recommendations:
        needed = MIN_RECOMMENDATIONS - len(recommendations)
        fallback_db_recs = _create_database_recommendations(
            session,
            available_ids,
            min_match_percent=1,
            limit=needed,
        )
        recommendations.extend(fallback_db_recs)

    if len(recommendations) < MIN_RECOMMENDATIONS and recommendations:
        needed = MIN_RECOMMENDATIONS - len(recommendations)
        existing_ids = {
            item.mon_an_id for item in recommendations if item.mon_an_id
        }
        detected_keys = [
            normalize_ingredient_name(name)
            for name in detected_names
            if normalize_ingredient_name(name)
        ]
        candidate_recipes = list(
            Recipe.objects.filter(dang_su_dung=True)
            .exclude(pk__in=existing_ids)
            .prefetch_related('thanh_phan__thuc_pham')
        )
        scored_extra = []
        for recipe in candidate_recipes:
            recipe_norm = normalize_ingredient_name(recipe.ten_mon)
            recipe_ing_names = [
                item.thuc_pham.ten_thuc_pham
                for item in recipe.thanh_phan.all()
                if getattr(item, 'thuc_pham_id', None)
            ]
            ing_norms = [normalize_ingredient_name(n) for n in recipe_ing_names]
            hits = sum(
                1
                for dk in detected_keys
                if dk in recipe_norm
                or any(dk in inorm or inorm in dk for inorm in ing_norms if inorm)
            )
            if hits > 0:
                scored_extra.append((hits, recipe, recipe_ing_names))
        scored_extra.sort(key=lambda item: item[0], reverse=True)
        extra_recs = []
        for hits, recipe, recipe_ing_names in scored_extra[:needed]:
            _save_recipe_image_if_missing(recipe, ingredient_names=recipe_ing_names)
            extra_recs.append(
                Recommendation(
                    phien_nhan_dien=session,
                    mon_an=recipe,
                    diem_phu_hop=Decimal('70.00'),
                    thuc_pham_con_thieu=[],
                )
            )
        if extra_recs:
            recommendations.extend(Recommendation.objects.bulk_create(extra_recs))

    return recommendations
