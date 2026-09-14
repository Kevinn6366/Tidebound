# GWC-Pro 路由迁移清单

对应 [展示与通信迁移规格](web-migration.md)。此清单依据迁移前 `gwcpro/backend/main.py` 的路由声明生成。未接入项保留原业务代码，新服务不导入、不代理这些业务。以下为第一轮路由盘点；第二轮新增对话空接口和浏览器隔离的原设置适配，以 `webapp/chat.py`、`webapp/ui_routes.py` 及当前迁移规格为准。`/api/login-config` 只保留展示字段，不迁入原文件存储与写接口。

| 方法 | 原路径 | 原函数 | 当前状态 |
| --- | --- | --- | --- |
| `MIDDLEWARE` | `http` | `_auth_guard` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/bridge/pull` | `bridge_pull` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/bridge/push` | `bridge_push` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/bridge/history` | `get_bridge_history` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/bridge/history` | `post_bridge_history` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/v1/chat/completions` | `chat_completions` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/v1/models` | `proxy_models` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/tts_from_pet` | `tts_from_pet` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/tts_from_pet/poll` | `tts_from_pet_poll` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/pet_chat/message` | `pet_chat_message` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/pet_chat/message/poll` | `pet_chat_message_poll` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/models` | `scan_local_models` | 已迁移为只读展示接口 |
| `GET` | `/api/mmd_motions` | `scan_mmd_motions` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/mmd_models` | `scan_mmd_models` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/admin/api/fetch_models` | `dummy_fetch_models` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/skills/retrieve` | `retrieve_skills` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/skills/packs` | `get_skill_packs` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/admin/api/skills` | `get_skills` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/admin/api/skills/toggle` | `toggle_skill` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/admin/api/skills/toggle_pack` | `toggle_skill_pack` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/admin/api/file_content` | `get_file_content` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/admin/api/skills/import` | `import_skills` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/admin/api/skills/delete` | `delete_skill` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/admin/api/skills/approve` | `approve_skill` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/admin/api/skills/pending` | `get_pending_skills` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/kb/status` | `kb_status` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/kb/test-embedding` | `kb_test_embedding` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/kb/reindex` | `kb_reindex` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/kb/retrieve` | `kb_retrieve` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/qqbot/status` | `qqbot_status` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/qqbot/logs` | `qqbot_logs` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/qqbot/contexts` | `qqbot_contexts` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/qqbot/context/delete` | `qqbot_context_delete` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/qqbot/context/export` | `qqbot_context_export` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/qqbot/config` | `qqbot_get_config` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/qqbot/plugins` | `qqbot_plugins` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/qqbot/plugins/reload` | `qqbot_plugins_reload` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/qqbot/plugins/toggle` | `qqbot_plugin_toggle` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/qqbot/config` | `qqbot_save_config` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/qqbot/start` | `qqbot_start` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/qqbot/stop` | `qqbot_stop` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/qqbot/test` | `qqbot_test` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/qqbot/fetch_models` | `qqbot_fetch_models` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/server-data/export` | `export_server_data` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/server-data/import` | `import_server_data` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/local-mode` | `get_local_mode` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `PUT` | `/api/local-mode` | `set_local_mode` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/auth/setup_default` | `auth_setup_default` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/auth/login` | `auth_login` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/auth/change_password` | `auth_change_password` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/auth/users` | `auth_list_users` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/auth/users/list` | `auth_list_users_detailed` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/auth/register` | `auth_register_v2` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/auth/force_set_password` | `auth_force_set_password` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/auth/admin/reset_password` | `admin_reset_password` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/auth/admin/clear_password` | `admin_clear_password` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/auth/admin/delete_user` | `admin_delete_user` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/auth/delete_account` | `delete_own_account` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/login-bg` | `upload_login_bg` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/login-bg` | `serve_login_bg` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `DELETE` | `/api/login-bg` | `delete_login_bg` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/login-config` | `get_login_config` | 已迁移为只读展示接口 |
| `PUT` | `/api/login-config` | `save_login_config` | 已迁移为只读展示接口 |
| `GET` | `/api/launcher-config` | `get_launcher_config` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `PUT` | `/api/launcher-config` | `save_launcher_config` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/tts/install/sources` | `tts_install_sources` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/tts/install/voices` | `tts_install_voices` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/tts/install` | `tts_install` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/tts/install/progress` | `tts_install_progress` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/tts/status` | `tts_status` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/tts/start` | `tts_start` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/tts/stop` | `tts_stop` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/tts/voices` | `tts_voices` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/tts/set_voice` | `tts_set_voice` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/userdata/{mirror_id}/core/{key}` | `get_core_data` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/userdata/{mirror_id}/batch` | `batch_load_core` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `PUT` | `/api/userdata/{mirror_id}/core/{key}` | `put_core_data` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `DELETE` | `/api/userdata/{mirror_id}/core/{key}` | `delete_core_data` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/userdata/{mirror_id}/bgm` | `list_bgm` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/userdata/{mirror_id}/bgm` | `upload_bgm` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `DELETE` | `/api/userdata/{mirror_id}/bgm/{bgm_id}` | `delete_bgm` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/userdata/{mirror_id}/bgm/{bgm_id}/file` | `serve_bgm_file` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/userdata/{mirror_id}/bg_images` | `list_bg_images` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/userdata/{mirror_id}/bg_images` | `upload_bg_image` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `DELETE` | `/api/userdata/{mirror_id}/bg_images/{bg_id}` | `delete_bg_image` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/userdata/{mirror_id}/bg_images/{bg_id}/file` | `serve_bg_image_file` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/userdata/{mirror_id}/app_image/{key}` | `upload_app_image` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/userdata/{mirror_id}/app_image/{key}` | `serve_app_image` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `DELETE` | `/api/userdata/{mirror_id}/app_image/{key}` | `delete_app_image` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/userdata/{mirror_id}/models` | `list_models` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/userdata/{mirror_id}/models` | `upload_model` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/userdata/{mirror_id}/models/file` | `upload_model_file` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `PUT` | `/api/userdata/{mirror_id}/models` | `save_model_manifest` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/userdata/{mirror_id}/models/{model_id}` | `get_model` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `DELETE` | `/api/userdata/{mirror_id}/models/{model_id}` | `delete_model` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/models/all` | `list_all_models` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/models/search/{model_id}` | `search_model` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/userdata/{mirror_id}/models/{model_id}/files/{path:path}` | `serve_model_file` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/userdata/{mirror_id}/mods` | `list_mods` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `PUT` | `/api/userdata/{mirror_id}/mods/{mod_id}` | `save_mod` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `DELETE` | `/api/userdata/{mirror_id}/mods/{mod_id}` | `delete_mod` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/userdata/{mirror_id}/plugins/{plugin_name}` | `list_plugin_data` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/userdata/{mirror_id}/plugins/{plugin_name}/{key}` | `get_plugin_data` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `PUT` | `/api/userdata/{mirror_id}/plugins/{plugin_name}/{key}` | `put_plugin_data` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `DELETE` | `/api/userdata/{mirror_id}/plugins/{plugin_name}/{key}` | `delete_plugin_data` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/userdata/{mirror_id}/plugins/{plugin_name}/{key}/blob` | `upload_plugin_blob` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/userdata/{mirror_id}/plugins/{plugin_name}/{key}/blob` | `serve_plugin_blob` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/auto-backup` | `auto_backup` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/auto-backup/{mirror_id}` | `list_auto_backups` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/auto-backup/{mirror_id}/{filename}` | `load_auto_backup` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `DELETE` | `/api/auto-backup/{mirror_id}/{filename}` | `delete_auto_backup` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/userdata/{mirror_id}/migrate` | `migrate_data` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `DELETE` | `/api/userdata/{mirror_id}/all` | `reset_user_data` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `DELETE` | `/api/admin/reset-all` | `reset_all_data` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/userdata/{source_id}/clone_to/{target_id}` | `clone_user_data` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/admin` | `serve_admin_ui` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/opencode/status` | `opencode_status` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/opencode/install` | `opencode_install` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/opencode/run` | `opencode_run` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/opencode/stream/{task_id}` | `opencode_stream` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/opencode/poll/{task_id}` | `opencode_poll` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/opencode/confirm` | `opencode_confirm` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/opencode/tasks` | `opencode_tasks` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/opencode/configure` | `opencode_configure` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/opencode/models` | `opencode_list_models` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/ollama/status` | `ollama_status` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/ollama/install` | `ollama_install` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/ollama/install-progress` | `ollama_install_progress` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/ollama/pull` | `ollama_pull` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/ollama/pull-progress/{task_id}` | `ollama_pull_progress` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/ollama/models` | `ollama_list_models` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/llamacpp/status` | `llamacpp_status` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/llamacpp/install` | `llamacpp_install` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/llamacpp/models` | `llamacpp_models` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/llamacpp/import` | `llamacpp_import` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/llamacpp/import-zip` | `llamacpp_import_zip` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/asr/model-status` | `asr_model_status` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/voice-result` | `voice_result_post` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/voice-result` | `voice_result_get` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `POST` | `/api/asr/transcribe` | `asr_transcribe` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/screenshot/capture` | `screenshot_capture` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/api/web/search` | `web_search` | 未接入；新服务返回 501（旧业务）或 404（非 API 静态路径） |
| `GET` | `/app` | `redirect_frontend` | 已迁移为只读展示接口 |
| `GET` | `/app/{path:path}` | `serve_frontend_path` | 已迁移为只读展示接口 |

## 第二轮补齐

新增 `POST /api/chat/messages` → `backend/chat.py` 空实现，返回 501 `chat_not_connected`。`/api/userdata/preview/` 下的 core、batch、bgm、bg_images、models、mods、app_image、plugins 与当前预览清理入口已恢复，拒绝其他 mirror_id。`/api/login-config` 的读写与 `/api/login-bg` 的读取、上传、清除按当前浏览器隔离。未实现的原账号、旧自动备份、跨用户迁移及执行服务仍明确返回未接入；不以盘点表的第一轮状态覆盖本段补齐记录。
