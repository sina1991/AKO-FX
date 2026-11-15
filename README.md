# AKO-FX

پلتفرم **DEMO ONLY** برای کاربر، کیف پول، **30nA-Broker** و **30nA-Prop**؛ با Web فارسی و CLI مشترک. نسخه `0.1.0`، مناسب اجرای آزمایشی روی یک VPS لینوکسی.

ثبت‌نام ← درخواست اعتبار آزمایشی ← تأیید ادمین ← کیف پول ← تخصیص به Broker یا خرید Prop.

## قابلیت‌های پیاده‌شده

- ثبت‌نام، ورود با password hashing، Session هشت‌ساعته، خروج و نقش‌های user/admin.
- درخواست اعتبار، تأیید/رد ادمین، دفترکل دوطرفه و انتقال اتمی؛ تمام مبالغ با integer cents.
- حساب Broker، انتقال رفت‌وبرگشت اعتبار، معاملات buy/sell، رزرو اعتبار، بستن و محاسبه PnL.
- دو پلن Prop، پرداخت هزینه با اعتبار آزمایشی، صدور سرمایه، هدف سود ۱۰٪ و حد زیان کل ۱۰٪.
- سناریوی مصنوعی up/down/reset توسط ادمین؛ گام ۵٪ قیمت پایه در بازه ۵۰٪ تا ۱۵۰٪.
- API مشترک Web/CLI، audit log، کنترل مالکیت و Idempotency-Key برای عملیات مالی.
- اجرای یکپارچه یا پنج سرویس مستقل با Docker Compose، reverse proxy و HTTPS خودکار Caddy.

تمام اعتبارها آزمایشی‌اند. هیچ payment gateway، کلید معاملاتی، اتصال اجرای واقعی یا حالت LIVE وجود ندارد. قیمت‌ها مصنوعی‌اند؛ مدل PnL از تبدیل واقعی ارزهای Forex، spread، commission و leverage استفاده نمی‌کند.

## اجرای محلی با Python 3.11+

از ریشه checkout اجرا کنید. برنامه به dependency خارجی Python نیاز ندارد.

```bash
clear
python3 -m ako_fx.manage init
python3 -m ako_fx.manage create-admin --email admin@example.com
```

رمز ادمین تعاملی دریافت می‌شود؛ رمز پیش‌فرض وجود ندارد.

```bash
clear
python3 -m ako_fx.server
```

مرورگر: `http://127.0.0.1:8080`. با حساب جدید ثبت‌نام و اعتبار درخواست کنید؛ سپس با ادمین درخواست را تأیید کنید.

## استقرار VPS

Docker Engine و Compose plugin را نصب کنید و دامنه را به IP سرور متصل کنید. سپس:

```bash
clear
cp .env.example .env
nano .env
```

مقدار `AKO_DOMAIN` را دامنه واقعی قرار دهید. پورت‌های ورودی 80/443 باید باز باشند.

```bash
clear
docker compose up -d --build
docker compose exec identity python -m ako_fx.manage create-admin --email admin@example.com
```

Dashboard در `https://YOUR_DOMAIN` در دسترس است. پورت‌های domain service روی IP عمومی منتشر نمی‌شوند. جزئیات نصب و backup در [راهنمای استقرار](docs/DEPLOYMENT.md).

## CLI

ورود رمز را بدون ثبت در shell history دریافت می‌کند:

```bash
clear
python3 -m ako_fx.cli login user@example.com
```

token پاسخ را در `AKO_TOKEN` قرار دهید؛ آن را در پیام یا مخزن منتشر نکنید. برای VPS، `AKO_URL=https://YOUR_DOMAIN` را تنظیم کنید.

```bash
clear
read -rsp 'Session token: ' AKO_TOKEN
export AKO_TOKEN
python3 -m ako_fx.cli GET /api/wallet
python3 -m ako_fx.cli POST /api/wallet/requests --data '{"amount":"1000"}'
```

هر درخواست POST مالی به‌صورت خودکار کلید یکتا دارد. برای retry همان عملیات، کلید قبلی را با `--key` دوباره استفاده کنید. [مرجع API](docs/API.md).

## بررسی‌ها و محدودیت‌ها

```bash
clear
python3 -m unittest discover -s tests -v
```

[گزارش پذیرش](docs/ACCEPTANCE.md) · [معماری](docs/ARCHITECTURE.md) · [راهنمای کاربر](docs/USER_GUIDE.md) · [ورود Agent](AGENTS.md).

استقلال سرویس‌ها در این نسخه در سطح process، API و module است. SQLite و Session store بین سرویس‌ها روی یک host مشترک‌اند؛ استقلال پایگاه داده و استقرار چندسروری، rate limiting زیرساختی و ممیزی مستقل Production در این نسخه انجام نشده است. نتیجه آزمون محلی به معنی استقرار یا پذیرش امنیتی سرور شما نیست.
