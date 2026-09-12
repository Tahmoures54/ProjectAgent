# Project Agent — سامانه هوشمند کنترل پروژه و CBS

**Project Agent** پلتفرم تحت‌وب **Project Controls** برای شرکت‌های مهندسی، پیمانکاری و مشاور است:  
**WBS · CBS · EVM · گزارش روزانه کارگاه · کانسرن با کنترل دسترسی · تاریخ جلالی · Multi-tenant**

هدف: آماده‌ی **داده واقعی**، جذب کاربر، و جلوتر از نرم‌افزارهای صرفاً تسک‌محور یا اکسل‌محور.

---

## چرا از رقبا متمایز است؟

| قابلیت | Project Agent | بسیاری از رقبا |
|--------|----------|----------------|
| Earned Value (CPI/SPI/EAC/S-Curve) | ✅ | محدود / ندارد |
| CBS + قرارداد + صورت‌وضعیت + Excel | ✅ | جزئی |
| گزارش روزانه با تأیید قبل از اعمال پیشرفت | ✅ | نادر |
| کانسرن با visibility (خصوصی/پروژه/مدیران/شرکت) | ✅ | ندارد |
| تقویم جلالی بومی | ✅ | ضعیف |
| RBAC + Multi-tenant | ✅ | متغیر |
| Docker + `/health` + هدرهای امنیتی | ✅ | — |

---

## امکانات اصلی

### کنترل پروژه
- WBS / CBS سلسله‌مراتبی
- EVM: PV, EV, AC, CPI, SPI, EAC, TCPI + S-Curve
- داشبورد پیشرفت فیزیکی، زمانی، مالی

### گزارش روزانه (Daily Report)
- ثبت توسط پیمانکار/گروه اجرایی
- گردش: پیش‌نویس → ارسال → بررسی → تأیید / رد / اصلاح
- اعمال پیشرفت روی آیتم‌ها **فقط پس از تأیید**

### کانسرن‌ها (Concerns)
- دسته‌بندی: فنی، زمان، هزینه، ایمنی، کیفیت، قراردادی، …
- اولویت و وضعیت (باز تا بسته / ارجاع)
- **کنترل مشاهده** در چهار سطح
- نظرات (عمومی / داخلی مدیران) + تاریخچه

### قرارداد و آیتم
- قرارداد، الحاقیه، آیتم، Import Excel / Export CSV

### امنیت و استقرار
- جستجوی سراسری پروژه‌ها / گزارش روزانه / کانسرن
- اینباکس عملیاتی (گزارش در انتظار تأیید + کانسرن بحرانی)
- داشبورد با KPI واقعی (قرارداد، تأخیر، کانسرن باز)
- 2FA، RBAC، CSRF، هدرهای امنیتی
- PostgreSQL توصیه‌شده، Docker، Gunicorn
- `GET /health` برای مانیتورینگ

---

## پیش‌نیاز

- Python 3.10+
- PostgreSQL (production) یا SQLite (توسعه)
- Docker (اختیاری)

---

## نصب توسعه

```bash
git clone https://github.com/Tahmoures54/ProjectAgent.git
cd ProjectAgent
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # SECRET_KEY را عوض کنید
python app.py
```

http://127.0.0.1:5000

جداول جدید (گزارش روزانه، کانسرن) در حالت توسعه با `create_all` ساخته می‌شوند.

---

## Production

```bash
# .env
PMS_ENV=production
SECRET_KEY=<random-48+chars>
DATABASE_URL=postgresql+psycopg2://...
PMS_AUTO_CREATE_DB=0   # ترجیحاً Alembic

docker compose up -d --build
curl https://your-domain/health
```

- هرگز `.env` واقعی را commit نکنید
- SSL + `SECRET_KEY` قوی الزامی است

---

## نقش‌ها (RBAC)

| نقش | کاربرد |
|-----|--------|
| owner / admin | پلتفرم |
| company_admin | کل شرکت |
| manager | پروژه + تأیید گزارش + کانسرن |
| contractor | گزارش روزانه + ثبت کانسرن |
| viewer | مشاهده |

---

## ساختار کلیدی

```
pms_app/
  blueprints/   auth, projects, contracts, items, daily_reports, concerns, billing, ...
  models/       Project, ContractItem, DailyReport, Concern, ...
  utils/        evm, security, jalali, entitlements
```

---

## تست

```bash
pytest -q
```

---

**Project Agent** — کنترل پروژه را حرفه‌ای، بومی و قابل دفاع کنید.
