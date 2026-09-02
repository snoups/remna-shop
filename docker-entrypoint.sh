#!/bin/sh
set -e

ASSETS_CONTAINER_PATH="/opt/remnashop/assets"
ASSETS_DEFAULT_PATH="/opt/remnashop/assets.default"

UVICORN_RELOAD_ARGS=""

echo "Starting asset initialization"

# --- First run: copy default banners if user banners dir is empty ---
USER_BANNERS="${ASSETS_CONTAINER_PATH}/banners"
if [ ! -d "$USER_BANNERS" ] || [ -z "$(ls -A "$USER_BANNERS" 2>/dev/null)" ]; then
    echo "No user banners found — copying defaults"
    cp -a "${ASSETS_DEFAULT_PATH}/banners/." "$USER_BANNERS/"
fi

# --- Migrate legacy layout: move pre-0.8 *.ftl (except custom.ftl) into .legacy/ ---
# Built-in translations now ship in assets.default; the user volume keeps only custom.ftl.
# Skipped when assets.default is absent (local dev bind-mounts src into assets directly).
USER_TRANSLATIONS="${ASSETS_CONTAINER_PATH}/translations"
if [ -d "$ASSETS_DEFAULT_PATH" ] && [ -d "$USER_TRANSLATIONS" ]; then
    for locale_dir in "$USER_TRANSLATIONS"/*/; do
        [ -d "$locale_dir" ] || continue
        for ftl in "$locale_dir"*.ftl; do
            [ -f "$ftl" ] || continue
            case "$(basename "$ftl")" in
                custom.ftl) continue ;;
            esac
            mkdir -p "${locale_dir}.legacy"
            mv "$ftl" "${locale_dir}.legacy/"
            echo "Moved legacy translation $(basename "$ftl") -> ${locale_dir}.legacy/"
        done
    done
fi

# --- Bootstrap custom.ftl for each locale in assets.default ---
if [ -d "${ASSETS_DEFAULT_PATH}/translations" ]; then
    for locale_dir in "${ASSETS_DEFAULT_PATH}/translations"/*/; do
        locale=$(basename "$locale_dir")
        USER_LOCALE_DIR="${ASSETS_CONTAINER_PATH}/translations/${locale}"
        CUSTOM_FTL="${USER_LOCALE_DIR}/custom.ftl"
        TEMPLATE_FTL="${ASSETS_DEFAULT_PATH}/translations/${locale}/custom.ftl"
        mkdir -p "$USER_LOCALE_DIR"
        if [ ! -f "$CUSTOM_FTL" ]; then
            # Copy the template custom.ftl from defaults (contains usage comments, no overrides)
            if [ -f "$TEMPLATE_FTL" ]; then
                cp "$TEMPLATE_FTL" "$CUSTOM_FTL"
                echo "Created custom.ftl for locale: ${locale}"
            else
                touch "$CUSTOM_FTL"
                echo "Created empty custom.ftl for locale: ${locale}"
            fi
        elif [ -f "$TEMPLATE_FTL" ]; then
            # User's custom.ftl is left untouched; refresh the reference template for diffing
            cp "$TEMPLATE_FTL" "${CUSTOM_FTL}.example"
        fi
    done
fi

echo "Asset initialization complete"


if [ "$UVICORN_RELOAD_ENABLED" = "true" ]; then
    echo "Uvicorn will run with reload enabled"
    UVICORN_RELOAD_ARGS="--reload --reload-dir /opt/remnashop/src --reload-dir /opt/remnashop/assets --reload-include *.ftl"
else
    echo "Uvicorn will run without reload"
fi

exec uvicorn src.__main__:application --host "${APP_HOST:-0.0.0.0}" --port "${APP_PORT:-5000}" --factory --use-colors ${UVICORN_RELOAD_ARGS}
