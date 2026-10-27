<script setup lang="ts">
import ModulePlaceholder from "@/components/ModulePlaceholder.vue";
</script>

<template>
  <ModulePlaceholder
    title="发布任务"
    description="查看多渠道发布任务的执行状态：待发布、发布中、成功、失败，含定时任务与重试记录，快速定位失败原因。"
    :features="[
      '发布任务队列与执行状态',
      '定时发布任务管理',
      '发布日志与错误信息记录',
      '失败自动重试',
      '失败原因分类：平台驳回 / 风控 / 授权失效',
    ]"
  />
</template>
