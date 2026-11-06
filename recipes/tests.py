import json
import tempfile
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from recognition.models import (
    DetectedIngredient,
    RecognitionSession,
    Recommendation,
)

from .models import Ingredient, Recipe, RecipeIngredient
from .views import (
    GROQ_API_URL,
    _find_recipe_image,
    _groq_recipe_suggestions,
    create_recommendations_for_session,
)


class RecipeRecommendationTests(TestCase):
    def _create_session_with_tomato(self, tomato):
        return self._create_session_with_ingredients([tomato])

    def _create_session_with_ingredients(self, ingredients):
        session = RecognitionSession.objects.create(
            anh_dau_vao=SimpleUploadedFile(
                'ingredient-image.jpg',
                b'test image content',
                content_type='image/jpeg',
            ),
            trang_thai='thanh_cong',
        )
        for ingredient in ingredients:
            DetectedIngredient.objects.create(
                phien_nhan_dien=session,
                thuc_pham=ingredient,
                ten_da_nhan_dien=ingredient.ten_thuc_pham,
                do_tin_cay='0.9500',
            )
        return session

    def _set_recommendation_session(self, session):
        session_data = self.client.session
        session_data['last_recognition_session_id'] = session.pk
        session_data.save()

    @override_settings(GROQ_API_KEY='test-key', GROQ_MODEL='recipe-model')
    @patch('recipes.views.urlopen')
    def test_groq_request_uses_detected_ingredients_and_parses_recipes(
        self,
        mock_urlopen,
    ):
        recipes = [{'name': 'Trứng xào cà chua'}]
        mock_urlopen.return_value.__enter__.return_value.read.return_value = (
            json.dumps({
                'choices': [{
                    'message': {
                        'content': json.dumps({'recipes': recipes}),
                    },
                }],
            }).encode('utf-8')
        )

        suggestions = _groq_recipe_suggestions(['Cà chua', 'Trứng'])

        self.assertEqual(suggestions, recipes)
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, GROQ_API_URL)
        self.assertEqual(
            request.get_header('Authorization'),
            'Bearer test-key',
        )
        payload = json.loads(request.data)
        self.assertEqual(payload['model'], 'recipe-model')
        self.assertIn('Cà chua', payload['messages'][0]['content'])
        self.assertIn('Trứng', payload['messages'][0]['content'])

    @override_settings(GROQ_API_KEY='test-key', GROQ_MODEL='recipe-model')
    @patch('recipes.views.time.sleep')
    @patch('recipes.views.urlopen')
    def test_groq_recipe_request_retries_after_service_overload(
        self,
        mock_urlopen,
        mock_sleep,
    ):
        overloaded = HTTPError(
            url=GROQ_API_URL,
            code=503,
            msg='Service Unavailable',
            hdrs={'Retry-After': '2'},
            fp=BytesIO(b'currently over capacity'),
        )
        recipes = [{'name': 'Trứng xào cà chua'}]
        response = mock_urlopen.return_value
        response.__enter__.return_value.read.return_value = json.dumps({
            'choices': [{
                'message': {
                    'content': json.dumps({'recipes': recipes}),
                },
            }],
        }).encode('utf-8')
        mock_urlopen.side_effect = [overloaded, response]

        suggestions = _groq_recipe_suggestions(['Cà chua', 'Trứng'])

        self.assertEqual(suggestions, recipes)
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once_with(2)

    @override_settings(GROQ_API_KEY='test-key', GROQ_MODEL='recipe-model')
    @patch('recipes.views.time.sleep')
    @patch('recipes.views.urlopen')
    def test_groq_recipe_request_stops_after_three_overload_retries(
        self,
        mock_urlopen,
        mock_sleep,
    ):
        mock_urlopen.side_effect = [
            HTTPError(
                url=GROQ_API_URL,
                code=503,
                msg='Service Unavailable',
                hdrs=None,
                fp=BytesIO(b'currently over capacity'),
            )
            for _ in range(4)
        ]

        with self.assertRaisesRegex(ValueError, 'HTTP 503.*over capacity'):
            _groq_recipe_suggestions(['Cà chua'])

        self.assertEqual(mock_urlopen.call_count, 4)
        self.assertEqual(
            [call.args[0] for call in mock_sleep.call_args_list],
            [1, 2, 4],
        )

    def test_existing_recipe_match_is_saved_without_calling_groq(self):
        tomato = Ingredient.objects.create(
            ten_thuc_pham='Cà chua',
            ten_chuan_hoa='ca_chua',
            loai_thuc_pham='Rau củ',
        )
        recipe = Recipe.objects.create(
            ten_mon='Trứng sốt cà chua',
            thoi_gian_nau=20,
            cong_thuc='Chiên trứng rồi nấu cùng cà chua.',
        )
        RecipeIngredient.objects.create(
            mon_an=recipe,
            thuc_pham=tomato,
        )
        session = self._create_session_with_tomato(tomato)

        with patch('recipes.views._groq_recipe_suggestions') as mock_groq:
            recommendations = create_recommendations_for_session(session)

        self.assertEqual(len(recommendations), 1)
        self.assertEqual(recommendations[0].mon_an, recipe)
        self.assertEqual(recommendations[0].diem_phu_hop, 100)
        mock_groq.assert_not_called()

        self._set_recommendation_session(session)
        response = self.client.get('/recommendations/')
        self.assertContains(response, 'Trứng sốt cà chua')
        self.assertContains(
            response,
            f'/recipe-detail/{recipe.pk}/',
        )
        self.assertNotContains(response, 'Chiên trứng rồi nấu cùng cà chua.')

        detail_response = self.client.get(f'/recipe-detail/{recipe.pk}/')
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(
            detail_response,
            'Chiên trứng rồi nấu cùng cà chua.',
        )

    def test_database_recommendation_saves_image_path_and_displays_stored_image(self):
        tomato = Ingredient.objects.create(
            ten_thuc_pham='Cà chua',
            ten_chuan_hoa='ca_chua',
            loai_thuc_pham='Rau củ',
        )
        recipe = Recipe.objects.create(
            ten_mon='Trứng sốt cà chua',
            thoi_gian_nau=20,
            cong_thuc='Chiên trứng rồi nấu cùng cà chua.',
        )
        RecipeIngredient.objects.create(
            mon_an=recipe,
            thuc_pham=tomato,
        )
        session = self._create_session_with_tomato(tomato)

        with tempfile.TemporaryDirectory() as media_root:
            image_directory = Path(media_root) / 'mon_an'
            image_directory.mkdir()
            (image_directory / 'trung_sot_ca_chua.jpg').touch()

            with (
                override_settings(MEDIA_ROOT=media_root),
                patch('recipes.views._groq_recipe_suggestions') as mock_groq,
            ):
                recommendations = create_recommendations_for_session(session)
                recipe.refresh_from_db()
                self._set_recommendation_session(session)
                response = self.client.get('/recommendations/')

        mock_groq.assert_not_called()
        self.assertEqual(len(recommendations), 1)
        self.assertEqual(recipe.anh_mon.name, 'mon_an/trung_sot_ca_chua.jpg')
        self.assertContains(
            response,
            'src="/media/mon_an/trung_sot_ca_chua.jpg"',
        )

    def test_database_recipe_below_70_percent_is_skipped_and_sent_to_groq(self):
        detected_ingredients = [
            Ingredient.objects.create(
                ten_thuc_pham=name,
                ten_chuan_hoa=canonical_name,
                loai_thuc_pham='Rau củ',
            )
            for name, canonical_name in (
                ('Cà chua', 'ca_chua'),
                ('Hành tây', 'hanh_tay'),
            )
        ]
        missing_ingredient = Ingredient.objects.create(
            ten_thuc_pham='Thịt bò',
            ten_chuan_hoa='thit_bo',
            loai_thuc_pham='Thịt',
        )
        recipe = Recipe.objects.create(
            ten_mon='Bò xào cà chua',
            thoi_gian_nau=20,
            cong_thuc='Xào thịt bò cùng cà chua và hành tây.',
        )
        for ingredient in [*detected_ingredients, missing_ingredient]:
            RecipeIngredient.objects.create(
                mon_an=recipe,
                thuc_pham=ingredient,
            )
        session = self._create_session_with_ingredients(detected_ingredients)
        detected_names = [
            ingredient.ten_thuc_pham for ingredient in detected_ingredients
        ]

        with patch(
            'recipes.views._groq_recipe_suggestions',
            side_effect=ValueError('Groq requested for unmatched recipes'),
        ) as mock_groq:
            with self.assertRaisesMessage(
                ValueError,
                'Groq requested for unmatched recipes',
            ):
                create_recommendations_for_session(session)

        mock_groq.assert_called_once_with(detected_names)
        self.assertFalse(
            Recommendation.objects.filter(
                phien_nhan_dien=session,
                mon_an=recipe,
            ).exists()
        )

    def test_database_recipe_at_70_percent_is_recommended(self):
        ingredients = [
            Ingredient.objects.create(
                ten_thuc_pham=f'Nguyên liệu {index}',
                ten_chuan_hoa=f'nguyen_lieu_{index}',
                loai_thuc_pham='Rau củ',
            )
            for index in range(10)
        ]
        recipe = Recipe.objects.create(
            ten_mon='Món ăn đủ ngưỡng',
            thoi_gian_nau=20,
            cong_thuc='Nấu các nguyên liệu.',
        )
        for ingredient in ingredients:
            RecipeIngredient.objects.create(
                mon_an=recipe,
                thuc_pham=ingredient,
            )
        session = self._create_session_with_ingredients(ingredients[:7])

        with patch('recipes.views._groq_recipe_suggestions') as mock_groq:
            recommendations = create_recommendations_for_session(session)

        self.assertEqual(len(recommendations), 1)
        self.assertEqual(recommendations[0].mon_an, recipe)
        self.assertEqual(recommendations[0].diem_phu_hop, 70)
        self.assertEqual(
            recommendations[0].thuc_pham_con_thieu,
            ['Nguyên liệu 7', 'Nguyên liệu 8', 'Nguyên liệu 9'],
        )
        mock_groq.assert_not_called()

    def test_recommendation_request_runs_only_after_button_post(self):
        tomato = Ingredient.objects.create(
            ten_thuc_pham='Cà chua',
            ten_chuan_hoa='ca_chua',
            loai_thuc_pham='Rau củ',
        )
        session = self._create_session_with_tomato(tomato)
        self._set_recommendation_session(session)

        with patch(
            'recognition.page_views.create_recommendations_for_session'
        ) as mock_create_recommendations:
            response = self.client.post('/recommendations/')

        self.assertRedirects(response, '/recommendations/')
        mock_create_recommendations.assert_called_once_with(session)

    def test_groq_error_is_displayed_without_claiming_button_was_not_clicked(self):
        tomato = Ingredient.objects.create(
            ten_thuc_pham='Cà chua',
            ten_chuan_hoa='ca_chua',
            loai_thuc_pham='Rau củ',
        )
        session = self._create_session_with_tomato(tomato)
        self._set_recommendation_session(session)
        error_message = (
            'Groq không thể gợi ý món ăn (HTTP 503): currently over capacity.'
        )

        with patch(
            'recognition.page_views.create_recommendations_for_session',
            side_effect=ValueError(error_message),
        ) as mock_create_recommendations:
            response = self.client.post('/recommendations/')
            self.assertRedirects(
                response,
                '/recommendations/',
                fetch_redirect_response=False,
            )
            response = self.client.get('/recommendations/')

        mock_create_recommendations.assert_called_once_with(session)
        self.assertContains(response, error_message)
        self.assertNotContains(
            response,
            'Nhấn nút “Gợi ý món ăn” trên trang nhận diện',
        )

    def test_recommendations_page_shows_database_recipes_without_detection(self):
        tomato = Ingredient.objects.create(
            ten_thuc_pham='Cà chua',
            ten_chuan_hoa='ca_chua',
            loai_thuc_pham='Rau củ',
        )
        recipe = Recipe.objects.create(
            ten_mon='Trứng sốt cà chua',
            mo_ta='Món ăn đơn giản.',
            thoi_gian_nau=20,
            cong_thuc='Chiên trứng rồi nấu cùng cà chua.',
        )
        RecipeIngredient.objects.create(
            mon_an=recipe,
            thuc_pham=tomato,
        )

        response = self.client.get('/recommendations/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Trứng sốt cà chua')
        self.assertContains(response, f'/recipe-detail/{recipe.pk}/')
        self.assertNotContains(response, 'Món ăn đơn giản.')
        self.assertNotContains(response, 'Chiên trứng rồi nấu cùng cà chua.')

        detail_response = self.client.get(f'/recipe-detail/{recipe.pk}/')
        self.assertContains(detail_response, 'Món ăn đơn giản.')
        self.assertContains(
            detail_response,
            'Chiên trứng rồi nấu cùng cà chua.',
        )

    def test_find_recipe_image_matches_recipe_name_to_media_filename(self):
        with tempfile.TemporaryDirectory() as media_root:
            image_directory = Path(media_root) / 'mon_an'
            image_directory.mkdir()
            (image_directory / 'thit_ga_xao_nam.jpg').touch()
            (image_directory / 'my_sot_kem.jpg').touch()
            (image_directory / 'notes.txt').touch()

            with override_settings(MEDIA_ROOT=media_root):
                image_name = _find_recipe_image('Gà xào cà chua')

        self.assertEqual(image_name, 'mon_an/thit_ga_xao_nam.jpg')

    @override_settings(GROQ_API_KEY='test-key')
    def test_groq_recipe_is_saved_and_displayed_with_ingredients_and_steps(self):
        tomato = Ingredient.objects.create(
            ten_thuc_pham='Cà chua',
            ten_chuan_hoa='ca_chua',
            loai_thuc_pham='Rau củ',
        )
        session = self._create_session_with_tomato(tomato)
        groq_recipes = [{
            'name': 'Gà xào cà chua',
            'description': 'Món gà xào nhanh với cà chua.',
            'cooking_time_minutes': 25,
            'difficulty': 'De',
            'servings': 2,
            'ingredients': [
                {
                    'name': 'Cà chua',
                    'quantity': 2,
                    'unit': 'quả',
                    'optional': False,
                },
                {
                    'name': 'Thịt gà',
                    'quantity': 200,
                    'unit': 'g',
                    'optional': False,
                },
            ],
            'steps': ['Rửa sạch cà chua và thịt gà.', 'Xào chín và nêm gia vị.'],
        }]

        with (
            tempfile.TemporaryDirectory() as media_root,
            override_settings(MEDIA_ROOT=media_root),
            patch(
                'recipes.views._groq_recipe_suggestions',
                return_value=groq_recipes,
            ) as mock_groq,
        ):
            image_directory = Path(media_root) / 'mon_an'
            image_directory.mkdir()
            (image_directory / 'thit_ga_xao_nam.jpg').touch()
            recommendations = create_recommendations_for_session(session)
            self._set_recommendation_session(session)
            response = self.client.get('/recommendations/')

        mock_groq.assert_called_once_with(['Cà chua'])
        self.assertEqual(len(recommendations), 1)
        recommendation = Recommendation.objects.get(
            phien_nhan_dien=session
        )
        recipe = recommendation.mon_an
        recipe.refresh_from_db()
        self.assertEqual(recipe.nguon_du_lieu, 'groq')
        self.assertEqual(recipe.ten_mon, 'Gà xào cà chua')
        self.assertFalse(bool(recipe.anh_mon))
        self.assertTrue(
            recipe.anh_mon_url.startswith('https://tse2.mm.bing.net/th?q=')
        )
        self.assertEqual(recommendation.thuc_pham_con_thieu, ['Thịt gà'])
        self.assertEqual(
            set(recipe.thanh_phan.values_list('thuc_pham__ten_chuan_hoa', flat=True)),
            {'ca_chua', 'thit_ga'},
        )
        self.assertContains(response, 'Gà xào cà chua')
        self.assertContains(
            response,
            f'/recipe-detail/{recipe.pk}/',
        )
        self.assertNotContains(response, 'Cần chuẩn bị thêm:')
        self.assertNotContains(response, 'Rửa sạch cà chua và thịt gà.')
        self.assertContains(response, 'https://tse2.mm.bing.net/th?q=')
        detail_response = self.client.get(f'/recipe-detail/{recipe.pk}/')
        self.assertContains(detail_response, 'Cà chua')
        self.assertContains(detail_response, 'Rửa sạch cà chua và thịt gà.')
