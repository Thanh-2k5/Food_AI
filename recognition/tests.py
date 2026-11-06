import json
from io import BytesIO
import tempfile
from urllib.error import HTTPError
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from recipes.models import Ingredient, Recipe
from recipes.ingredient_utils import normalize_ingredient_name

from . import views
from .models import (
    DetectedIngredient,
    FavoriteRecipe,
    RecipeHistory,
    RecognitionSession,
    UserProfile,
)


class AccountAuthenticationTests(TestCase):
    def test_homepage_shows_authentication_actions(self):
        response = self.client.get('/')

        self.assertContains(response, 'href="/login/"')
        self.assertContains(response, 'href="/register/"')

        user = get_user_model().objects.create_user(
            username='signedin',
            password='Secure-Password-123',
        )
        self.client.force_login(user)
        response = self.client.get('/')

        self.assertContains(response, 'Xin chào, signedin')
        self.assertContains(response, 'Đăng xuất')
        self.assertNotContains(response, 'href="/login/"')

    def test_registration_creates_user_with_hashed_password_and_logs_in(self):
        response = self.client.post('/register/', {
            'username': 'newuser',
            'password1': 'Secure-Password-123',
            'password2': 'Secure-Password-123',
        })

        user = get_user_model().objects.get(username='newuser')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/')
        self.assertTrue(user.check_password('Secure-Password-123'))
        self.assertNotEqual(user.password, 'Secure-Password-123')
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)
        self.assertEqual(user.email, '')
        self.assertEqual(user.first_name, '')
        self.assertEqual(user.profile.food_preference, '')

    def test_registration_accepts_any_eight_character_password(self):
        response = self.client.post('/register/', {
            'username': '12345678',
            'password1': '12345678',
            'password2': '12345678',
        })

        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(username='12345678')
        self.assertTrue(user.check_password('12345678'))

    def test_registration_rejects_password_shorter_than_eight_characters(self):
        response = self.client.post('/register/', {
            'username': 'shortpassword',
            'password1': '1234567',
            'password2': '1234567',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Mật khẩu cần có ít nhất 8 ký tự.')
        self.assertFalse(
            get_user_model().objects.filter(username='shortpassword').exists()
        )

    def test_registration_accepts_email_and_saves_optional_preferences(self):
        response = self.client.post('/register/', {
            'username': 'cook@example.com',
            'password1': 'Secure-Password-123',
            'password2': 'Secure-Password-123',
            'food_preference': 'Món chay',
            'first_name': 'Linh',
        })

        user = get_user_model().objects.get(username='cook@example.com')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(user.email, 'cook@example.com')
        self.assertEqual(user.first_name, 'Linh')
        self.assertEqual(user.profile.food_preference, 'Món chay')
        self.assertEqual(UserProfile.objects.count(), 1)

    def test_registration_rejects_duplicate_username(self):
        get_user_model().objects.create_user(
            username='existing',
            password='Secure-Password-123',
        )

        response = self.client.post('/register/', {
            'username': 'existing',
            'password1': 'Other-Password-123',
            'password2': 'Other-Password-123',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tên người dùng này đã được sử dụng.')
        self.assertEqual(get_user_model().objects.filter(
            username='existing'
        ).count(), 1)

    def test_login_and_post_logout(self):
        user = get_user_model().objects.create_user(
            username='account',
            password='Secure-Password-123',
        )

        login_response = self.client.post('/login/', {
            'username': 'account',
            'password': 'Secure-Password-123',
        })

        self.assertEqual(login_response.status_code, 302)
        self.assertEqual(login_response.url, '/')
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)
        logout_response = self.client.post('/logout/')
        self.assertEqual(logout_response.status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_accepts_email_address(self):
        user = get_user_model().objects.create_user(
            username='emailaccount',
            email='cook@example.com',
            password='Secure-Password-123',
        )

        response = self.client.post('/login/', {
            'username': 'COOK@example.com',
            'password': 'Secure-Password-123',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_registration_page_renders_vietnamese_labels_and_fields(self):
        response = self.client.get('/register/')

        self.assertContains(response, 'Đăng ký tài khoản FoodGenie!')
        self.assertContains(response, 'Tên người dùng (hoặc Email)')
        self.assertContains(response, 'Sở thích ẩm thực')
        self.assertContains(response, 'Xác nhận mật khẩu')
        self.assertContains(response, 'Tên hiển thị (không bắt buộc)')
        self.assertContains(response, 'Mật khẩu cần có ít nhất 8 ký tự.')

    def test_login_page_renders_vietnamese_labels(self):
        response = self.client.get('/login/')

        self.assertContains(response, 'Chào mừng bạn quay trở lại!')
        self.assertContains(response, 'Tên người dùng hoặc email')
        self.assertContains(response, 'Mật khẩu')
        self.assertContains(response, 'Chưa có tài khoản?')

    def test_logout_rejects_get(self):
        response = self.client.get('/logout/')

        self.assertEqual(response.status_code, 405)


class UserRecipePersistenceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='recipeuser',
            password='Secure-Password-123',
        )
        self.other_user = get_user_model().objects.create_user(
            username='otheruser',
            password='Secure-Password-123',
        )
        self.recipe = Recipe.objects.create(
            ten_mon='Canh rau củ',
            thoi_gian_nau=25,
            cong_thuc='Nấu rau củ đến khi chín.',
        )

    def test_recipe_views_are_saved_per_user_and_not_duplicated(self):
        self.client.force_login(self.user)
        first_response = self.client.get(
            f'/recipe-detail/{self.recipe.pk}/'
        )
        second_response = self.client.get(
            f'/recipe-detail/{self.recipe.pk}/'
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(
            RecipeHistory.objects.filter(user=self.user).count(),
            1,
        )

        self.client.force_login(self.other_user)
        self.client.get(f'/recipe-detail/{self.recipe.pk}/')
        self.assertEqual(
            RecipeHistory.objects.filter(user=self.other_user).count(),
            1,
        )
        self.assertEqual(RecipeHistory.objects.count(), 2)

    def test_history_page_only_shows_current_users_recipes(self):
        RecipeHistory.objects.create(user=self.user, recipe=self.recipe)
        self.client.force_login(self.other_user)

        response = self.client.get('/history/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['history_count'], 0)
        self.assertContains(response, 'Chưa có lịch sử món ăn')

    def test_favorite_toggle_adds_and_removes_favorite_for_current_user(self):
        self.client.force_login(self.user)
        response = self.client.post(
            f'/recipe-detail/{self.recipe.pk}/favorite/'
        )

        self.assertRedirects(
            response,
            f'/recipe-detail/{self.recipe.pk}/',
        )
        favorite = FavoriteRecipe.objects.get(
            user=self.user,
            recipe=self.recipe,
        )
        self.assertEqual(FavoriteRecipe.objects.count(), 1)

        detail_response = self.client.get(
            f'/recipe-detail/{self.recipe.pk}/'
        )
        self.assertContains(detail_response, 'Bỏ yêu thích')
        self.client.post(
            f'/recipe-detail/{self.recipe.pk}/favorite/'
        )
        self.assertFalse(
            FavoriteRecipe.objects.filter(pk=favorite.pk).exists()
        )

    def test_favorites_are_private_and_cannot_be_removed_by_another_user(self):
        favorite = FavoriteRecipe.objects.create(
            user=self.user,
            recipe=self.recipe,
        )
        self.client.force_login(self.other_user)

        response = self.client.get('/favorites/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['favorite_count'], 0)
        self.assertContains(response, 'Chưa có món ăn yêu thích')
        response = self.client.post(
            f'/favorites/{favorite.pk}/remove/'
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(FavoriteRecipe.objects.filter(pk=favorite.pk).exists())

    def test_history_and_favorites_require_login(self):
        self.assertRedirects(
            self.client.get('/history/'),
            '/login/?next=/history/',
        )
        self.assertRedirects(
            self.client.get('/favorites/'),
            '/login/?next=/favorites/',
        )


class IngredientDetectionTests(TestCase):
    def _uploaded_image(self):
        image_bytes = BytesIO()
        Image.new('RGB', (2, 2), 'white').save(image_bytes, format='PNG')
        return SimpleUploadedFile(
            'ingredients.png',
            image_bytes.getvalue(),
            content_type='image/png',
        )

    def test_normalize_ingredient_name_matches_standardized_vietnamese_names(self):
        self.assertEqual(
            normalize_ingredient_name('Đậu_đũa'),
            normalize_ingredient_name('dau-dua'),
        )

    def test_detection_labels_avoid_the_top_edge_and_each_other(self):
        first = views._find_label_bounds(
            20, 0, 100, 70, 55, 20, 200, 120, [],
        )
        second = views._find_label_bounds(
            35, 0, 115, 70, 55, 20, 200, 120, [first],
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertGreater(first[1], 0)
        self.assertFalse(
            first[0] < second[2]
            and first[2] > second[0]
            and first[1] < second[3]
            and first[3] > second[1]
        )

    @patch(
        'recognition.views._detect_ingredients',
        return_value=(
            [
                {'name': 'Cà chua', 'confidence': 91},
                {'name': 'Hành lá', 'confidence': 76},
            ],
            '/media/result.jpg',
            'uploads/result.jpg',
        ),
    )
    def test_detect_persists_session_and_canonical_ingredients(
        self,
        mock_detect_ingredients,
    ):
        Ingredient.objects.create(
            ten_thuc_pham='Cà chua',
            ten_chuan_hoa='ca_chua',
            loai_thuc_pham='Rau củ',
        )
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                with patch(
                    'recipes.views.create_recommendations_for_session'
                ) as mock_create_recommendations:
                    response = self.client.post(
                        '/detect/',
                        {'image': self._uploaded_image()},
                    )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'detect.html')
        self.assertContains(response, 'Gợi ý món ăn')
        mock_detect_ingredients.assert_called_once()
        session = RecognitionSession.objects.get()
        self.assertEqual(session.trang_thai, 'thanh_cong')
        self.assertTrue(session.anh_dau_vao.name.startswith('nhan_dien/'))
        self.assertEqual(session.anh_da_xu_ly.name, 'uploads/result.jpg')
        self.assertEqual(
            self.client.session['last_recognition_session_id'],
            session.pk,
        )
        mock_create_recommendations.assert_not_called()
        detections = list(
            DetectedIngredient.objects.filter(
                phien_nhan_dien=session
            ).order_by('id')
        )
        self.assertEqual(len(detections), 2)
        self.assertEqual(detections[0].ten_da_nhan_dien, 'Cà chua')
        self.assertEqual(detections[0].thuc_pham.ten_chuan_hoa, 'ca_chua')
        self.assertEqual(str(detections[0].do_tin_cay), '0.9100')
        self.assertEqual(detections[1].ten_da_nhan_dien, 'Hành lá')
        self.assertIsNone(detections[1].thuc_pham_id)

    @patch(
        'recognition.views._detect_ingredients',
        return_value=(
            [
                {'name': 'Cà chua', 'confidence': 91},
                {'name': 'Hành lá', 'confidence': 76},
            ],
            '/media/uploads/processed.jpg',
            'uploads/processed.jpg',
        ),
    )
    def test_detect_get_restores_last_image_and_detected_ingredients(
        self,
        mock_detect_ingredients,
    ):
        session = RecognitionSession.objects.create(
            anh_dau_vao=self._uploaded_image(),
            anh_da_xu_ly='uploads/processed.jpg',
            trang_thai='thanh_cong',
        )
        DetectedIngredient.objects.bulk_create([
            DetectedIngredient(
                phien_nhan_dien=session,
                ten_da_nhan_dien='Cà chua',
                do_tin_cay='0.9100',
            ),
            DetectedIngredient(
                phien_nhan_dien=session,
                ten_da_nhan_dien='Hành lá',
                do_tin_cay='0.7600',
            ),
        ])
        session_data = self.client.session
        session_data['last_recognition_session_id'] = session.pk
        session_data.save()

        response = self.client.get('/detect/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'src="/media/uploads/processed.jpg"')
        self.assertContains(response, 'Cà chua')
        self.assertContains(response, 'Hành lá')
        self.assertContains(response, 'Gợi ý món ăn')
        mock_detect_ingredients.assert_not_called()

    @patch(
        'recognition.views._detect_ingredients',
        side_effect=ValueError('Không thể kết nối tới Groq API.'),
    )
    def test_detect_marks_session_failed_when_recognition_fails(
        self,
        mock_detect_ingredients,
    ):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.post(
                    '/detect/',
                    {'image': self._uploaded_image()},
                )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Không thể kết nối tới Groq API.')
        mock_detect_ingredients.assert_called_once()
        session = RecognitionSession.objects.get()
        self.assertEqual(session.trang_thai, 'that_bai')
        self.assertTrue(session.anh_dau_vao.name.startswith('nhan_dien/'))
        self.assertFalse(
            DetectedIngredient.objects.filter(
                phien_nhan_dien=session
            ).exists()
        )

    @override_settings(GROQ_API_KEY='test-key', GROQ_MODEL='vision-model')
    @patch('recognition.views.default_storage.url', return_value='/media/result.jpg')
    @patch('recognition.views.default_storage.save', return_value='result.jpg')
    @patch('recognition.views.urlopen')
    def test_detect_ingredients_sends_image_and_draws_box(
        self,
        mock_urlopen,
        mock_storage_save,
        mock_storage_url,
    ):
        api_content = json.dumps({
            'ingredients': [{
                'name': 'Tomato',
                'confidence': 0.91,
                'box': [250, 250, 750, 750],
            }],
        })
        mock_urlopen.return_value.__enter__.return_value.read.return_value = (
            json.dumps({
                'choices': [{
                    'message': {'content': api_content},
                }],
            }).encode('utf-8')
        )

        image_bytes = BytesIO()
        Image.new('RGB', (20, 20), 'white').save(image_bytes, format='PNG')
        uploaded_file = SimpleUploadedFile(
            'ingredients.png',
            image_bytes.getvalue(),
            content_type='image/png',
        )

        detections, image_url, image_path = views._detect_ingredients(
            uploaded_file
        )

        self.assertEqual(
            detections,
            [{'name': 'Cà chua', 'confidence': 91}],
        )
        self.assertEqual(image_url, '/media/result.jpg')
        self.assertEqual(image_path, 'result.jpg')
        mock_storage_url.assert_called_once_with('result.jpg')
        request = mock_urlopen.call_args.args[0]
        request_payload = json.loads(request.data)
        self.assertEqual(request_payload['model'], 'vision-model')
        encoded_image = request_payload['messages'][0]['content'][1][
            'image_url'
        ]['url'].split(',', 1)
        self.assertEqual(encoded_image[0], 'data:image/png;base64')
        self.assertTrue(encoded_image[1])

        saved_image = Image.open(mock_storage_save.call_args.args[1])
        self.assertEqual(saved_image.size, (20, 20))
        self.assertNotEqual(saved_image.getpixel((5, 10)), (255, 255, 255))

    @override_settings(GROQ_API_KEY='')
    def test_detect_requires_groq_api_key(self):
        image_bytes = BytesIO()
        Image.new('RGB', (2, 2), 'white').save(image_bytes, format='PNG')
        uploaded_file = SimpleUploadedFile(
            'ingredients.png',
            image_bytes.getvalue(),
            content_type='image/png',
        )

        with self.assertRaisesMessage(ValueError, 'GROQ_API_KEY'):
            views._detect_ingredients(uploaded_file)

    @override_settings(GROQ_API_KEY='test-key', GROQ_MODEL='vision-model')
    @patch('recognition.views.urlopen')
    def test_detect_includes_groq_error_message(self, mock_urlopen):
        error_body = json.dumps({
            'message': 'Model access is not allowed.',
        }).encode('utf-8')
        mock_urlopen.side_effect = HTTPError(
            url=views.GROQ_API_URL,
            code=403,
            msg='Forbidden',
            hdrs=None,
            fp=BytesIO(error_body),
        )

        image_bytes = BytesIO()
        Image.new('RGB', (2, 2), 'white').save(image_bytes, format='PNG')
        uploaded_file = SimpleUploadedFile(
            'ingredients.png',
            image_bytes.getvalue(),
            content_type='image/png',
        )

        with self.assertRaisesRegex(
            ValueError,
            r'HTTP 403.*Model access is not allowed',
        ):
            views._detect_ingredients(uploaded_file)

    @override_settings(GROQ_API_KEY='test-key', GROQ_MODEL='vision-model')
    @patch('recognition.views.urlopen')
    def test_detect_includes_plain_text_groq_error(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError(
            url=views.GROQ_API_URL,
            code=403,
            msg='Forbidden',
            hdrs=None,
            fp=BytesIO(b'Access denied by gateway.'),
        )

        image_bytes = BytesIO()
        Image.new('RGB', (2, 2), 'white').save(image_bytes, format='PNG')
        uploaded_file = SimpleUploadedFile(
            'ingredients.png',
            image_bytes.getvalue(),
            content_type='image/png',
        )

        with self.assertRaisesRegex(
            ValueError,
            r'HTTP 403: Access denied by gateway',
        ):
            views._detect_ingredients(uploaded_file)
