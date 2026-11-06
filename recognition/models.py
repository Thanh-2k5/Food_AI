
from django.conf import settings
from django.db import models

from recipes.models import Recipe, Ingredient


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    food_preference = models.CharField(max_length=120, blank=True)

    class Meta:
        db_table = "ho_so_nguoi_dung"

    def __str__(self):
        return f"Hồ sơ {self.user.username}"


class RecipeHistory(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recipe_history",
    )
    recipe = models.ForeignKey(
        Recipe,
        on_delete=models.CASCADE,
        related_name="user_history",
    )
    last_viewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "lich_su_mon_an"
        ordering = ["-last_viewed_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "recipe"],
                name="uq_lich_su_nguoi_dung_mon_an",
            )
        ]

    def __str__(self):
        return f"{self.user} đã xem {self.recipe}"


class FavoriteRecipe(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="favorite_recipes",
    )
    recipe = models.ForeignKey(
        Recipe,
        on_delete=models.CASCADE,
        related_name="user_favorites",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "mon_an_yeu_thich"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "recipe"],
                name="uq_yeu_thich_nguoi_dung_mon_an",
            )
        ]

    def __str__(self):
        return f"{self.user} yêu thích {self.recipe}"


class RecognitionSession(models.Model):
    """Lưu thông tin mỗi lần nhận diện ảnh."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recognition_sessions",
    )
    anh_dau_vao = models.ImageField(upload_to="nhan_dien/")
    anh_da_xu_ly = models.ImageField(
        upload_to="uploads/",
        blank=True,
        null=True,
    )
    nha_cung_cap = models.CharField(max_length=30, default="Groq")
    trang_thai = models.CharField(
        max_length=20,
        choices=[
            ("cho_xu_ly", "Chờ xử lý"),
            ("thanh_cong", "Thành công"),
            ("that_bai", "Thất bại"),
        ],
        default="cho_xu_ly"
    )
    ngay_tao = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "phien_nhan_dien"
        ordering = ["-ngay_tao"]

    def __str__(self):
        return f"Phiên nhận diện {self.id}"


class DetectedIngredient(models.Model):
    """Lưu các thực phẩm Groq nhận diện từ ảnh."""

    phien_nhan_dien = models.ForeignKey(
        RecognitionSession,
        on_delete=models.CASCADE,
        related_name="thuc_pham_da_nhan_dien"
    )
    thuc_pham = models.ForeignKey(
        Ingredient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ket_qua_nhan_dien"
    )
    ten_da_nhan_dien = models.CharField(max_length=100)
    do_tin_cay = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True
    )

    class Meta:
        db_table = "thuc_pham_nhan_dien"

    def __str__(self):
        return self.ten_da_nhan_dien


class Recommendation(models.Model):
    """Lưu món ăn được gợi ý theo phiên nhận diện."""

    phien_nhan_dien = models.ForeignKey(
        RecognitionSession,
        on_delete=models.CASCADE,
        related_name="ket_qua_goi_y"
    )
    mon_an = models.ForeignKey(
        Recipe,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lich_su_goi_y"
    )
    diem_phu_hop = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0
    )
    thuc_pham_con_thieu = models.JSONField(default=list, blank=True)
    ngay_tao = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ket_qua_goi_y"
        ordering = ["-diem_phu_hop"]

    def __str__(self):
        return f"Kết quả gợi ý {self.id}"
