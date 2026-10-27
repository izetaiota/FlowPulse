<script setup lang="ts">
import ModulePlaceholder from "@/components/ModulePlaceholder.vue";
</script>

<template>
  <ModulePlaceholder
    title="内容数据监控"
    description="单篇内容的阅读、点赞、收藏、评论、转发数据，账号总览与今日 / 昨日 / 7 日趋势，支持按账号、时间范围、赛道标签筛选，报表一键导出。"
    :features="[
      '单篇内容数据：阅读 / 点赞 / 收藏 / 评论 / 转发',
      '账号汇总看板与今日 / 昨日 / 7 日趋势',
      '折线图、柱状图可视化',
      '数据筛选：账号、时间范围、赛道标签',
      '报表导出 CSV / Excel',
    ]"
  />
</template>
