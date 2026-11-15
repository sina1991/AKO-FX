# API و CLI

تمام مسیرها JSON هستند. به‌جز register/login/health، هدر `Authorization: Bearer TOKEN` الزامی است. POSTهای دامنه به `Idempotency-Key` یکتای ۸ تا ۱۲۸ کاراکتر نیاز دارند. در retry کلید و payload را بدون تغییر نگه دارید. مقدار amount یک رشته اعشاری مثبت با حداکثر دو رقم اعشار است. پاسخ‌ها مبالغ را با cents بازمی‌گردانند.

| روش | مسیر | ورودی / کاربرد |
|---|---|---|
| GET | `/health` | نسخه، role و DEMO_ONLY |
| POST | `/api/auth/register` | email, password؛ role ارسالی نادیده گرفته می‌شود |
| POST | `/api/auth/login` | email, password؛ token هشت‌ساعته |
| POST | `/api/auth/logout` | لغو Session جاری |
| GET | `/api/me` | کاربر جاری |
| GET | `/api/wallet` | موجودی، درخواست‌ها و ۲۰۰ entry آخر |
| POST | `/api/wallet/requests` | amount |
| GET | `/api/admin/funding` | ادمین؛ ۵۰۰ درخواست آخر |
| POST | `/api/admin/funding/{id}` | ادمین؛ status: approved/rejected |
| GET | `/api/admin/audit` | ادمین؛ ۵۰۰ رویداد آخر |
| POST | `/api/admin/scenario` | ادمین؛ scenario: up/down/reset |
| GET | `/api/accounts` | حساب‌های متعلق به کاربر، positionها و equity |
| GET | `/api/broker/quotes` | قیمت مصنوعی، scale و نوع شبیه‌ساز |
| POST | `/api/broker/accounts` | بدنه خالی؛ ساخت حساب |
| POST | `/api/broker/accounts/{id}/transfers` | amount, direction: deposit/withdraw |
| POST | `/api/broker/accounts/{id}/positions` | symbol: EURUSD/GBPUSD/USDJPY, side: buy/sell, quantity: integer 1..100000 |
| POST | `/api/broker/positions/{id}/close` | بدنه خالی؛ بستن position متعلق به کاربر |
| GET | `/api/prop/plans` | پلن‌ها و قواعد |
| POST | `/api/prop/purchases` | plan_id: starter/advanced |
| POST | `/api/prop/accounts/{id}/evaluate` | بدنه خالی؛ ارزیابی |

خطاها: 400 ورودی نامعتبر، 401 Session نامعتبر، 403 نقش غیرمجاز، 404 مسیر یا حساب ناموجود/متعلق به دیگری، 409 کمبود اعتبار یا conflict، 413 body بزرگ، 415 Content-Type نامعتبر، 429 محدودیت ورود، 503 سرویس دامنه قطع است.

CLI همه این مسیرها را پشتیبانی می‌کند. نمونه:

```bash
clear
python3 -m ako_fx.cli POST /api/broker/accounts --data '{}'
python3 -m ako_fx.cli POST /api/broker/accounts/ACCOUNT_ID/transfers --key RETRY_KEY_123 --data '{"amount":"500","direction":"deposit"}'
python3 -m ako_fx.cli POST /api/broker/accounts/ACCOUNT_ID/positions --data '{"symbol":"EURUSD","side":"buy","quantity":100}'
python3 -m ako_fx.cli POST /api/broker/positions/POSITION_ID/close --data '{}'
python3 -m ako_fx.cli POST /api/prop/purchases --data '{"plan_id":"starter"}'
```

برای تصمیم ادمین، ابتدا با ادمین login کنید و token ادمین را در AKO_TOKEN بگذارید:

```bash
clear
python3 -m ako_fx.cli GET /api/admin/funding
python3 -m ako_fx.cli POST /api/admin/funding/REQUEST_ID --data '{"status":"approved"}'
python3 -m ako_fx.cli POST /api/admin/scenario --data '{"scenario":"up"}'
```

Web برای هر کلیک key جدید ایجاد می‌کند و هنگام ارسال دکمه‌ها را غیرفعال می‌کند. در قطع ارتباط نتیجه ممکن است نامعلوم باشد؛ پیش از تکرار موجودی/حساب را refresh کنید. CLI برای retry دقیق‌تر کلید را روی stderr نمایش می‌دهد. endpointها pagination کامل یا export نامحدود ندارند؛ محدودیت پاسخ در جدول مشخص است.
