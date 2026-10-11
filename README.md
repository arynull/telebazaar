# telebazaar

Self-hosted shop for Telegram: product catalog, carts, orders, and Telegram
Stars payments — one CLI + bot, one SQLite store, zero third-party services.

`telebazaar` is the foundation of a full business suite (roadmap: CRM
pipeline, broadcast campaigns, payments depth, analytics, multi-shop). v0.1.0
ships the Storefront: manage products from the CLI, sell through a Telegram
bot, accept Stars invoices, track orders through a strict status machine.

## Install

Requires Python 3.12+. No runtime dependencies — stdlib only.

```sh
pip install .
telebazaar --version   # telebazaar 0.1.0
```

## Quickstart

```sh
export TELEBAZAAR_DATA_DIR=~/.telebazaar   # default if unset
telebazaar init        # create data dir, database, sample config.toml
telebazaar doctor      # sanity check: dirs, schema, token, merchants

# stock the shop
telebazaar catalog add --sku WIDGET-1 --name "Test Widget" --price 1500 --currency XTR --stock 10
telebazaar catalog list
telebazaar catalog show WIDGET-1

# an order's full lifecycle
telebazaar orders create --customer 123456 --sku WIDGET-1 --qty 2
telebazaar orders show <id>
telebazaar orders pay <id>
telebazaar orders ship <id>
```

## Bot setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Set it (env wins over the config file):

```sh
export TELEBAZAAR_BOT_TOKEN=<your-bot-token>
export TELEBAZAAR_MERCHANT_IDS=123456,789012   # your Telegram user ids
```

or put `bot_token` / `merchant_ids` in `$TELEBAZAAR_DATA_DIR/config.toml`
(`telebazaar init` writes a sample).

3. Run the bot (long-polling, no webhook needed):

```sh
telebazaar bot run
```

## Bot commands

Customers:

- `/start` — welcome
- `/shop` — browse products, tap ➕ to add to cart
- `/cart` — view cart, checkout or clear
- `/myorders` — your recent orders

Merchants (ids in `TELEBAZAAR_MERCHANT_IDS`):

- `/orders` — open orders (pending payment / paid)
- `/order <id>` — order detail with Ship / Cancel buttons
- `/broadcast <segment> <text>` — send a message to every member of a segment

Checkout sends a Telegram invoice (Stars: currency `XTR`, empty provider
token, one price item). The bot answers the pre-checkout query only when the
order exists, is still `pending_payment`, and the amount matches; on
`successful_payment` the order flips to `paid` and the charge id is stored.

## CLI reference

```
telebazaar --version
telebazaar init
telebazaar doctor
telebazaar catalog add --sku SKU --name NAME --price MINOR_UNITS
    [--currency XTR] [--stock N] [--description TEXT] [--tags TAGS] [--photo FILE_ID_OR_URL]
telebazaar catalog list [--all]
telebazaar catalog show SKU                      # JSON
telebazaar catalog set-stock SKU N
telebazaar catalog deactivate SKU
telebazaar orders create --customer TG_ID --sku SKU --qty N [--sku SKU --qty N ...]
telebazaar orders show ID                        # JSON
telebazaar orders list [--status STATUS]
telebazaar orders pay ID
telebazaar orders ship ID
telebazaar orders cancel ID
telebazaar broadcast --segment NAME --text TEXT (--dry | --yes)
telebazaar bot run
```

Money is integer minor units everywhere (Stars for `XTR`). Order statuses:
`pending_payment → paid → shipped`, with `cancelled` allowed from
`pending_payment` or `paid`; anything else is rejected. Stock is reserved when
the order is created. Every mutation is appended to an audit `events` table.

## Data & config

- Data dir: `TELEBAZAAR_DATA_DIR` (default `~/.telebazaar/`), holds
  `telebazaar.db` (SQLite) and `config.toml`.
- Env: `TELEBAZAAR_BOT_TOKEN`, `TELEBAZAAR_MERCHANT_IDS` (comma-separated),
  `TELEBAZAAR_DATA_DIR`.
- `telebazaar bot run` refuses to start without a token (exit 2).

## License

MIT — see LICENSE.
