# استقرار روی یک Linux VPS

**روش پیشنهادی:** [install.sh و نصب بدون تداخل با Nginx موجود](INSTALLER.md). دستورهای این سند برای روش دستی‌اند. اگر با installer نصب کرده‌اید، به‌جای compose پیش‌فرض از `sudo ako-fx compose ...` استفاده کنید.

پیش‌نیاز: Ubuntu 24.04 LTS یا Linux سازگار، Docker Engine با Compose plugin، Git، دامنه با DNS متصل به IP عمومی و پورت‌های 80/443 باز. نصب Docker در این مخزن خودکار نشده است.

## دریافت و بررسی

```bash
clear
git clone https://github.com/sina1991/AKO-FX.git
cd AKO-FX
git remote -v
git branch --show-current
git rev-parse HEAD
```

## تنظیم دامنه

```bash
clear
cp .env.example .env
nano .env
```

مثال: AKO_DOMAIN=demo.yourdomain.com. برای HTTPS خودکار، DNS و دسترسی عمومی دامنه باید صحیح باشند.

## اجرا و ساخت ادمین

```bash
clear
docker compose up -d --build
docker compose ps
docker compose exec identity python -m ako_fx.manage create-admin --email admin@yourdomain.com
```

رمز دو بار تعاملی وارد می‌شود. فقط gateway روی loopback host منتشر است؛ Caddy ورودی عمومی HTTPS را ارائه می‌کند. دامنه‌های backend در network داخلی اجرا می‌شوند. سرویس‌های domain غیر root، با root filesystem فقط‌خواندنی و بدون Linux capabilities اضافی اجرا می‌شوند.

## بررسی

```bash
clear
curl --fail https://YOUR_DOMAIN/health
docker compose logs --tail=50 gateway wallet broker prop identity
```

/health تنها سلامت process پاسخ‌دهنده است؛ سلامت کامل دامنه‌ها را تضمین نمی‌کند. Compose برای سرویس‌های داخلی healthcheck جدا دارد. برای پذیرش کامل، گردش ثبت‌نام تا تأیید و معامله را طبق USER_GUIDE انجام دهید.

## CLI روی سرور

در checkout و با Python 3.11+:

```bash
clear
export AKO_URL=https://YOUR_DOMAIN
python3 -m ako_fx.cli login user@example.com
read -rsp 'Session token: ' AKO_TOKEN
export AKO_TOKEN
python3 -m ako_fx.cli GET /api/wallet
```

## Backup سازگار با WAL

```bash
clear
docker compose exec identity python -m ako_fx.manage backup /data/backup-20261115.db
docker compose cp identity:/data/backup-20261115.db ./backup-20261115.db
chmod 600 backup-20261115.db
```

نام فایل را برای هر backup تغییر دهید. فایل شامل password hash و Sessionهای فعال است؛ آن را محرمانه و در محل امن مستقل از VPS نگه دارید. فایل raw ako.db را حین اجرا به تنهایی کپی نکنید؛ SQLite backup API یک snapshot سازگار می‌سازد.

## Restore در پنجره توقف

ابتدا مسیر backup را بررسی و از DB فعلی backup بگیرید. سپس:

```bash
clear
docker compose stop gateway identity wallet broker prop
docker compose run --rm --no-deps --user 0 identity python -c "import os; [os.remove('/data/'+n) for n in ('ako.db','ako.db-wal','ako.db-shm') if os.path.exists('/data/'+n)]"
docker compose cp ./backup-20261115.db identity:/data/ako.db
docker compose run --rm --no-deps --user 0 identity python -c "import os; os.chown('/data/ako.db',10001,10001); os.chmod('/data/ako.db',0o600)"
docker compose up -d
```

Restore داده‌های بعد از زمان backup را کنار می‌گذارد و Sessionهای آن snapshot را نیز برمی‌گرداند. پیش از انتشار دوباره می‌توان تمام Sessionها را با عملیات محلی DB لغو کرد. ابتدا این روش را روی محیط آزمایشی تمرین کنید.

## به‌روزرسانی و توقف

قبل از update، backup بگیرید و release موردنظر را بررسی کنید. سپس checkout همان commit/tag و `docker compose up -d --build` اجرا شود. این نسخه migration framework ندارد؛ تغییر schema نیازمند طرح migration و restore سازگار است.

`docker compose stop` داده را نگه می‌دارد. `docker compose down -v` volumeهای DB و TLS را حذف می‌کند؛ برای توقف عادی از آن استفاده نکنید.

## محدودیت تأیید

سرور کاربر در این مأموریت در دسترس نبوده و استقرار واقعی انجام نشده است. Docker در محیط پیاده‌سازی موجود نبوده؛ build و Compose runtime باید توسط CI و سپس روی VPS بررسی شوند. این نسخه جایگاه یک demo قابل اجرا را دارد و پذیرش مستقل Production هنوز انجام نشده است.
