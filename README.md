# owui-garmin

Open WebUI tool + coach model for Garmin Connect.

## Setup

1. **Tool:** Workspace → Tools → New → paste [`garmin.py`](garmin.py) → Save. Set ID to `garmin-connect`.
2. **Credentials:** open the tool **Valves** (gear) and set your Garmin Connect **email** and **password**. Without these, login will fail.
3. **Model:** Workspace → Models → Import [`models/jack-d.json`](models/jack-d.json) (JSON array).

First chat: ask to log in; if MFA is required, paste the code in chat (not in Valves) and the model calls `submit_mfa`.

Change `base_model_id` in the model JSON if you are not using `minimaxi/minimax-m3`.

## License

MIT
