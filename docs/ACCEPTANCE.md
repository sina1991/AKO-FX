# گزارش پذیرش نسخه دمو 0.1.0

تاریخ: 2026-11-15. این گزارش توسط عامل پیاده‌سازی تهیه شده؛ ممیزی مستقل یا تأیید Production نیست.

## نتایج مشاهده‌شده

| بررسی | نتیجه |
|---|---|
| مجموعه unittest با Python 3.12 | ۱۲ آزمون موفق |
| ثبت‌نام، جلوگیری از role escalation و خروج | موفق |
| کنترل دسترسی user/admin و ownership | موفق |
| pending/approved/rejected و جلوگیری از تأیید تکراری | موفق |
| Idempotency-Key و تشخیص payload متفاوت | موفق |
| شش تأیید هم‌زمان یک درخواست | فقط یک تأیید موفق؛ بقیه conflict |
| conservation دفترکل و جلوگیری از حذف entries | موفق |
| انتقال کمبود موجودی و rollback | موفق |
| رزرو و آزادسازی اعتبار؛ سود long و زیان short | موفق |
| هزینه Prop، سرمایه مستقل و منع برداشت | موفق |
| failed و بستن خودکار؛ terminal status | موفق |
| passed فقط پس از تحقق سود و بستن position | موفق |
| ماندگاری داده، انقضای Session و محدودیت login | موفق |
| HTTP، static UI، CSP، Origin و JSON نامعتبر | موفق |
| Gateway با چهار domain role جدا و پورت‌های واقعی | موفق |
| syntax JavaScript با node --check | موفق |
| ساخت Python wheel بدون dependency خارجی | موفق |
| مرورگر واقعی Chromium | اجرا نشد: محیط socket موردنیاز Chromium را با Operation not permitted مسدود کرد |
| Docker build / Compose runtime / HTTPS واقعی | اجرا نشد: Docker در محیط موجود نبود |
| استقرار روی VPS کاربر | انجام نشده؛ سرور یا دامنه ارائه نشده |

آزمون‌های Gateway با پنج HTTP server جدا و یک DB مشترک اجرا شده‌اند؛ این بررسی جای تست network و volumeهای Docker را نمی‌گیرد. health endpoint فقط زنده‌بودن همان process را نشان می‌دهد.

## بازتولید

از ریشه مخزن:

```bash
clear
python3 -m unittest discover -s tests -v
python3 -m compileall -q ako_fx
node --check ako_fx/web/app.js
```

Browser journey اختیاری در tests/browser_acceptance.py وجود دارد؛ به playwright و Chromium نیاز دارد. CI آن‌ها را نصب می‌کند؛ برای مرورگر نصب‌شده سیستم می‌توان AKO_CHROMIUM=/usr/bin/chromium را تعیین کرد:

```bash
clear
PYTHONPATH=. python3 tests/browser_acceptance.py
```

CI تعریف شده تا unittest، compile، Compose config، Docker build و گردش مرورگر را بررسی کند. تعریف workflow به معنی اجرای موفق آن نیست؛ نتیجه هر run در GitHub Actions مرجع است.

## محدوده تحویل

گردش end-to-end دمو از ثبت‌نام تا کیف پول، Broker و Prop در سطح API پیاده و بررسی شده است. Web فارسی، CLI، قرارداد OpenAPI، Docker Compose، bootstrap ادمین، backup و راهنمای restore تحویل شده‌اند.

استقلال DB، PostgreSQL، پردازش توزیع‌شده، payment واقعی، سفارش واقعی، feed بازار، مدل دقیق Forex، daily drawdown، MFA، بازیابی رمز، email verification، ابزار مدیریت پلن دلخواه و ممیزی مستقل Production در محدوده این نسخه نیستند. دو پلن و قواعد آن‌ها ثابت‌اند. محدودیت‌های معماری در ARCHITECTURE.md ثبت شده‌اند.

## نصب‌کننده هم‌زیست با Nginx موجود — 2026-11-15

install.sh، راهنمای INSTALLER.md و helper مدیریتی به پروژه اضافه شدند. نقص شبکه Gateway در Compose پیش‌فرض نیز اصلاح شد: Gateway علاوه بر internal به Bridge غیر internal متصل است.

**نتیجه اجرای محلی: ۴۳ تست موفق**، به‌علاوه بررسی syntax اسکریپت‌های Bash و compile فایل‌های Python. مجموعه محلی شامل تست‌های قبلی و تست‌های installer برای انتخاب پورت، کنترل مالکیت config، حفظ volume/admin، pin کردن Docker daemon، جلوگیری از جایگزینی volume گم‌شده، rollback فایل Nginx در خطا، check-only بدون write، و تطابق واقعی certificate/key با OpenSSL است. تست‌های installer که سیستم را تغییر می‌دهند از mock استفاده می‌کنند؛ این‌ها نصب واقعی Linux نیستند.

CI job مستقل installer-host روی Ubuntu 24.04 تعریف شده است: یک سایت TLS قبلی روی 443 می‌سازد، certificate مورداعتماد محلی را در مسیر 30na-dashboard قرار می‌دهد، installer را با Docker/Nginx واقعی اجرا می‌کند، یک wallet و دو حساب ایجاد می‌کند، دوباره نصب را بدون رمز اجرا می‌کند و حفظ داده، admin، backup و سایت قبلی را بررسی می‌کند. تست TLS این job از CA آزمایشی استفاده می‌کند؛ صدور عمومی Let's Encrypt در آن آزمایش نمی‌شود.

اجرای installer روی VPS کاربر و مسیر عمومی اینترنت از این محیط انجام نشده است. هیچ ادعای تأیید Production اضافه نشده است. نتایج مشاهده‌شده CI پس از اجرا مرجع پذیرش host هستند.

### نتیجه مشاهده‌شده آزمون نصب واقعی در CI

Job `installer-host` در [run شماره ۵](https://github.com/sina1991/AKO-FX/actions/runs/43743388104/job/132901258314) موفق شد: نصب واقعی پنج container روی Ubuntu 24.04، انتشار `127.0.0.1:9080`، HTTPS روی `8443` با certificate معتبر fixture، گردش wallet/Broker/Prop، backup سازگار و اجرای دوباره با حفظ admin و داده‌ها بررسی شدند. hash فایل سایت قبلی و پاسخ آن روی 443 نیز حفظ شدند.

در همان run، ۴۳ تست، Compose config و Docker build موفق بودند؛ بخش browser به‌علت انتقال `ubuntu-latest` به Ubuntu 26.04 و ناسازگاری Playwright قفل‌شده متوقف شد. runner تست به Ubuntu 24.04 تثبیت شد. این خطا مربوط به آماده‌سازی ابزار مرورگر بود و job نصب واقعی موفق ماند.
