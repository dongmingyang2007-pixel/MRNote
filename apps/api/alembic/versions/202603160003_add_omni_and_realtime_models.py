"""Add Qwen3-Omni and realtime model variants to catalog

Revision ID: 202603160003
Revises: 202603160002
"""

from alembic import op

revision = "202603160003"
down_revision = "202603160002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        -- Add Qwen3-Omni-Flash-Realtime (全模态)
        INSERT INTO model_catalog (
            id, model_id, display_name, provider, category, description, capabilities,
            context_window, max_output, input_price, output_price, is_active, sort_order,
            created_at, updated_at
        ) VALUES
        ('00000000-0000-0000-0000-000000000012', 'qwen3-omni-flash-realtime', 'Qwen3-Omni-Flash-Realtime', 'qwen', 'llm', '端到端全模态实时模型：直接接收音频/图片/视频输入，直接输出语音+文字。119种语言文本、20种语言语音。一个模型替代 ASR+LLM+TTS+Vision 整条管线。', '["text","vision","audio_input","audio_output","realtime","multilingual"]', 131072, 8192, 0.0022, 0.0083, true, 5, now(), now())
        ON CONFLICT (model_id) DO NOTHING;

        -- Add realtime ASR model
        INSERT INTO model_catalog (
            id, model_id, display_name, provider, category, description, capabilities,
            context_window, max_output, input_price, output_price, is_active, sort_order,
            created_at, updated_at
        ) VALUES
        ('00000000-0000-0000-0000-000000000013', 'qwen3-asr-flash-realtime', 'Qwen3-ASR-Flash-Realtime', 'qwen', 'asr', '实时流式语音识别，边说边转，延迟极低', '["chinese","english","realtime","streaming"]', 0, 0, 0, 0, true, 5, now(), now())
        ON CONFLICT (model_id) DO NOTHING;

        -- Add Qwen3-ASR-Flash (non-realtime, already tested working)
        INSERT INTO model_catalog (
            id, model_id, display_name, provider, category, description, capabilities,
            context_window, max_output, input_price, output_price, is_active, sort_order,
            created_at, updated_at
        ) VALUES
        ('00000000-0000-0000-0000-000000000014', 'qwen3-asr-flash', 'Qwen3-ASR-Flash', 'qwen', 'asr', '高精度语音识别，支持5分钟内音频同步识别，Base64直传', '["chinese","english","sync","base64"]', 0, 0, 0, 0, true, 15, now(), now())
        ON CONFLICT (model_id) DO NOTHING;

        -- Add realtime TTS models
        INSERT INTO model_catalog (
            id, model_id, display_name, provider, category, description, capabilities,
            context_window, max_output, input_price, output_price, is_active, sort_order,
            created_at, updated_at
        ) VALUES
        ('00000000-0000-0000-0000-000000000015', 'qwen3-tts-flash-realtime', 'Qwen3-TTS-Flash-Realtime', 'qwen', 'tts', '实时流式语音合成，17种拟人音色，极低延迟', '["chinese","english","realtime","streaming","multi_voice"]', 0, 0, 0, 0.01, true, 5, now(), now())
        ON CONFLICT (model_id) DO NOTHING;

        -- Add Qwen3-TTS-Flash (non-realtime, already tested working)
        INSERT INTO model_catalog (
            id, model_id, display_name, provider, category, description, capabilities,
            context_window, max_output, input_price, output_price, is_active, sort_order,
            created_at, updated_at
        ) VALUES
        ('00000000-0000-0000-0000-000000000016', 'qwen3-tts-flash', 'Qwen3-TTS-Flash', 'qwen', 'tts', '高质量语音合成，17种拟人音色，支持指令控制语气', '["chinese","english","multi_voice","instruct"]', 0, 0, 0, 0.01, true, 15, now(), now())
        ON CONFLICT (model_id) DO NOTHING;

        -- Add CosyVoice v3.5 Plus
        INSERT INTO model_catalog (
            id, model_id, display_name, provider, category, description, capabilities,
            context_window, max_output, input_price, output_price, is_active, sort_order,
            created_at, updated_at
        ) VALUES
        ('00000000-0000-0000-0000-000000000017', 'cosyvoice-v3.5-plus', 'CosyVoice v3.5 Plus', 'qwen', 'tts', '新一代生成式语音大模型，文本理解和语音生成深度融合', '["chinese","english","natural","emotion"]', 0, 0, 0, 0.01, true, 25, now(), now())
        ON CONFLICT (model_id) DO NOTHING;

        -- Add Qwen-声音复刻 (voice cloning)
        INSERT INTO model_catalog (
            id, model_id, display_name, provider, category, description, capabilities,
            context_window, max_output, input_price, output_price, is_active, sort_order,
            created_at, updated_at
        ) VALUES
        ('00000000-0000-0000-0000-000000000018', 'qwen-voice-enrollment', 'Qwen 声音复刻', 'qwen', 'tts', '录制5秒声音即可克隆用户音色，让AI用你的声音说话', '["voice_clone","custom_voice"]', 0, 0, 0, 0, true, 30, now(), now())
        ON CONFLICT (model_id) DO NOTHING;

        -- Add Fun-ASR Realtime
        INSERT INTO model_catalog (
            id, model_id, display_name, provider, category, description, capabilities,
            context_window, max_output, input_price, output_price, is_active, sort_order,
            created_at, updated_at
        ) VALUES
        ('00000000-0000-0000-0000-000000000019', 'fun-asr-realtime', 'Fun-ASR 实时语音识别', 'qwen', 'asr', '通义实验室新一代端到端语音识别，实时流式，上下文感知', '["chinese","english","realtime","streaming"]', 0, 0, 0, 0, true, 25, now(), now())
        ON CONFLICT (model_id) DO NOTHING;

        -- Add Qwen-Audio-Turbo
        INSERT INTO model_catalog (
            id, model_id, display_name, provider, category, description, capabilities,
            context_window, max_output, input_price, output_price, is_active, sort_order,
            created_at, updated_at
        ) VALUES
        ('00000000-0000-0000-0000-000000000020', 'qwen-audio-turbo', 'Qwen-Audio-Turbo', 'qwen', 'asr', '短视频级音频语言理解，支持语音、自然声音、音乐识别', '["chinese","english","audio_understanding","music"]', 0, 0, 0, 0, true, 30, now(), now())
        ON CONFLICT (model_id) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM model_catalog WHERE id IN (
            '00000000-0000-0000-0000-000000000012',
            '00000000-0000-0000-0000-000000000013',
            '00000000-0000-0000-0000-000000000014',
            '00000000-0000-0000-0000-000000000015',
            '00000000-0000-0000-0000-000000000016',
            '00000000-0000-0000-0000-000000000017',
            '00000000-0000-0000-0000-000000000018',
            '00000000-0000-0000-0000-000000000019',
            '00000000-0000-0000-0000-000000000020'
        );
    """)
