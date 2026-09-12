# Path: pms_app/config/testing.py

class TestingConfig:
    """
    تنظیمات مخصوص اجرای تست‌ها.
    این کلاس توسط create_app با config_name="testing" بارگذاری می‌شود.
    """

    # فعال‌سازی حالت تست (باعث می‌شود _ensure_db_schema_and_seed اجرا نشود)
    TESTING = True

    # کلید مخفی برای session و CSRF
    SECRET_KEY = "test-secret-key"

    # دیتابیس در حافظه (در conftest ممکن است به فایل موقت تغییر کند)
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # غیرفعال‌سازی CSRF در تست‌ها (برای ساده‌سازی ارسال فرم‌ها)
    WTF_CSRF_ENABLED = False

    # غیرفعال‌سازی Debug برای جلوگیری از رندر خطاهای تعاملی در تست
    DEBUG = False

    OWNER_EMAIL = ""
    OWNER_EMAILS = ""