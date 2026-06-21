---
name: douyin-transcribe
description: Resolve and transcribe a Douyin video through the local Douyin Transcribe API.
---

# Douyin Transcribe

Use this skill when the user provides a Douyin link or share text and asks for transcription,
subtitles, or learning notes.

## Workflow

1. Submit the input to `POST /api/v1/tasks/transcribe`.
2. Poll `GET /api/v1/tasks/{task_id}` until `completed` or `failed`.
3. On completion, fetch `notes.md` or the requested artifact.
4. Report failures using the task's `error` field.

Default to transcription only. Do not request comments, user posts, live-room data, or cookies
unless the user explicitly asks for deep collection.
