<script setup lang="ts">
import ModulePlaceholder from "@/components/ModulePlaceholder.vue";
</script>

<template>
  <ModulePlaceholder
    title="内容编辑 · 批量分发"
    description="统一编辑器，一份原稿多平台分发：自动适配公众号图文、小红书笔记、抖音短视频、视频号格式规范，支持定时发布与任务队列管理。"
    :features="[
      '统一编辑器，一份原稿多平台分发',
      '公众号：图文排版、头图、摘要',
      '小红书：图文笔记、标签自动处理',
      '抖音 / 视频号：短视频 + 标题 + 话题',
      '定时发布与批量分发（多选渠道）',
      '发布任务队列与发布日志',
      '失败原因展示：平台驳回 / 风控 / 授权失效，支持重试',
    ]"
  />
</template>
