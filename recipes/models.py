from django.db import models


class Recipe(models.Model):
    """Thông tin món ăn."""

    ten_mon = models.CharField(max_length=200)
    mo_ta = models.TextField(blank=True)
    anh_mon = models.ImageField(
        upload_to="mon_an/",
        blank=True,
        null=True
    )
    anh_mon_url = models.URLField(blank=True, max_length=1000)
    thoi_gian_nau = models.PositiveIntegerField(
        help_text="Thời gian nấu tính bằng phút"
    )
    do_kho = models.CharField(
        max_length=20,
        choices=[
            ("De", "Dễ"),
            ("Trung binh", "Trung bình"),
            ("Kho", "Khó"),
        ],
        default="De"
    )
    cong_thuc = models.TextField()
    so_khau_phan = models.PositiveIntegerField(default=1)
    nguon_du_lieu = models.CharField(
        max_length=30,
        choices=[
            ("thu_cong", "Nhập thủ công"),
            ("groq", "Groq API"),
        ],
        default="thu_cong"
    )
    dang_su_dung = models.BooleanField(default=True)
    ngay_tao = models.DateTimeField(auto_now_add=True)
    ngay_cap_nhat = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mon_an"
        ordering = ["ten_mon"]

    def __str__(self):
        return self.ten_mon


class Ingredient(models.Model):
    """Danh mục thực phẩm, không bao gồm gia vị."""

    ten_thuc_pham = models.CharField(max_length=100)
    ten_chuan_hoa = models.CharField(
        max_length=100,
        unique=True
    )
    loai_thuc_pham = models.CharField(max_length=50)
    dang_su_dung = models.BooleanField(default=True)

    class Meta:
        db_table = "thuc_pham"
        ordering = ["ten_thuc_pham"]

    def __str__(self):
        return self.ten_thuc_pham


class RecipeIngredient(models.Model):
    """Các thực phẩm cần có cho một món ăn."""

    mon_an = models.ForeignKey(
        Recipe,
        on_delete=models.CASCADE,
        related_name="thanh_phan"
    )
    thuc_pham = models.ForeignKey(
        Ingredient,
        on_delete=models.CASCADE,
        related_name="cac_mon_an"
    )
    so_luong = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True
    )
    don_vi = models.CharField(max_length=30, blank=True)
    la_tuy_chon = models.BooleanField(default=False)

    class Meta:
        db_table = "thanh_phan_mon_an"
        constraints = [
            models.UniqueConstraint(
                fields=["mon_an", "thuc_pham"],
                name="uq_mon_an_thuc_pham"
            )
        ]

    def __str__(self):
        return f"{self.mon_an.ten_mon} - {self.thuc_pham.ten_thuc_pham}"

# Create your models here.
