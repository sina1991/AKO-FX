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

## نصب کامل با install.sh — سازگار با سرور دارای پروژه قبلی

روی **Ubuntu 24.04**، با کاربر root اجرا کنید:

```bash
clear
curl -fsSL https://raw.githubusercontent.com/sina1991/AKO-FX/main/install.sh -o /tmp/ako-fx-install.sh &&
bash /tmp/ako-fx-install.sh --domain x.30na.top
```

دامنه مثال را برای سرور دیگر تغییر دهید. نصب‌کننده کد را از GitHub دریافت و SHA را ثبت می‌کند، Docker/Compose و Nginx موجود را بررسی می‌کند، certificate معتبر دامنه را پیدا می‌کند و AKO-FX را روی **اولین پورت HTTPS آزاد از 8443** نصب می‌کند. Gateway فقط روی loopback و پورت آزاد از 9080 منتشر می‌شود. در پایان، آدرس ورود دقیق چاپ می‌شود؛ معمولاً `https://x.30na.top:8443`.

در نصب فعلی، volume و ادمین از containerهای پروژه `ako-fx` شناسایی و حفظ می‌شوند. قبل از تغییر نسخه، از DB موجود backup سازگار گرفته می‌شود. اگر ادمین وجود نداشته باشد، ایمیل و رمز به‌صورت تعاملی دریافت می‌شود. نصب‌کننده Caddy دوم روی 80/443 راه‌اندازی نمی‌کند و سایت‌های موجود Nginx را بازنویسی نمی‌کند.

اگر certificate موجود نباشد، نصب‌کننده email حساب Let's Encrypt را می‌پرسد و برای دامنه‌ای که site متعارض ندارد، certificate رایگان با Certbot webroot می‌گیرد. این مرحله به DNS صحیح و پورت عمومی 80 نیاز دارد. فقط در صورت نیاز، packageهای سیستم نصب می‌شوند؛ روی host دارای 30nA، Docker خراب/ناموجود با daemon تازه جایگزین نمی‌شود.

برای بررسی اولیه بدون تغییر تنظیمات یا containerها:

```bash
clear
bash /tmp/ako-fx-install.sh --domain x.30na.top --check-only
```

مدیریت پس از نصب:

```bash
clear
sudo ako-fx status
sudo ako-fx logs
```

اگر firewall پنل VPS فعال است، پورت HTTPS چاپ‌شده را مجاز کنید. UFW فعال به‌صورت خودکار برای همان پورت تنظیم می‌شود؛ UFW غیرفعال فعال نمی‌شود. [راهنمای کامل نصب، ادامه نصب و بازیابی](docs/INSTALLER.md).

روش Docker Compose دستی برای مدیریت اختصاصی همچنان در [راهنمای استقرار](docs/DEPLOYMENT.md) موجود است؛ تنظیم نصب خودکار در `/etc/ako-fx/compose.json` قرار می‌گیرد.

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
