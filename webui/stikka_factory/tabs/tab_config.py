from reactpy import component, html


@component
def ConfigTab(
    config_password_input,
    on_password_change,
    on_unlock,
    on_reload_file,
    on_save,
    on_reload_printers,
    config_text,
    on_config_text_change,
    config_unlocked,
):
    lock_state = "Unlocked" if config_unlocked else "Locked"

    return html.div(
        {"class_name": "config-shell"},
        html.div(
            {"class_name": "config-head"},
            html.div(
                {"class_name": "config-title-wrap"},
                html.p({"class_name": "card-title"}, "Printer Config"),
                html.p(
                    {"class_name": "setting-note"},
                    "Edit printers_config.json, save, and reload printers without restarting.",
                ),
            ),
            html.div(
                {"class_name": "config-lock-pill"},
                f"State: {lock_state}",
            ),
        ),
        html.div(
            {"class_name": "config-grid"},
            html.div(
                {"class_name": "settings-card"},
                html.label(
                    {"class_name": "form-field"},
                    html.span({"class_name": "field-label"}, "Config password"),
                    html.input(
                        {
                            "type": "password",
                            "value": config_password_input,
                            "placeholder": "Enter config password",
                            "onChange": on_password_change,
                            "class_name": "input-control",
                        }
                    ),
                ),
                html.div(
                    {"class_name": "config-actions"},
                    html.button(
                        {
                            "onClick": on_unlock,
                            "class_name": "btn scan-btn",
                        },
                        "Unlock",
                    ),
                    html.button(
                        {
                            "onClick": on_reload_file,
                            "class_name": "btn scan-btn",
                        },
                        "Reload file",
                    ),
                    html.button(
                        {
                            "onClick": on_save,
                            "disabled": not config_unlocked,
                            "class_name": "btn print-btn",
                        },
                        "Save config",
                    ),
                    html.button(
                        {
                            "onClick": on_reload_printers,
                            "class_name": "btn scan-btn",
                        },
                        "Reload printers",
                    ),
                ),
                html.p(
                    {"class_name": "setting-note"},
                    "Tip: Save validates JSON first and reloads printer registry automatically.",
                ),
            ),
            html.div(
                {"class_name": "preview-card config-editor-card"},
                html.label(
                    {"class_name": "form-field"},
                    html.span({"class_name": "field-label"}, "printers_config.json"),
                    html.textarea(
                        {
                            "value": config_text,
                            "onChange": on_config_text_change,
                            "class_name": "input-control textarea-control config-editor",
                            "rows": "22",
                            "disabled": not config_unlocked,
                        }
                    ),
                ),
            ),
        ),
    )
