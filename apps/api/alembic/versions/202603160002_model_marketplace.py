"""model_catalog and pipeline_configs tables with seed data

Revision ID: 202603160002
Revises: 202603160001
Create Date: 2026-03-16
"""

from alembic import op

revision = "202603160002"
down_revision = "202603160001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table if not exists model_catalog (
          id varchar(36) primary key,
          model_id varchar(100) not null unique,
          display_name varchar(255) not null,
          provider varchar(100) not null,
          category varchar(20) not null,
          description text not null default '',
          capabilities jsonb not null default '[]'::jsonb,
          context_window integer not null default 0,
          max_output integer not null default 0,
          input_price double precision not null default 0,
          output_price double precision not null default 0,
          is_active boolean not null default true,
          sort_order integer not null default 0,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        );

        create index if not exists idx_model_catalog_category on model_catalog(category);
        create index if not exists idx_model_catalog_provider on model_catalog(provider);

        alter table model_catalog alter column created_at set default now();
        alter table model_catalog alter column updated_at set default now();

        create table if not exists pipeline_configs (
          id varchar(36) primary key,
          project_id uuid not null references projects(id) on delete cascade,
          model_type varchar(20) not null,
          model_id varchar(100) not null,
          config_json jsonb not null default '{}'::jsonb,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          unique (project_id, model_type)
        );

        create index if not exists idx_pipeline_configs_project on pipeline_configs(project_id);

        alter table pipeline_configs alter column created_at set default now();
        alter table pipeline_configs alter column updated_at set default now();

        -- Seed data: LLM models
        insert into model_catalog (
          id,
          model_id,
          display_name,
          provider,
          category,
          description,
          capabilities,
          context_window,
          max_output,
          input_price,
          output_price,
          is_active,
          sort_order,
          created_at,
          updated_at
        ) values
        (
          '00000000-0000-0000-0000-000000000001',
          'qwen3.5-flash',
          'Qwen3.5 Flash',
          'alibaba',
          'llm',
          '通义千问3.5 Flash，超快速推理，适合日常对话与简单任务',
          '["chat", "function_calling", "streaming"]'::jsonb,
          131072, 8192, 0.3, 0.6, true, 10, now(), now()
        ),
        (
          '00000000-0000-0000-0000-000000000002',
          'qwen3.5-plus',
          'Qwen3.5 Plus',
          'alibaba',
          'llm',
          '通义千问3.5 Plus，均衡的智能与速度，适合复杂对话与内容生成',
          '["chat", "function_calling", "streaming", "reasoning"]'::jsonb,
          131072, 8192, 2.0, 6.0, true, 20, now(), now()
        ),
        (
          '00000000-0000-0000-0000-000000000003',
          'qwen3-max',
          'Qwen3 Max',
          'alibaba',
          'llm',
          '通义千问3 Max，旗舰级推理能力，适合高难度分析与创作任务',
          '["chat", "function_calling", "streaming", "reasoning", "long_context"]'::jsonb,
          131072, 8192, 6.0, 24.0, true, 30, now(), now()
        ),
        (
          '00000000-0000-0000-0000-000000000004',
          'deepseek-v3.2',
          'DeepSeek V3.2',
          'deepseek',
          'llm',
          'DeepSeek V3.2，强大的开源大模型，性价比极高，适合多种场景',
          '["chat", "function_calling", "streaming", "reasoning"]'::jsonb,
          65536, 8192, 1.0, 2.0, true, 40, now(), now()
        ),
        (
          '00000000-0000-0000-0000-000000000005',
          'deepseek-r1',
          'DeepSeek R1',
          'deepseek',
          'llm',
          'DeepSeek R1，专注深度推理，适合数学、编程与逻辑分析任务',
          '["chat", "streaming", "reasoning", "chain_of_thought"]'::jsonb,
          65536, 8192, 4.0, 16.0, true, 50, now(), now()
        ),

        -- Seed data: ASR models
        (
          '00000000-0000-0000-0000-000000000006',
          'paraformer-v2',
          'Paraformer V2',
          'alibaba',
          'asr',
          '高精度语音识别模型，支持中英文混合识别，适合实时转写场景',
          '["realtime", "chinese", "english", "punctuation"]'::jsonb,
          0, 0, 0.0, 0.0, true, 10, now(), now()
        ),
        (
          '00000000-0000-0000-0000-000000000007',
          'sensevoice-v1',
          'SenseVoice V1',
          'alibaba',
          'asr',
          '多语种语音理解模型，支持情感识别与语种检测',
          '["multilingual", "emotion", "language_detection", "punctuation"]'::jsonb,
          0, 0, 0.0, 0.0, true, 20, now(), now()
        ),

        -- Seed data: TTS models
        (
          '00000000-0000-0000-0000-000000000008',
          'cosyvoice-v1',
          'CosyVoice V1',
          'alibaba',
          'tts',
          '自然流畅的语音合成模型，支持多种音色和情感表达',
          '["chinese", "english", "multi_speaker", "emotion"]'::jsonb,
          0, 0, 0.0, 0.0, true, 10, now(), now()
        ),
        (
          '00000000-0000-0000-0000-000000000009',
          'sambert-v1',
          'Sambert V1',
          'alibaba',
          'tts',
          '高品质语音合成模型，发音清晰自然，适合客服与播报场景',
          '["chinese", "high_quality", "multi_speaker"]'::jsonb,
          0, 0, 0.0, 0.0, true, 20, now(), now()
        ),

        -- Seed data: Vision models
        (
          '00000000-0000-0000-0000-000000000010',
          'qwen-vl-plus',
          'Qwen VL Plus',
          'alibaba',
          'vision',
          '通义千问视觉理解模型 Plus，支持图片理解、OCR与视觉问答',
          '["vision", "ocr", "image_understanding", "visual_qa"]'::jsonb,
          8192, 2048, 2.0, 6.0, true, 10, now(), now()
        ),
        (
          '00000000-0000-0000-0000-000000000011',
          'qwen-vl-max',
          'Qwen VL Max',
          'alibaba',
          'vision',
          '通义千问视觉理解旗舰模型，最强图像与文档分析能力',
          '["vision", "ocr", "image_understanding", "visual_qa", "document_analysis"]'::jsonb,
          8192, 2048, 6.0, 24.0, true, 20, now(), now()
        )
        on conflict (model_id) do nothing;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop table if exists pipeline_configs;
        drop table if exists model_catalog;
        """
    )
