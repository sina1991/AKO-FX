# نصب کامل و ادامه نصب با install.sh

این روش برای Ubuntu 24.04، Python 3.11+، دسترسی root و یک domain واقعی طراحی شده است. سرور می‌تواند از قبل پروژه 30nA یا Nginx داشته باشد. installer فقط منابع مشخص AKO-FX را مدیریت می‌کند؛ وجود تنظیم متعارض یا ناشناخته باعث توقف با خطا می‌شود. عدم تداخل روی تمام ترکیب‌های دلخواه سرور تضمین نمی‌شود؛ preflight و بررسی نهایی بخشی از اجرای واقعی‌اند.

## فرمان اصلی از GitHub

```bash
clear
curl -fsSL https://raw.githubusercontent.com/sina1991/AKO-FX/main/install.sh -o /tmp/ako-fx-install.sh &&
bash /tmp/ako-fx-install.sh --domain x.30na.top
```

با کاربر غیر root، فرمان دوم را با `sudo bash` اجرا کنید. curl و دسترسی خروجی به GitHub لازم است. bootstrap کد را در directory موقت دریافت و SHA آن را ثبت می‌کند؛ پوشه checkout فعلی شما دست‌نخورده می‌ماند. این installer از curl pipe به shell استفاده نمی‌کند؛ خطای دانلود باعث جلوگیری از شروع نصب می‌شود.

در صورت نیاز به نسخه مشخص، `--ref COMMIT_OR_TAG` اضافه کنید. وقتی install.sh از یک checkout تمیز محلی اجرا می‌شود، همان HEAD محلی نصب می‌شود؛ برای انتخاب ref متفاوت از فرمان دانلود استفاده کنید. فایل‌های tracked محلی اصلاح‌شده پذیرفته نمی‌شوند.

## بررسی بدون نصب

```bash
clear
bash /tmp/ako-fx-install.sh --domain x.30na.top --check-only
```

check-only container، DB، Nginx، firewall یا package نصب/تغییر نمی‌دهد. دریافت source در فضای موقت و خواندن Docker/Nginx انجام می‌شود. اگر git یا Python وجود نداشته باشد، این حالت متوقف می‌شود. اجرای اصلی در صورت نیاز این پیش‌نیازها را روی Ubuntu 24.04 نصب می‌کند.

check-only موفق جای build image، اجرای service، صدور certificate یا تست HTTPS واقعی را نمی‌گیرد. با `--non-interactive` باید domain و در صورت نیاز email صدور certificate مشخص باشند. برای نصب تازه و بدون admin، credentials اولیه نیز لازم است.

## رفتار روی سرور فعلی x.30na.top

- Nginx فعلی و سایت پروژه قبلی روی 80/443 باقی می‌مانند؛ AKO-FX در فایل site جدا اجرا می‌شود.
- certificate معتبر پوشش‌دهنده دامنه در `/etc/letsencrypt/live/*` شناسایی می‌شود. مسیر `30na-dashboard` نیز از همین روش شناسایی می‌شود. کلید خصوصی جابه‌جا یا چاپ نمی‌شود.
- اولین پورت آزاد HTTPS از 8443 و اولین backend آزاد از 9080 انتخاب می‌شوند. domain serviceها پورت عمومی ندارند.
- Gateway علاوه بر شبکه internal به Bridge مخصوص host-access متصل است و فقط روی loopback منتشر می‌شود.
- `Host` همراه شماره پورت به API می‌رسد؛ این مورد برای کنترل Origin درخواست‌های POST لازم است.
- Caddy دوم اجرا نمی‌شود. Docker daemon موجود، تنظیمات Docker یا daemon اختصاصی Sandbox پروژه قبلی بازپیکربندی/متوقف نمی‌شوند.

برای پورت‌های صریح، اگر آزاد باشند:

```bash
clear
bash /tmp/ako-fx-install.sh --domain x.30na.top --port 8443 --backend-port 9080
```

پورت اشغال‌شده با flag صریح خطا می‌دهد؛ installer سرویس اشغال‌کننده را متوقف نمی‌کند. در حالت انتخاب خودکار، پورت بعدی امتحان می‌شود. پورت‌های ثبت‌شده در ادامه نصب ثابت می‌مانند.

## حفظ داده و admin نصب قبلی

installer containerهای Compose با project name دقیق `ako-fx` را بررسی می‌کند. service، command برنامه و named volume متصل به `/data` باید قابل شناسایی باشند. همان volume در Compose تولیدشده به‌صورت external استفاده می‌شود؛ داده به volume خالی منتقل نمی‌شود.

وجود چند volume متفاوت، bind mount ناشناخته یا container غیرمنتظره در همین project باعث توقف می‌شود. Caddy فعال قبلی خودکار متوقف نمی‌شود؛ باید نقش آن پیش از مهاجرت روشن باشد.

قبل از تغییر containerهای موجود، از SQLite با backup API snapshot سازگار گرفته و در `/var/backups/ako-fx/` با دسترسی محدود ذخیره می‌شود. backup ناموفق با DB موجود، ادامه نصب را متوقف می‌کند. کپی دیگری در volume باقی می‌ماند؛ مدیریت retention پشتیبان‌ها دستی است.

اگر هر admin موجود باشد، رمز و حساب او حفظ می‌شود. در غیر این صورت email و رمز حداقل ۱۲ کاراکتری دریافت می‌شود؛ رمز در command line یا state ذخیره نمی‌شود.

## Docker و پیش‌نیازها

اگر Docker در یک host تازه موجود نباشد، packageهای Ubuntu `docker.io` و `docker-compose-v2` نصب و daemon محلی راه‌اندازی می‌شوند. Nginx/OpenSSL/Certbot فقط در صورت نیاز نصب می‌شوند. از Docker ازقبل‌نصب‌شده‌ای که پاسخ نمی‌دهد، daemon جایگزین ساخته نمی‌شود. روی host دارای 30nA، نبود CLI نیز باعث توقف می‌شود تا daemon دیگری بدون آگاهی ایجاد نشود.

installer از Docker endpoint محلی انتخاب‌شده در context/DOCKER_HOST استفاده می‌کند و endpoint و ID daemon را ذخیره می‌کند. ادامه نصب و helper از همان endpoint استفاده می‌کنند؛ تغییر shell context به ایجاد یک DB خالی منجر نمی‌شود. endpointهای remote پشتیبانی نمی‌شوند.

daemon اختصاصی کاربر `30na-sandbox` برای AKO-FX پذیرفته نمی‌شود. اگر فقط همان daemon در دسترس باشد، ابتدا باید یک Docker daemon کاربردی مستقل آماده شود؛ installer محدودیت امنیتی Sandbox را تغییر نمی‌دهد. منابع CPU/RAM/disk به ظرفیت VPS وابسته‌اند؛ installer برای سرویس‌های موجود ظرفیت رزرو نمی‌کند.

## HTTPS در نصب تازه

اگر certificate معتبر وجود نداشته باشد، email حساب ACME دریافت می‌شود. installer برای domain فاقد site متعارض، مسیر webroot چالش را در یک فایل Nginx متعلق به خودش ایجاد می‌کند و certificate با Certbot می‌گیرد. اجرای این مرحله email را به Let's Encrypt ارسال و Terms of Service آن را می‌پذیرد.

رکوردهای A/AAAA باید صحیح باشند و TCP 80 از اینترنت به Nginx برسد. Certbot با webroot اجرا می‌شود و برای صدور/تمدید certificate جدید Nginx را متوقف نمی‌کند. timer تمدید و hook reload فقط برای certificate صادرشده توسط همین installer تنظیم می‌شوند. certificate قبلی 30nA و روش تمدید آن تغییر نمی‌کنند؛ اگر renewal قبلی Nginx را موقتاً متوقف کند، AKO-FX نیز در همان فاصله وقفه خواهد داشت.

برای certificate خارج از مسیر شناسایی خودکار:

```bash
clear
bash /tmp/ako-fx-install.sh --domain x.30na.top \
  --cert /path/to/fullchain.pem --key /path/to/privkey.pem
```

certificate باید domain را پوشش دهد، با key تطابق داشته باشد و حداقل ۲۴ ساعت اعتبار داشته باشد. موفقیت نهایی، علاوه بر این بررسی، به trust سیستم برای TLS نیاز دارد؛ verify خاموش نمی‌شود.

## نتیجه و ورود

پس از build و startup، installer Gateway را از loopback بررسی می‌کند؛ سپس از مسیر HTTPS با hostname/SNI واقعی، صفحه AKO-FX و مسیرهای Identity/Wallet/Broker/Prop را بررسی می‌کند. فقط پس از موفقیت و وجود admin، آدرس ورود چاپ می‌شود:

`https://x.30na.top:8443` یا پورت آزاد انتخاب‌شده دیگر.

این تأیید محلی است؛ firewall پنل VPS و مسیر اینترنت کاربر از داخل سرور قابل اثبات نیستند. اگر UFW فعال باشد فقط پورت HTTPS جدید مجاز می‌شود؛ UFW غیرفعال فعال نمی‌شود. در firewall ارائه‌دهنده نیز TCP همان پورت را باز کنید.

## مدیریت و ادامه نصب

```bash
clear
sudo ako-fx status
sudo ako-fx logs
sudo ako-fx compose ps
```

ساخت admin اضافی در صورت نیاز:

```bash
clear
sudo ako-fx admin --email second-admin@example.com
```

اگر نصب متوقف شد، پس از رفع خطا همان فرمان نصب را تکرار کنید. `docker compose down -v`، پاک‌کردن volume یا حذف state برای دورزدن خطا مناسب نیست. در ادامه نصب domain، پورت‌ها، daemon و volume از state حفظ می‌شوند.

از این پس برای این نصب از `ako-fx compose ...` استفاده کنید. اجرای Compose قدیمی از `~/AKO-FX` می‌تواند gateway را دوباره به تنظیم قبلی برگرداند؛ آن checkout منبع مدیریت نصب جدید نیست.

## مسیرهای نصب

| مسیر | کاربرد |
|---|---|
| `/opt/ako-fx/releases/<SHA>` | source نصب‌شده با SHA مشخص |
| `/etc/ako-fx/install.json` | state، پورت‌ها، daemon، volume و مرحله نصب؛ بدون رمز |
| `/etc/ako-fx/compose.json` | تنظیم مستقل پنچ سرویس |
| `/etc/ako-fx/compose.previous.json` | تنظیم قبلی برای بررسی recovery |
| `/etc/nginx/sites-available/ako-fx-installer` | HTTPS site متعلق به AKO-FX |
| `/etc/nginx/sites-available/ako-fx-acme` | فقط هنگام صدور certificate جدید |
| `/usr/local/sbin/ako-fx` | helper مدیریتی root-only |
| `/var/backups/ako-fx/` | snapshotهای DB |

Config غیرمتعلق به installer بازنویسی نمی‌شود. تغییر دستی فایل Nginx مدیریت‌شده با hash شناسایی و اجرای بعدی متوقف می‌شود. اگر `nginx -t` یا reload شکست بخورد، همان site متعلق به AKO-FX به نسخه قبل برمی‌گردد. rollback کامل packageها، imageها یا DB خودکار نیست؛ منابع ساخته‌شده برای ادامه نصب حفظ می‌شوند. پیش از upgrade عمده، backup و پنجره نگهداری در نظر بگیرید.

## اجرای بدون تعامل

تنها برای automation تحت کنترل administrator، فایل رمز root-owned با mode 0600 بسازید و مسیر آن را بدهید:

```bash
clear
bash /tmp/ako-fx-install.sh --domain ako.example.com \
  --email operator@example.com --admin-email admin@example.com \
  --admin-password-file /root/ako-admin-password --non-interactive
```

فایل فقط از stdin به bootstrap داخل container ارسال می‌شود. آن را پس از ساخت admin طبق سیاست خود حذف کنید. در ادامه نصب با admin موجود، فایل رمز لازم نیست.

## پذیرش و محدودیت آزمون

[گزارش پذیرش](ACCEPTANCE.md) نتایج واقعی را ثبت می‌کند. تست‌های واحد از عملیات سیستم mock می‌سازند؛ smoke job جدا روی Ubuntu 24.04 برای Docker/Nginx/TLS واقعی و اجرای دوباره با حفظ داده تعریف شده است. اجرای موفق تست واحد، معادل اجرای موفق روی VPS شما یا تأیید Production نیست.

بررسی نهایی HTTPS پس از reload منتظر آماده‌شدن listener می‌ماند و Connection refused گذرا را تا ۱۵ ثانیه retry می‌کند. خطای certificate از این retry معاف نیست و نصب را متوقف می‌کند.
