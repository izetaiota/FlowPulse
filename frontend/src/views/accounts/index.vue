<script setup lang="ts">
import ModulePlaceholder from "@/components/ModulePlaceholder.vue";
</script>

<template>
  <ModulePlaceholder
    title="账号管理 · 渠道接入"
    description="绑定公众号、抖音、小红书、视频号四平台账号，按赛道分组管理，持续监控授权状态，异常自动告警。优先使用平台官方 OAuth 开放接口，接口能力不足时提供浏览器自动化兜底方案（明确标注风控风险）。"
    :features="[
      '多平台账号绑定：公众号 / 抖音 / 小红书 / 视频号',
      '账号分组管理（赛道分组，如知识分享、好物种草）',
      '授权状态监控与过期告警',
      'OAuth 官方接口优先，浏览器自动化兜底',
      '凭证加密存储，定时检测有效期',
    ]"
  />
</template>
