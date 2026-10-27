<script setup lang="ts">
import ModulePlaceholder from "@/components/ModulePlaceholder.vue";
</script>

<template>
  <ModulePlaceholder
    title="投流监控 · ROI 分析 · 核心差异化"
    description="对接巨量千川、小红书薯条、视频号推广，统一拉取投放计划与消耗、曝光、点击、转化、成交指标，自动计算 ROI，并把投放计划与作品绑定，实现内容效果和投放效果联动复盘。"
    :features="[
      '统一拉取千川 / 薯条 / 视频号推广投放计划',
      '投放指标：消耗 / 曝光 / 点击 / 转化 / 成交金额',
      '自动计算 ROI',
      '投放计划绑定作品，内容 × 投放联动复盘',
      '投流异常告警：消耗突增、转化暴跌',
      '投流复盘报表',
    ]"
  />
</template>
