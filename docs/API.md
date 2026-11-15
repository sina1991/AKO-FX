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
| POST | `/api/broker/accounts/{id}/positions` | symbol از quotes؛ side: buy/sell؛ quantity: integer؛ سقف Broker برابر 100000 و Prop جدید 1000000000 |
| POST | `/api/broker/positions/{id}/close` | بدنه خالی؛ بستن position متعلق به کاربر |
| GET | `/api/prop/plans` | پلن‌ها و قواعد |
| POST | `/api/prop/purchases` | plan_id: a-1000 تا a-50000 / b-1000 تا b-200000 |
| POST | `/api/prop/accounts/{id}/evaluate` | بدنه خالی؛ ارزیابی |

خطاها: 400 ورودی نامعتبر، 401 Session نامعتبر، 403 نقش غیرمجاز، 404 مسیر یا حساب ناموجود/متعلق به دیگری، 409 کمبود اعتبار یا conflict، 413 body بزرگ، 415 Content-Type نامعتبر، 429 محدودیت ورود، 503 سرویس دامنه قطع است.

CLI همه این مسیرها را پشتیبانی می‌کند. نمونه:

```bash
clear
python3 -m ako_fx.cli POST /api/broker/accounts --data '{}'
python3 -m ako_fx.cli POST /api/broker/accounts/ACCOUNT_ID/transfers --key RETRY_KEY_123 --data '{"amount":"500","direction":"deposit"}'
python3 -m ako_fx.cli POST /api/broker/accounts/ACCOUNT_ID/positions --data '{"symbol":"EURUSD","side":"buy","quantity":100}'
python3 -m ako_fx.cli POST /api/broker/positions/POSITION_ID/close --data '{}'
python3 -m ako_fx.cli POST /api/prop/purchases --data '{"plan_id":"b-10000"}'
```

برای تصمیم ادمین، ابتدا با ادمین login کنید و token ادمین را در AKO_TOKEN بگذارید:

```bash
clear
python3 -m ako_fx.cli GET /api/admin/funding
python3 -m ako_fx.cli POST /api/admin/funding/REQUEST_ID --data '{"status":"approved"}'
python3 -m ako_fx.cli POST /api/admin/scenario --data '{"scenario":"up"}'
```

Web برای هر کلیک key جدید ایجاد می‌کند و هنگام ارسال دکمه‌ها را غیرفعال می‌کند. در قطع ارتباط نتیجه ممکن است نامعلوم باشد؛ پیش از تکرار موجودی/حساب را refresh کنید. CLI برای retry دقیق‌تر کلید را روی stderr نمایش می‌دهد. endpointها pagination کامل یا export نامحدود ندارند؛ محدودیت پاسخ در جدول مشخص است.

## Prop A/B در نسخه 0.2

`GET /api/prop/plans` چهارده پلن versioned را می‌دهد؛ plan_id مانند `a-1000` یا `b-10000` است. `GET /api/prop/rules` منابع، تعارض‌ها و نام checkهای انسانی را بازمی‌گرداند. هر حساب Prop جدید در `/api/accounts` دارای فیلد `prop` با stage، روزها، deadline، کف‌ها، flags و درخواست‌ها است. stage=3 یعنی funded-demo، نه معامله واقعی.

| روش | مسیر | ورودی |
|---|---|---|
| POST | `/api/prop/accounts/{id}/requests` | kind: transition / payout / refund20 / reset / extend / growth / merge؛ برای merge: other_account_id |
| GET | `/api/admin/prop/requests` | درخواست‌ها، flags و چک‌لیست |
| GET | `/api/admin/prop/accounts` | حساب‌های کاربران برای بررسی ادمین |
| POST | `/api/admin/prop/requests/{id}` | decision: approve / reject / reset / fail؛ reason و checks؛ در صورت نیاز slippage_exempt و source_conflict_ack |
| POST | `/api/admin/prop/accounts/{id}/flag` | reason؛ action: record / fail / fail_owner |
| POST | `/api/admin/prop/settings` | broker_timezone؛ فقط قراردادهای آینده |
| POST | `/api/broker/positions/{id}/protection` | stop_loss / take_profit به قیمت اعشاری یا null برای حذف |

افتتاح position نیز stop_loss و take_profit اختیاری دارد. leverage نماد از `/api/broker/quotes` برمی‌گردد. quantity عدد صحیح واحد است؛ سقف فنی حساب جدید Prop یک میلیارد واحد است، نه محدودیت تجاری تعداد معاملات/lot.

برای approve/reset، checks زیر باید boolean true باشند: identity، ownership، no_external_copying، no_automated_trading، no_trading_vps، market_integrity. این‌ها گواه بررسی ادمین‌اند و جای الگوریتم تشخیص تقلب را نمی‌گیرند. reason باید ۸ تا ۱۰۰۰ کاراکتر باشد. flags نمی‌توانند با یک تأیید عادی دور زده شوند؛ ثبت exception اسلیپیج به شواهد SL نیاز دارد. حساب شکست‌خورده دوباره فعال نمی‌شود.

```bash
clear
python3 -m ako_fx.cli POST /api/prop/purchases --data '{"plan_id":"b-10000"}'
python3 -m ako_fx.cli POST /api/prop/accounts/ACCOUNT_ID/requests --data '{"kind":"transition"}'
python3 -m ako_fx.cli GET /api/admin/prop/requests
```
