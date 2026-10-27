<script setup lang="ts">
import ModulePlaceholder from "@/components/ModulePlaceholder.vue";
</script>

<template>
  <ModulePlaceholder
    title="选题库 / 灵感库"
    description="选题日历排期、灵感随手记录、竞品选题收藏，配合标签分类与状态流转，把零散的灵感沉淀为可执行的创作计划。"
    :features="[
      '新建选题：标题、赛道、目标平台、预计发布时间',
      '选题标签与分类管理',
      '选题排期日历视图',
      '灵感快速随手记录',
      '优质竞品选题收藏',
      '状态流转：草稿 → 制作中 → 待发布 → 已发布 → 归档',
    ]"
  />
</template>
