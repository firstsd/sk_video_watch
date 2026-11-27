"""Read the playback settings shared by all deployments."""

import os


def read_seconds(name, default, minimum=1):
    message = f"{name} must be a whole number of seconds (at least {minimum})"
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise ValueError(message) from exc
    if value < minimum:
        raise ValueError(message)
    return value


def playback_settings_from_environment():
    target = read_seconds("MATCHDAY_LIVE_TARGET_SECONDS", 150)
    maximum = read_seconds("MATCHDAY_LIVE_MAX_SECONDS", 180)
    if maximum <= target:
        raise ValueError(
            "MATCHDAY_LIVE_MAX_SECONDS must be greater than MATCHDAY_LIVE_TARGET_SECONDS"
        )
    return {
        "live_target_seconds": target,
        "live_max_seconds": maximum,
        "forward_buffer_seconds": read_seconds("MATCHDAY_FORWARD_BUFFER_SECONDS", 180),
        "back_buffer_seconds": read_seconds("MATCHDAY_BACK_BUFFER_SECONDS", 30, minimum=0),
    }
