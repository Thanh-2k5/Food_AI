import re

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from recipes.models import Recipe
from recipes.views import (
    MIN_RECOMMENDATIONS,
    _save_recipe_image_if_missing,
    create_recommendations_for_session,
)

from .forms import RegistrationForm
from .models import (
    DetectedIngredient,
    FavoriteRecipe,
    RecipeHistory,
    RecognitionSession,
    Recommendation,
)
from .views import get_active_recognition_session


def home(request):
    return render(request, 'home.html')


def register(request):
    if request.user.is_authenticated:
        return redirect('home')

    form = RegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect('home')

    return render(request, 'auth_form.html', {
        'form': form,
        'page_title': 'Đăng ký',
        'submit_label': 'Tạo tài khoản',
        'other_url': 'login',
        'other_label': 'Đăng nhập ngay',
        'is_registration': True,
    })


def recommendations(request):
    if request.method == 'POST':
        request.session.pop('recommendation_error', None)
        recognition_session = get_active_recognition_session(
            request,
            require_success=True,
        )
        if recognition_session is None:
            request.session['recommendation_error'] = (
                'Hãy nhận diện nguyên liệu thành công trước khi yêu cầu gợi ý.'
            )
        elif (
            Recommendation.objects.filter(
                phien_nhan_dien=recognition_session,
                mon_an__isnull=False,
            ).count()
            < MIN_RECOMMENDATIONS
        ):
            try:
                create_recommendations_for_session(recognition_session)
            except ValueError as error:
                request.session['recommendation_error'] = str(error)
            else:
                request.session.pop('recommendation_error', None)
        return redirect('recommendations')

    recognition_session = get_active_recognition_session(request)
    recommendations = Recommendation.objects.none()
    detected_ingredients = []
    browse_recipes = Recipe.objects.none()
    if recognition_session is not None:
        recommendations = list(
            Recommendation.objects.filter(
                phien_nhan_dien=recognition_session,
                mon_an__isnull=False,
            )
            .select_related('mon_an')
            .prefetch_related('mon_an__thanh_phan__thuc_pham')
        )
        if (
            recognition_session.trang_thai == 'thanh_cong'
            and 0 < len(recommendations) < MIN_RECOMMENDATIONS
            and not any(
                item.mon_an and item.mon_an.nguon_du_lieu == 'groq'
                for item in recommendations
            )
        ):
            try:
                create_recommendations_for_session(recognition_session)
            except ValueError:
                pass
            recommendations = list(
                Recommendation.objects.filter(
                    phien_nhan_dien=recognition_session,
                    mon_an__isnull=False,
                )
                .select_related('mon_an')
                .prefetch_related('mon_an__thanh_phan__thuc_pham')
            )
        for item in recommendations:
            _save_recipe_image_if_missing(item.mon_an)
        detected_ingredients = list(
            DetectedIngredient.objects.filter(
                phien_nhan_dien=recognition_session
            ).select_related('thuc_pham')
        )
    if recognition_session is None:
        browse_recipes = list(
            Recipe.objects.filter(dang_su_dung=True)
            .prefetch_related('thanh_phan__thuc_pham')
            .order_by('-ngay_cap_nhat', 'ten_mon')[:6]
        )
        for item in browse_recipes:
            _save_recipe_image_if_missing(item)

    recommendation_error = request.session.pop('recommendation_error', None)
    return render(request, 'recommendations.html', {
        'recognition_session': recognition_session,
        'recommendations': recommendations,
        'browse_recipes': browse_recipes,
        'detected_ingredients': detected_ingredients,
        'recommendation_error': recommendation_error,
    })


def recipe_detail(request, recipe_id=None):
    recipes = Recipe.objects.filter(
        dang_su_dung=True
    ).prefetch_related('thanh_phan__thuc_pham')
    if recipe_id is None:
        recipe = recipes.first()
    else:
        recipe = get_object_or_404(
            recipes,
            pk=recipe_id,
        )
    if recipe is not None:
        _save_recipe_image_if_missing(recipe)
    is_favorite = False
    if recipe is not None and request.user.is_authenticated:
        RecipeHistory.objects.update_or_create(
            user=request.user,
            recipe=recipe,
        )
        is_favorite = FavoriteRecipe.objects.filter(
            user=request.user,
            recipe=recipe,
        ).exists()
    cooking_steps = []
    if recipe is not None and recipe.cong_thuc:
        step_kinds = ('prep', 'sauce', 'cook', 'serve')
        raw_lines = [
            line.strip()
            for line in recipe.cong_thuc.splitlines()
            if line.strip()
        ]
        for index, line in enumerate(raw_lines, start=1):
            cleaned = re.sub(
                r'^(?:bước\s*\d+\s*[:.-]?|\d+\s*[.):-])\s*',
                '',
                line,
                flags=re.IGNORECASE,
            ).strip()
            cooking_steps.append({
                'number': index,
                'text': cleaned or line,
                'kind': (
                    'serve'
                    if index == len(raw_lines) and len(raw_lines) > 1
                    else step_kinds[(index - 1) % len(step_kinds)]
                ),
            })
    return render(request, 'recipe_detail.html', {
        'recipe': recipe,
        'is_favorite': is_favorite,
        'cooking_steps': cooking_steps,
    })


@login_required
def history(request):
    history_items = (
        RecipeHistory.objects.filter(user=request.user)
        .select_related('recipe')
    )
    return render(request, 'history.html', {
        'history_items': history_items,
        'history_count': history_items.count(),
    })


@login_required
def favorites(request):
    favorite_items = (
        FavoriteRecipe.objects.filter(user=request.user)
        .select_related('recipe')
    )
    return render(request, 'favorites.html', {
        'favorite_items': favorite_items,
        'favorite_count': favorite_items.count(),
    })


@login_required
def toggle_favorite(request, recipe_id):
    if request.method != 'POST':
        return redirect('recipe_detail', recipe_id=recipe_id)

    recipe = get_object_or_404(
        Recipe,
        pk=recipe_id,
        dang_su_dung=True,
    )
    favorite, created = FavoriteRecipe.objects.get_or_create(
        user=request.user,
        recipe=recipe,
    )
    if not created:
        favorite.delete()

    return redirect('recipe_detail', recipe_id=recipe_id)


@login_required
def remove_history(request, history_id):
    if request.method == 'POST':
        get_object_or_404(
            RecipeHistory,
            pk=history_id,
            user=request.user,
        ).delete()
    return redirect('history')


@login_required
def remove_favorite(request, favorite_id):
    if request.method == 'POST':
        get_object_or_404(
            FavoriteRecipe,
            pk=favorite_id,
            user=request.user,
        ).delete()
    return redirect('favorites')
