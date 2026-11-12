# 🍳 FoodGenie (ReciScan) – Hệ thống Nhận diện Nguyên liệu & Gợi ý Món ăn bằng AI

**FoodGenie (ReciScan)** là ứng dụng web xây dựng trên nền tảng **Django**, giúp người dùng chụp hoặc tải lên hình ảnh các nguyên liệu nấu ăn có sẵn trong bếp. Hệ thống sử dụng **AI Vision** để tự động nhận diện, khoanh vùng (bounding box) nguyên liệu trên ảnh, cho phép chỉnh sửa danh sách nguyên liệu và gợi ý các công thức món ăn Việt Nam phù hợp nhất.

---

## ✨ Tính năng nổi bật

- **📸 Nhận diện nguyên liệu từ hình ảnh (AI Vision)**:
  - Hỗ trợ tải ảnh từ máy tính hoặc chụp trực tiếp bằng camera điện thoại (tự động xử lý xoay chiều EXIF và tối ưu kích thước ảnh).
  - Tự động phát hiện và vẽ khung nhận diện (2D Bounding Box) kèm tên nguyên liệu bằng tiếng Việt trực tiếp trên ảnh.
  - Cho phép người dùng **thêm, sửa, xóa** nguyên liệu thủ công ngay trên giao diện trước khi tìm món.
- **🍲 Gợi ý món ăn thông minh (Hybrid Recommendation)**:
  - **Cơ sở dữ liệu nội bộ**: Đối chiếu nguyên liệu nhận diện được với kho công thức có sẵn để tính điểm phù hợp (`diem_phu_hop`) và liệt kê các nguyên liệu còn thiếu.
  - **AI Đầu bếp (Groq / LLM)**: Tự động sinh thêm công thức món ăn Việt Nam mới (tối thiểu 3–4 món) kèm thời gian nấu, độ khó, khẩu phần, định lượng nguyên liệu và các bước chế biến chi tiết khi kho dữ liệu chưa đủ món phù hợp.
  - **Hình ảnh món ăn tự động**: Tự động ghép ảnh món ăn từ thư viện nội bộ hoặc tạo/tìm ảnh minh họa món ăn tương ứng.
- **📖 Chi tiết công thức trực quan**:
  - Hiển thị danh sách nguyên liệu dưới dạng checklist tiện lợi khi đi chợ / chuẩn bị nấu.
  - Trình bày từng bước nấu ăn kèm hình minh họa trực quan theo giai đoạn (sơ chế, pha sốt, chế biến, trình bày).
- **👤 Quản lý tài khoản & Cá nhân hóa**:
  - Đăng ký / Đăng nhập bằng tên người dùng hoặc địa chỉ Email, lưu sở thích ẩm thực.
  - **Món ăn yêu thích**: Lưu và quản lý bộ sưu tập các món ăn yêu thích.
  - **Lịch sử xem món**: Tự động lưu lại các công thức đã xem gần đây của từng người dùng.

---

## 🛠️ Công nghệ sử dụng

- **Backend**: Python 3.11+, Django 
- **AI & API**:
  - **xKiro API** (Vision LLMs như `qwen/qwen3.7-flash:free`, `qwen/qwen3.8-omni-flash:free`, v.v.) và **Groq Vision** (dự phòng) cho bài toán nhận diện & khoanh vùng nguyên liệu.
  - **Groq API** (`llama-3.3-70b-versatile`, `llama-3.1-8b-instant`) cho bài toán sáng tạo công thức nấu ăn.
- **Xử lý ảnh**: Pillow (PIL)
- **Cơ sở dữ liệu**: MySQL (`food_AI`)
- **Frontend**: HTML5, CSS3, Vanilla JavaScript, Bootstrap Icons, Google Fonts
- **Triển khai (Deployment)**: Gunicorn, Render (`render.yaml`, `build.sh`), PythonAnywhere

---

## 📂 Cấu trúc thư mục

```text
food_recommendation/
├── config/                 # Cấu hình dự án Django (settings, urls, wsgi, asgi)
├── recognition/            # App nhận diện nguyên liệu, xác thực, lịch sử & yêu thích
│   ├── models.py           # UserProfile, RecognitionSession, DetectedIngredient, Recommendation, ...
│   ├── views.py            # Xử lý ảnh, gọi AI Vision API, vẽ bounding box
│   ├── page_views.py       # Views cho Trang chủ, Gợi ý, Chi tiết món, Yêu thích, Lịch sử
│   ├── forms.py            # Form Đăng ký & Đăng nhập (Username/Email)
│   └── tests.py            # Unit tests cho nhận diện, tài khoản, lịch sử, yêu thích
├── recipes/                # App quản lý món ăn, nguyên liệu và thuật toán gợi ý
│   ├── models.py           # Recipe, Ingredient, RecipeIngredient
│   ├── views.py            # Thuật toán đối sánh công thức DB & gọi Groq API sinh công thức
│   ├── ingredient_utils.py # Chuẩn hóa tên nguyên liệu tiếng Việt
│   └── tests.py            # Unit tests cho gợi ý món ăn
├── templates/              # Giao diện HTML (home, detect, recommendations, recipe_detail, ...)
├── static/                 # Tài nguyên tĩnh (CSS, JavaScript)
├── media/                  # Ảnh món ăn (mon_an/) và ảnh người dùng tải lên (nhan_dien/, uploads/)
├── build.sh                # Script build tự động cho Render
├── render.yaml             # Cấu hình Infrastructure-as-Code cho Render
├── requirements.txt        # Danh sách thư viện Python
└── manage.py               # Công cụ dòng lệnh của Django
```

---

## 🚀 Hướng dẫn cài đặt và chạy локаl (Local Development)

### 1. Clone dự án và tạo môi trường ảo

```bash
git clone <YOUR_GITHUB_REPO_URL>
cd food_recommendation

# Tạo môi trường ảo
python -m venv venv

# Kích hoạt môi trường ảo (Windows PowerShell)
.\venv\Scripts\Activate.ps1
# Hoặc trên macOS/Linux:
# source venv/bin/activate
```

### 2. Cài đặt thư viện

```bash
pip install -r requirements.txt
```

### 3. Cấu hình biến môi trường (`.env`)

Tạo file `.env` tại thư mục gốc của dự án (`food_recommendation/.env`) với nội dung:

```env
SECRET_KEY=your-secret-key
DEBUG=True
USE_SQLITE=1

# API Keys cho nhận diện ảnh và gợi ý công thức
XKIRO_API_KEY=your_xkiro_api_key
GROQ_API_KEY=your_groq_api_key

# (Tùy chọn) Cấu hình MySQL nếu dùng USE_SQLITE=0
DB_NAME=food_AI
DB_USER=root
DB_PASSWORD=1234
DB_HOST=127.0.0.1
DB_PORT=3307
```

### 4. Khởi tạo cơ sở dữ liệu và chạy server

```bash
python manage.py migrate
python manage.py runserver
```

Truy cập ứng dụng tại: `http://127.0.0.1:8000/`

---

## 🧪 Chạy kiểm thử (Unit Tests)

```powershell
$env:USE_SQLITE="1"
python manage.py test
```

---

## ☁️ Triển khai lên Render (public web)

Dự án đã được cấu hình sẵn với đường link public web: https://food-ai-1-m7k6.onrender.com/login/


