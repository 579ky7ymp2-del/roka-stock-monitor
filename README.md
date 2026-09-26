# ROKA Stock Monitor

Monitors the ROKA Men's Maverick X-3 Wetsuit Open Box and watches specifically for size **L**.

- Checks approximately every 5 minutes with GitHub Actions.
- Detects size L from the ROKA Shopify product feed.
- Sends one Discord notification when L changes from unavailable to available.
- Persists the previous state so it does not spam.
- Does not purchase automatically.

## Required secret

Create a repository secret named `DISCORD_WEBHOOK_URL`.

Never commit the webhook URL to the repository.

## Timing

GitHub scheduled workflows run approximately every 5 minutes, but scheduled jobs can occasionally be delayed. This is near-real-time monitoring, not a guaranteed instant alert.
