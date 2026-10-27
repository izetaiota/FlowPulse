<script setup lang="ts">
import ModulePlaceholder from "@/components/ModulePlaceholder.vue";
</script>

<template>
  <ModulePlaceholder
    title="统一消息看板 · 核心差异化"
    description="聚合四个平台的私信、评论、@提醒到同一页面，集中查看、筛选并直接回复，不用再来回切换后台。支持消息标签、关键词预警与历史存档检索，轻松维护粉丝互动。"
    :features="[
      '聚合抖音 / 小红书 / 公众号 / 视频号的私信、评论、@提醒',
      '按渠道、账号、未读 / 已读筛选',
      '看板内直接回复评论与私信',
      '消息标签：意向咨询 / 好评 / 疑问 / 负面反馈',
      '关键词自动告警',
      '消息历史存档与全文检索',
    ]"
  />
</template>
